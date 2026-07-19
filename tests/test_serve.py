"""Bind-host restriction and single-instance lock (design §7; review 🔴E, 🟡 multi-start).

The service must never expose itself on the university LAN: it binds only to loopback or the
tailscale interface, where tailnet ACLs apply. And only one instance may own the store/run
tree at a time (systemd + a stray manual start must not both run).
"""
import sys

import pytest
from fastapi.testclient import TestClient

from service.serve import (
    validate_bind_host, BindError, SingleInstanceLock, AlreadyRunning, build_service,
)
from service.client import ServiceClient


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "100.101.102.103"])
def test_allowed_bind_hosts(host):
    assert validate_bind_host(host) == host


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "10.0.0.5", "8.8.8.8"])
def test_rejected_bind_hosts(host):
    with pytest.raises(BindError):
        validate_bind_host(host)


def test_single_instance_lock_blocks_second_holder(tmp_path):
    lock_path = tmp_path / "service.lock"
    first = SingleInstanceLock(lock_path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunning):
            SingleInstanceLock(lock_path).acquire()
    finally:
        first.release()


def test_single_instance_lock_reacquire_after_release(tmp_path):
    lock_path = tmp_path / "service.lock"
    a = SingleInstanceLock(lock_path)
    a.acquire()
    a.release()
    b = SingleInstanceLock(lock_path)
    b.acquire()  # must succeed now
    b.release()


def test_single_instance_lock_context_manager(tmp_path):
    lock_path = tmp_path / "service.lock"
    with SingleInstanceLock(lock_path):
        with pytest.raises(AlreadyRunning):
            SingleInstanceLock(lock_path).acquire()


# --- service wiring -----------------------------------------------------------

_STUB_RUNNER = ('import sys,os\nargs=sys.argv[1:]\nwd=None\n'
                'for i,a in enumerate(args):\n'
                '    if a in ("-w","--work-dir"): wd=args[i+1]\n'
                'if wd: open(os.path.join(wd,"ok.txt"),"w").write("ok")\nsys.exit(0)\n')
_STUB_POST = 'import sys\nsys.exit(0)\n'


class _RecNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, title, message, priority="default"):
        self.calls.append((title, message, priority))
        return True


def _stub_service(tmp_path, token, notifier=None):
    (tmp_path / "r.py").write_text(_STUB_RUNNER)
    (tmp_path / "p.py").write_text(_STUB_POST)
    return build_service(
        tmp_path / "data", token, notifier=notifier,
        python=sys.executable, runner_py=str(tmp_path / "r.py"),
        post_py=str(tmp_path / "p.py"), poll=0.05,
    )


def test_build_service_serves_health_and_enforces_token(tmp_path):
    store, worker, app = _stub_service(tmp_path, "tok")
    try:
        c = TestClient(app)
        assert c.get("/health").json()["status"] == "ok"
        assert c.get("/jobs").status_code == 401
        assert c.get("/jobs", headers={"Authorization": "Bearer tok"}).status_code == 200
    finally:
        store.close()


def test_build_service_notifies_on_completion(tmp_path):
    rec = _RecNotifier()
    store, worker, app = _stub_service(tmp_path, "tok", notifier=rec)
    try:
        jid = store.enqueue(mode="trajectory")
        worker.run_dir_for(jid).mkdir(parents=True)
        worker.run_one(store.claim_next())
        assert any(str(jid) in title and "completed" in title for title, _, _ in rec.calls)
    finally:
        store.close()

