"""Worker orchestration tests (design §4.2).

The worker is the single-FIFO executor: it claims the oldest queued job, creates and
persists its work_dir, spawns runner.py as a subprocess it owns (so the run outlives any
UI), runs post, and records the terminal state. cancel terminates the running subprocess.

Most tests use stub runner/post scripts so orchestration (completed / failed / cancelled /
FIFO draining / work_dir persistence) is deterministic and binary-free. One end-to-end test
drives the real ForRocket binary through a trajectory run.
"""
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from service.store import JobStore, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
from service.worker import Worker


# --- stub runner/post scripts -------------------------------------------------

_STUB_RUNNER = '''\
import sys, os, time
args = sys.argv[1:]
wd = None
for i, a in enumerate(args):
    if a in ("-w", "--work-dir"):
        wd = args[i + 1]
rd = os.getcwd()
def _read(name, default):
    p = os.path.join(rd, name)
    return open(p).read().strip() if os.path.exists(p) else default
time.sleep(float(_read("_stub_sleep", "0") or 0))
code = int(_read("_stub_exit", "0") or 0)
print("stub runner mode-args: " + " ".join(args))
if code == 0 and wd:
    open(os.path.join(wd, "ran.txt"), "w").write("ok")
else:
    sys.stderr.write("stub failure\\n")
sys.exit(code)
'''

_STUB_POST = '''\
import sys, os
wd = sys.argv[-1]
open(os.path.join(wd, "post_done.txt"), "w").write("ok")
sys.exit(0)
'''


@pytest.fixture
def stubs(tmp_path):
    r = tmp_path / "stub_runner.py"
    p = tmp_path / "stub_post.py"
    r.write_text(_STUB_RUNNER)
    p.write_text(_STUB_POST)
    return r, p


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


@pytest.fixture
def worker(tmp_path, store, stubs):
    runner_py, post_py = stubs
    data_root = tmp_path / "data"
    w = Worker(store, data_root, python=sys.executable,
               runner_py=str(runner_py), post_py=str(post_py), poll=0.05)
    return w


def _prepare_run_dir(worker, job_id, exit_code=None, sleep=None):
    """Create the per-job run dir the worker will cd into (uploads do this in production)."""
    rd = worker.run_dir_for(job_id)
    rd.mkdir(parents=True, exist_ok=True)
    if exit_code is not None:
        (rd / "_stub_exit").write_text(str(exit_code))
    if sleep is not None:
        (rd / "_stub_sleep").write_text(str(sleep))
    return rd


def test_run_one_completes_and_persists_work_dir(worker, store):
    jid = store.enqueue(mode="trajectory")
    _prepare_run_dir(worker, jid)
    job = store.claim_next()
    worker.run_one(job)

    done = store.get(jid)
    assert done.status == COMPLETED
    assert done.work_dir  # persisted
    wd = Path(done.work_dir)
    assert wd.is_dir()
    assert (wd / "ran.txt").exists()          # runner ran with the provided work_dir
    assert (wd / "post_done.txt").exists()     # post ran
    assert done.result_dir == str(wd)


def test_work_dir_persisted_before_run_completes(worker, store):
    """The work_dir must be in the DB while the job is still running, so a crash mid-run
    leaves a resume anchor. Use a sleeping stub and check the DB from another thread."""
    jid = store.enqueue(mode="montecarlo")
    _prepare_run_dir(worker, jid, sleep=0.6)
    job = store.claim_next()

    t = threading.Thread(target=worker.run_one, args=(job,))
    t.start()
    try:
        deadline = time.time() + 2.0
        seen = ""
        while time.time() < deadline:
            seen = store.get(jid).work_dir
            if seen:
                break
            time.sleep(0.02)
        assert seen, "work_dir must be persisted before the run finishes"
        assert store.get(jid).status == RUNNING
    finally:
        t.join(5)
    assert store.get(jid).status == COMPLETED


def test_run_one_failure_marks_failed_with_output(worker, store):
    jid = store.enqueue(mode="area")
    _prepare_run_dir(worker, jid, exit_code=3)
    job = store.claim_next()
    worker.run_one(job)

    failed = store.get(jid)
    assert failed.status == FAILED
    assert failed.error_message  # captured runner output / exit info


def test_cancel_running_job_marks_cancelled(worker, store):
    jid = store.enqueue(mode="montecarlo")
    _prepare_run_dir(worker, jid, sleep=3.0)
    job = store.claim_next()

    t = threading.Thread(target=worker.run_one, args=(job,))
    t.start()
    # wait until the worker is actually running this job
    deadline = time.time() + 2.0
    while time.time() < deadline and not worker.is_running(jid):
        time.sleep(0.02)
    assert worker.is_running(jid)
    assert worker.cancel(jid) is True
    t.join(5)

    assert store.get(jid).status == CANCELLED


def test_cancel_queued_job_never_runs(worker, store):
    a = store.enqueue(mode="montecarlo")
    b = store.enqueue(mode="trajectory")
    # cancel b while nothing is running -> cancelled without ever executing
    assert worker.cancel(b) is True
    assert store.get(b).status == CANCELLED
    _prepare_run_dir(worker, a)
    job = store.claim_next()
    assert job.id == a  # b was cancelled, so a is next
    worker.run_one(job)
    assert store.get(a).status == COMPLETED
    # b never got a run dir / work_dir
    assert store.get(b).work_dir == ""


def test_loop_drains_queue_in_fifo_order(worker, store):
    ids = [store.enqueue(mode="trajectory") for _ in range(3)]
    for jid in ids:
        _prepare_run_dir(worker, jid)
    worker.start()
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if all(store.get(i).status == COMPLETED for i in ids):
                break
            time.sleep(0.05)
    finally:
        worker.stop()
    statuses = [store.get(i).status for i in ids]
    assert statuses == [COMPLETED, COMPLETED, COMPLETED]
    # FIFO: started_at increases with enqueue order
    starts = [store.get(i).started_at for i in ids]
    assert starts == sorted(starts)


# --- end-to-end with the real binary -----------------------------------------

def test_run_one_trajectory_end_to_end(binary_path, store, tmp_path, projects_dir):
    """Real runner.py + real ForRocket binary: a trajectory job runs to completion and
    leaves outputs in the service-owned work_dir."""
    import shutil
    repo_root = Path(__file__).resolve().parent.parent
    data_root = tmp_path / "data"
    w = Worker(store, data_root, python=sys.executable,
               runner_py=str(repo_root / "runner.py"), post_py=str(repo_root / "post.py"),
               poll=0.05)

    jid = store.enqueue(mode="trajectory", model_name="ROCKET-A")
    run_dir = w.run_dir_for(jid)
    shutil.copytree(Path(projects_dir) / "example", run_dir)

    job = store.claim_next()
    w.run_one(job)

    done = store.get(jid)
    assert done.status == COMPLETED, done.error_message
    wd = Path(done.work_dir)
    assert wd.is_dir()
    assert wd.name.startswith("work_trajectory")
    assert any(wd.iterdir())
