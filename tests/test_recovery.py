"""Startup recovery (design §4.2, §8).

When the service restarts after a host reboot/crash, jobs left `running` are recovered:
  - Monte Carlo with a usable persisted work_dir  -> automatic resume (runner.py -r).
  - short modes (trajectory/area/sensitivity)     -> requeued, re-run from scratch.
  - MC without a usable work_dir                  -> requeued (fresh).
cancelled/failed/completed rows are terminal and never resumed.
"""
import sys
from pathlib import Path

import pytest

from service.store import JobStore, QUEUED, RUNNING, COMPLETED, CANCELLED
from service.worker import Worker

# stub runner handles BOTH a fresh run (-w) and a resume (-r): it writes ran.txt into
# whichever work dir it was given, so orchestration is verifiable without the binary.
_STUB_RUNNER = '''\
import sys, os
args = sys.argv[1:]
wd = None
for i, a in enumerate(args):
    if a in ("-w", "--work-dir", "-r", "--resume-work-dir"):
        wd = args[i + 1]
print("stub runner: " + " ".join(args))
if wd:
    open(os.path.join(wd, "ran.txt"), "w").write("ok")
sys.exit(0)
'''
_STUB_POST = 'import sys, os\nopen(os.path.join(sys.argv[-1], "post_done.txt"), "w").write("ok")\nsys.exit(0)\n'


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


@pytest.fixture
def worker(tmp_path, store):
    (tmp_path / "stub_runner.py").write_text(_STUB_RUNNER)
    (tmp_path / "stub_post.py").write_text(_STUB_POST)
    return Worker(store, tmp_path / "data", python=sys.executable,
                  runner_py=str(tmp_path / "stub_runner.py"),
                  post_py=str(tmp_path / "stub_post.py"), poll=0.05)


def _crash_a_running_job(worker, store, mode, with_work_dir=True):
    """Simulate a job that was running when the process died: claimed (running) with a
    work_dir on disk, but no terminal state recorded."""
    jid = store.enqueue(mode=mode)
    run_dir = worker.run_dir_for(jid)
    run_dir.mkdir(parents=True)
    store.claim_next()
    if with_work_dir:
        wd = run_dir / ("work_montecarlo" if mode == "montecarlo" else "work_" + mode)
        wd.mkdir()
        (wd / "cases").mkdir()
        (wd / "completed_cases.txt").write_text("0_case\n")
        store.set_work_dir(jid, str(wd.resolve()))
    return jid


def test_recover_requeues_short_running_job(worker, store):
    jid = _crash_a_running_job(worker, store, "trajectory")
    resumable = worker.recover()
    assert resumable == []
    assert store.get(jid).status == QUEUED
    assert store.get(jid).work_dir == ""  # cleared for fresh re-run


def test_recover_flags_montecarlo_as_resumable_and_keeps_running(worker, store):
    jid = _crash_a_running_job(worker, store, "montecarlo")
    resumable = worker.recover()
    assert [j.id for j in resumable] == [jid]
    assert store.get(jid).status == RUNNING  # not requeued; will resume in place


def test_recover_requeues_montecarlo_without_workdir(worker, store):
    jid = _crash_a_running_job(worker, store, "montecarlo", with_work_dir=False)
    resumable = worker.recover()
    assert resumable == []
    assert store.get(jid).status == QUEUED


def test_resume_one_runs_only_remaining_and_completes(worker, store):
    jid = _crash_a_running_job(worker, store, "montecarlo")
    (resumable,) = worker.recover()
    worker.resume_one(resumable)
    done = store.get(jid)
    assert done.status == COMPLETED
    wd = Path(done.work_dir)
    assert (wd / "ran.txt").exists()       # resume actually invoked the runner
    assert (wd / "post_done.txt").exists()  # post ran after resume


def test_recover_ignores_terminal_jobs(worker, store):
    a = store.enqueue(mode="montecarlo")
    store.claim_next()
    store.mark_cancelled(a)
    assert worker.recover() == []
    assert store.get(a).status == CANCELLED


def test_start_resumes_then_drains_queue(worker, store):
    import time
    # a crashed MC to resume...
    mc = _crash_a_running_job(worker, store, "montecarlo")
    # ...and a fresh queued trajectory behind it
    tj = store.enqueue(mode="trajectory")
    worker.run_dir_for(tj).mkdir(parents=True)

    worker.start()
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if store.get(mc).status == COMPLETED and store.get(tj).status == COMPLETED:
                break
            time.sleep(0.05)
    finally:
        worker.stop()
    assert store.get(mc).status == COMPLETED
    assert store.get(tj).status == COMPLETED
