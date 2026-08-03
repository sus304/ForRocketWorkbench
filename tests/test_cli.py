"""Service client / CLI (design §4.3, Phase 10).

ServiceClient is the HTTP client shared by the `wb` CLI and (later) the GUI. Tests drive it
against an in-process app via the FastAPI TestClient injected as the session, so submit /
status / list / cancel / pull are covered without a live socket. One end-to-end test starts a
real worker and runs the full submit -> poll -> pull cycle with the ForRocket binary.
"""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.store import JobStore
from service.worker import Worker
from service.api import create_app
from service.client import ServiceClient

TOKEN = "cli-token"

_STUB_RUNNER = ('import sys,os\nargs=sys.argv[1:]\nwd=None\n'
                'for i,a in enumerate(args):\n'
                '    if a in ("-w","--work-dir"): wd=args[i+1]\n'
                'if wd:\n    open(os.path.join(wd,"summary.csv"),"w").write("stat,val\\napogee,1\\n")\n'
                'sys.exit(0)\n')
_STUB_POST = 'import sys\nsys.exit(0)\n'


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
def sc(store, worker):
    app = create_app(store, worker, TOKEN)
    return ServiceClient("", TOKEN, session=TestClient(app))


@pytest.fixture
def example(projects_dir):
    return Path(projects_dir) / "example"


def test_submit_returns_id_and_queues(sc, store, example):
    out = sc.submit(example, "trajectory", model_name="ROCKET-A")
    jid = out["id"]
    assert out["status"] == "queued"
    assert store.get(jid).model_name == "ROCKET-A"


def test_status_and_list(sc, example):
    jid = sc.submit(example, "trajectory")["id"]
    assert sc.status(jid)["id"] == jid
    assert any(j["id"] == jid for j in sc.list_jobs())


def test_cancel(sc, example):
    jid = sc.submit(example, "trajectory")["id"]
    sc.cancel(jid)
    assert sc.status(jid)["status"] == "cancelled"


def test_rerun_client_and_cli(sc, store, example):
    """The client's rerun() and the `wb rerun` sub-command reach the same endpoint. The source is
    cancelled first because a re-run is only offered for a finished job."""
    from cli import wb

    jid = sc.submit(example, "trajectory")["id"]
    sc.cancel(jid)

    new = sc.rerun(jid, memo="after solver fix")
    assert new["rerun_of"] == jid
    assert new["memo"] == "after solver fix"
    assert new["input_hash"] == sc.status(jid)["input_hash"]

    sc.cancel(new["id"])
    assert wb.main(["rerun", str(new["id"])], client=sc) == 0
    assert sc.status(store.list()[0].id)["rerun_of"] == new["id"]


def test_pull_extracts_result(sc, store, worker, tmp_path, example):
    # fabricate a completed job with a result dir
    jid = store.create_preparing(mode="montecarlo")
    store.mark_queued(jid)
    rd = worker.run_dir_for(jid)
    rd.mkdir(parents=True)
    store.claim_next()
    wd = rd / "work_montecarlo"
    wd.mkdir()
    (wd / "summary.csv").write_text("stat,val\napogee,1234\n")
    store.set_work_dir(jid, str(wd.resolve()))
    store.mark_completed(jid, result_dir=str(wd.resolve()))

    dest = tmp_path / "pulled"
    sc.pull(jid, dest)
    assert (dest / "summary.csv").exists()


def test_bad_token_is_rejected(store, worker, example):
    app = create_app(store, worker, TOKEN)
    bad = ServiceClient("", "wrong", session=TestClient(app))
    with pytest.raises(Exception):
        bad.list_jobs()


def test_cli_end_to_end(binary_path, store, tmp_path, projects_dir):
    repo = Path(__file__).resolve().parent.parent
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(repo / "runner.py"), post_py=str(repo / "post.py"), poll=0.05)
    sc = ServiceClient("", TOKEN, session=TestClient(create_app(store, w, TOKEN)))
    w.start()
    try:
        jid = sc.submit(Path(projects_dir) / "example", "trajectory")["id"]
        deadline = time.time() + 180
        while time.time() < deadline:
            if sc.status(jid)["status"] in ("completed", "failed"):
                break
            time.sleep(0.2)
        assert sc.status(jid)["status"] == "completed"
        dest = tmp_path / "pulled"
        sc.pull(jid, dest)
        assert any(dest.iterdir())
    finally:
        w.stop()
