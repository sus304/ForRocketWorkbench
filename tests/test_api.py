"""HTTP API tests (design §5, §7).

Auth (Bearer token), job submission with hardened upload, listing/detail with live progress,
cancel, and result download (light vs full). Most tests use a stub-runner worker so they are
fast and binary-free; one end-to-end test drives the real binary through submit -> run ->
download.
"""
import io
import json
import sys
import tarfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.store import JobStore, RUNNING, CANCELLED, COMPLETED, FAILED
from service.worker import Worker
from service.uploads import pack_closure
from service.api import create_app

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_STUB_RUNNER = ('import sys,os\nargs=sys.argv[1:]\nwd=None\n'
                'for i,a in enumerate(args):\n'
                '    if a in ("-w","--work-dir","-r","--resume-work-dir"): wd=args[i+1]\n'
                'if wd: open(os.path.join(wd,"ran.txt"),"w").write("ok")\nsys.exit(0)\n')
_STUB_POST = 'import sys,os\nopen(os.path.join(sys.argv[-1],"post_done.txt"),"w").write("ok")\n'


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


@pytest.fixture
def worker(tmp_path, store):
    (tmp_path / "r.py").write_text(_STUB_RUNNER)
    (tmp_path / "p.py").write_text(_STUB_POST)
    return Worker(store, tmp_path / "data", python=sys.executable,
                  runner_py=str(tmp_path / "r.py"), post_py=str(tmp_path / "p.py"), poll=0.05)


@pytest.fixture
def client(store, worker):
    return TestClient(create_app(store, worker, TOKEN))


@pytest.fixture
def closure(projects_dir):
    return pack_closure(Path(projects_dir) / "example", "trajectory")


def _submit(client, blob, mode="trajectory", **data):
    return client.post(
        "/jobs",
        headers=AUTH,
        data={"mode": mode, **data},
        files={"payload": ("closure.tar.gz", blob, "application/gzip")},
    )


# --- auth ---------------------------------------------------------------------

def test_requires_bearer_token(client):
    assert client.get("/jobs").status_code == 401
    assert client.get("/jobs", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/jobs", headers=AUTH).status_code == 200


def test_health_is_unauthenticated(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_reports_disk_and_stall(client, store, worker):
    import os
    import time
    jid = store.create_preparing(mode="montecarlo")
    store.mark_queued(jid)
    run_dir = worker.run_dir_for(jid)
    run_dir.mkdir(parents=True)
    store.claim_next()  # -> running
    wd = run_dir / "work_montecarlo"
    (wd / "cases").mkdir(parents=True)
    manifest = wd / "completed_cases.txt"
    manifest.write_text("0_c\n")
    old = time.time() - 120
    os.utime(manifest, (old, old))
    store.set_work_dir(jid, str(wd.resolve()))

    h = client.get("/health").json()
    assert h["disk_free_bytes"] > 0
    assert h["running_stall_seconds"] is not None
    assert h["running_stall_seconds"] >= 60  # manifest has not advanced for ~120s


# --- submit -------------------------------------------------------------------

def test_submit_creates_queued_job_with_extracted_inputs(client, worker, closure):
    r = _submit(client, closure, model_name="ROCKET-A")
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    assert r.json()["status"] == "queued"
    run_dir = worker.run_dir_for(jid)
    assert (run_dir / "config_solver.json").exists()  # inputs staged before queued
    detail = client.get(f"/jobs/{jid}", headers=AUTH).json()
    assert detail["mode"] == "trajectory"
    assert detail["model_name"] == "ROCKET-A"


def test_submit_rejects_unknown_mode(client, closure):
    assert _submit(client, closure, mode="bogus").status_code == 400


def test_submit_rejects_malicious_upload(client, store):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        ti = tarfile.TarInfo("../escape.txt")
        data = b"pwned"
        ti.size = len(data)
        tar.addfile(ti, io.BytesIO(data))
    r = _submit(client, buf.getvalue())
    assert r.status_code == 400
    # the job must not be left runnable
    assert all(j.status == FAILED for j in store.list()) or store.list() == []
    assert not any(j.status in ("queued", "preparing") for j in store.list())


# --- list / detail / cancel ---------------------------------------------------

def test_list_and_get_job(client, closure):
    jid = _submit(client, closure).json()["id"]
    listing = client.get("/jobs", headers=AUTH).json()["jobs"]
    assert any(j["id"] == jid for j in listing)
    detail = client.get(f"/jobs/{jid}", headers=AUTH)
    assert detail.status_code == 200
    assert detail.json()["capability"]["can_cancel"] is True


def test_get_missing_job_404(client):
    assert client.get("/jobs/9999", headers=AUTH).status_code == 404


def test_cancel_queued_job(client, closure):
    jid = _submit(client, closure).json()["id"]
    r = client.post(f"/jobs/{jid}/cancel", headers=AUTH)
    assert r.status_code == 200
    assert client.get(f"/jobs/{jid}", headers=AUTH).json()["status"] == "cancelled"


# --- progress -----------------------------------------------------------------

def test_montecarlo_progress_reported(client, store, worker):
    jid = store.create_preparing(mode="montecarlo")
    store.mark_queued(jid)
    run_dir = worker.run_dir_for(jid)
    run_dir.mkdir(parents=True)
    (run_dir / "config_montecarlo.json").write_text(json.dumps({"MonteCarlo Case Count": 8}))
    store.claim_next()
    wd = run_dir / "work_montecarlo"
    wd.mkdir()
    (wd / "cases").mkdir()
    (wd / "completed_cases.txt").write_text("0_c\n1_c\n2_c\n")
    store.set_work_dir(jid, str(wd.resolve()))

    prog = client.get(f"/jobs/{jid}", headers=AUTH).json()["progress"]
    assert prog == {"done": 3, "total": 8}


# --- result download ----------------------------------------------------------

def _fabricate_completed(store, worker, mode="montecarlo"):
    jid = store.create_preparing(mode=mode)
    store.mark_queued(jid)
    run_dir = worker.run_dir_for(jid)
    run_dir.mkdir(parents=True)
    store.claim_next()
    wd = run_dir / ("work_montecarlo")
    (wd / "cases").mkdir(parents=True)
    (wd / "summary.csv").write_text("stat,val\napogee,1234\n")
    (wd / "cases" / "0_flight_log.csv").write_text("t,x\n0,0\n")
    store.set_work_dir(jid, str(wd.resolve()))
    store.mark_completed(jid, result_dir=str(wd.resolve()))
    return jid


def _tar_names(blob: bytes):
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as t:
        return set(t.getnames())


def test_result_light_excludes_case_logs(client, store, worker):
    jid = _fabricate_completed(store, worker)
    r = client.get(f"/jobs/{jid}/result.tar.gz", headers=AUTH)
    assert r.status_code == 200
    names = _tar_names(r.content)
    assert "summary.csv" in names
    assert not any(n.startswith("cases/") for n in names)


def test_result_full_includes_case_logs(client, store, worker):
    jid = _fabricate_completed(store, worker)
    r = client.get(f"/jobs/{jid}/result.tar.gz?full=1", headers=AUTH)
    names = _tar_names(r.content)
    assert "summary.csv" in names
    assert any(n.startswith("cases/") for n in names)


def test_result_conflict_before_completion(client, closure):
    jid = _submit(client, closure).json()["id"]
    assert client.get(f"/jobs/{jid}/result.tar.gz", headers=AUTH).status_code == 409


# --- end to end with the real binary -----------------------------------------

def test_submit_run_download_end_to_end(binary_path, store, tmp_path, projects_dir):
    repo = Path(__file__).resolve().parent.parent
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(repo / "runner.py"), post_py=str(repo / "post.py"), poll=0.05)
    client = TestClient(create_app(store, w, TOKEN))
    blob = pack_closure(Path(projects_dir) / "example", "trajectory")

    w.start()
    try:
        jid = _submit(client, blob, model_name="ROCKET-A").json()["id"]
        deadline = time.time() + 180
        status = None
        while time.time() < deadline:
            status = client.get(f"/jobs/{jid}", headers=AUTH).json()["status"]
            if status in ("completed", "failed"):
                break
            time.sleep(0.2)
        assert status == "completed"
        r = client.get(f"/jobs/{jid}/result.tar.gz", headers=AUTH)
        assert r.status_code == 200
        assert len(_tar_names(r.content)) > 0
    finally:
        w.stop()
