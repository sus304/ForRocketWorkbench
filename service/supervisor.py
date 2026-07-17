"""Local service supervision (design §4.3).

In use case ② the GUI must not embed the worker in-process (a UI crash would kill the run),
so it launches the job service as a separate process and does not kill it on exit. On the
server (③) systemd owns the service instead and the GUI/CLI just connect. is_up() lets a
client check reachability; ensure_local_service() starts a local instance if none answers.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Optional


def is_up(client) -> bool:
    """True if a service answers /health through the given client."""
    try:
        return client.health().get("status") == "ok"
    except Exception:
        return False


def ensure_local_service(client, data_root, token: str, host: str = "127.0.0.1",
                         port: int = 8760, python: str = sys.executable,
                         wait: float = 15.0) -> Optional[subprocess.Popen]:
    """Return None if a service is already up; otherwise spawn a detached local instance
    (not killed when the launcher exits) and wait until it answers /health.

    Raises TimeoutError if it does not come up in `wait` seconds."""
    if is_up(client):
        return None
    env = dict(os.environ, WB_API_TOKEN=token, WB_SERVICE_URL=f"http://{host}:{port}")
    proc = subprocess.Popen(
        [python, "-m", "service.serve", "--host", host, "--port", str(port),
         "--data-root", str(data_root)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + wait
    while time.time() < deadline:
        if is_up(client):
            return proc
        if proc.poll() is not None:
            raise RuntimeError(f"service process exited early (code {proc.returncode})")
        time.sleep(0.2)
    raise TimeoutError("local service did not become healthy in time")
