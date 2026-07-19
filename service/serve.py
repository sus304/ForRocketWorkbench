"""Service entrypoint helpers: bind-host restriction and single-instance locking (design §7).

The compute service must not be reachable on the university LAN. It binds only to loopback
(use case ②) or the tailscale interface (use case ③), where tailnet ACLs apply; binding to
0.0.0.0 or a LAN address is refused outright. A file lock guarantees a single instance owns
the store and run tree, so a stray manual start cannot collide with the systemd unit.
"""
from __future__ import annotations

import fcntl
import ipaddress
import os
from pathlib import Path

from service.store import JobStore
from service.worker import Worker
from service.notify import Notifier
from service.api import create_app

# Tailscale hands out addresses from the 100.64.0.0/10 CGNAT range.
_TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}


class BindError(Exception):
    """Requested bind host is neither loopback nor a tailscale-interface address."""


class AlreadyRunning(Exception):
    """Another instance already holds the service lock."""


def validate_bind_host(host: str) -> str:
    """Return host if it is safe to bind to (loopback or tailnet), else raise BindError."""
    if host in _LOOPBACK_NAMES:
        return host
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise BindError(f"not an IP address or loopback name: {host!r}")
    if ip.is_loopback:
        return host
    if ip.version == 4 and ip in _TAILSCALE_NET:
        return host
    raise BindError(
        f"refusing to bind to non-loopback/non-tailnet host: {host!r} "
        "(bind to 127.0.0.1 for local use or the tailscale0 address for the server)"
    )


def _event_handler(store: JobStore, notifier: Notifier):
    """Fire a notification when a job reaches a terminal state (design §8)."""
    def handler(job_id, status, summary=""):
        job = store.get(job_id)
        mode = job.mode if job else ""
        model = job.model_name if job else ""
        title = f"Job {job_id} {status}"
        message = summary or f"{mode} {model} -> {status}".strip()
        notifier.notify(title, message, priority="high" if status == "failed" else "default")
    return handler


def build_service(data_root, token, notifier: Notifier = None, **worker_kwargs):
    """Wire the store, worker (with notifier hook) and API app together. Returns
    (store, worker, app). Does not start the worker or the HTTP server."""
    data_root = Path(data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    store = JobStore(data_root / "jobs.db")
    notifier = notifier if notifier is not None else Notifier()
    worker = Worker(store, data_root, on_event=_event_handler(store, notifier), **worker_kwargs)
    app = create_app(store, worker, token)
    return store, worker, app


def run(host: str, port: int, data_root, token: str) -> None:  # pragma: no cover
    """Serve the API bound only to a safe host, single-instance, with the worker running.

    The worker starts first so startup recovery (resume interrupted MC) happens before the
    API accepts new work.
    """
    import uvicorn

    if not token:
        raise ValueError("WB_API_TOKEN is empty; refusing to start with an open API "
                         "(set the token or use the local auto-generated secret)")
    host = validate_bind_host(host)
    data_root = Path(data_root)
    with SingleInstanceLock(data_root / "service.lock"):
        store, worker, app = build_service(data_root, token)
        worker.start()
        try:
            uvicorn.run(app, host=host, port=port)
        finally:
            worker.stop()
            store.close()


class SingleInstanceLock:
    """Advisory whole-file lock (flock). One holder at a time; a second acquire on the same
    path raises AlreadyRunning."""

    def __init__(self, path):
        self._path = str(path)
        self._fh = None

    def acquire(self) -> "SingleInstanceLock":
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._path, "w")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise AlreadyRunning(f"another instance holds {self._path}")
        fh.write(str(os.getpid()))
        fh.flush()
        self._fh = fh
        return self

    def release(self) -> None:
        if self._fh is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


def _cli(argv=None):  # pragma: no cover
    import argparse
    p = argparse.ArgumentParser(prog="service.serve", description="Run the compute job service")
    p.add_argument("--host", default=os.environ.get("WB_BIND_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("WB_PORT", "8760")))
    p.add_argument("--data-root", default=os.environ.get("WB_DATA_ROOT", "service_data"))
    p.add_argument("--token", default=os.environ.get("WB_API_TOKEN", ""))
    a = p.parse_args(argv)
    run(a.host, a.port, a.data_root, a.token)


if __name__ == "__main__":  # pragma: no cover
    _cli()
