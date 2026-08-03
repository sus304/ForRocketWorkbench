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

# Spawns a child of its own before sleeping, the way runner.py spawns solvers, and records its
# pid so a test can assert the whole tree died — not just the process the worker holds.
_STUB_RUNNER_WITH_CHILD = '''\
import os, subprocess, sys, time
rd = os.getcwd()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(os.path.join(rd, "_child_pid"), "w").write(str(child.pid))
time.sleep(60)
'''

# Writes the stop-flag path it was given, then waits for the flag to appear and exits 0 —
# the cooperative pause runner.py implements for montecarlo.
_STUB_RUNNER_STOP_FLAG = '''\
import os, sys, time
args = sys.argv[1:]
flag = None
for i, a in enumerate(args):
    if a == "--stop-flag-file":
        flag = args[i + 1]
open(os.path.join(os.getcwd(), "_flag_arg"), "w").write(flag or "")
deadline = time.time() + 60
while time.time() < deadline:
    if flag and os.path.exists(flag):
        sys.exit(0)
    time.sleep(0.05)
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


# --- the loop must outlive any single job -------------------------------------
#
# A worker thread that dies stops the queue silently: jobs stay `running` with nothing behind
# them, cancel has no process to signal, and only a service restart brings execution back. A
# full disk did exactly that once — the ENOSPC surfaced as a SQLite error inside mark_failed
# and unwound straight out of the thread.

def _wait_for(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_loop_survives_a_job_that_raises(worker, store):
    boom = store.enqueue(mode="trajectory")
    later = store.enqueue(mode="trajectory")
    _prepare_run_dir(worker, boom)
    _prepare_run_dir(worker, later)

    real_run_one = worker.run_one

    def exploding(job):
        if job.id == boom:
            raise RuntimeError("database or disk is full")
        return real_run_one(job)

    worker.run_one = exploding
    worker.start()
    try:
        assert _wait_for(lambda: store.get(later).status == COMPLETED), \
            "the queue must keep draining after a job blew up"
        assert worker.is_alive()
    finally:
        worker.stop()

    failed = store.get(boom)
    assert failed.status == FAILED
    assert "worker error" in failed.error_message


def test_loop_survives_a_store_that_cannot_record_the_failure(worker, store, monkeypatch):
    """The disk-full case: the job fails AND the store cannot be written. The worker must give
    up on recording it rather than die, leaving a row a later cancel can still release."""
    monkeypatch.setattr("service.worker._ERROR_BACKOFF_SEC", 0.01)
    jid = store.enqueue(mode="trajectory")
    _prepare_run_dir(worker, jid)

    def unwritable(*a, **k):
        raise RuntimeError("database or disk is full")

    monkeypatch.setattr(worker, "run_one", unwritable)
    monkeypatch.setattr(store, "mark_failed", unwritable)

    worker.start()
    try:
        assert _wait_for(lambda: store.get(jid).status == RUNNING and worker.is_alive())
        time.sleep(0.2)
        assert worker.is_alive(), "an unwritable store must not take the worker down"
    finally:
        worker.stop()


# --- cancel reaches the whole process tree ------------------------------------

def test_cancel_kills_the_solver_children_too(tmp_path, store, stubs):
    """Signalling only the direct child left solvers orphaned and still burning cores."""
    _, post_py = stubs
    runner_py = tmp_path / "stub_runner_child.py"
    runner_py.write_text(_STUB_RUNNER_WITH_CHILD)
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(runner_py), post_py=str(post_py), poll=0.05)

    jid = store.enqueue(mode="montecarlo")
    run_dir = _prepare_run_dir(w, jid)
    job = store.claim_next()
    t = threading.Thread(target=w.run_one, args=(job,))
    t.start()
    try:
        pid_file = run_dir / "_child_pid"
        assert _wait_for(lambda: pid_file.exists() and pid_file.read_text().strip())
        child_pid = int(pid_file.read_text().strip())
        assert w.cancel(jid) is True
    finally:
        t.join(30)

    assert store.get(jid).status == CANCELLED

    def _gone():
        try:
            os.kill(child_pid, 0)
        except OSError:
            return True
        return False

    assert _wait_for(_gone), f"solver child {child_pid} outlived the cancel"


def test_cancel_releases_a_running_row_with_no_process(worker, store):
    """A row left `running` by a dead worker is otherwise stuck active forever: it cannot be
    cancelled, deleted or re-run, and every health reading looks like a stalled job."""
    jid = store.enqueue(mode="montecarlo")
    store.claim_next()
    assert store.get(jid).status == RUNNING
    assert worker.current_job_id() is None  # nothing is executing it

    assert worker.cancel(jid) is True
    assert store.get(jid).status == CANCELLED


# --- low disk stops a run before ENOSPC corrupts it ---------------------------

def test_job_is_refused_when_disk_is_below_the_floor(tmp_path, store, stubs, monkeypatch):
    runner_py, post_py = stubs
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(runner_py), post_py=str(post_py), poll=0.05,
               disk_floor_bytes=20 * 1024 ** 3)
    monkeypatch.setattr(w, "disk_free_bytes", lambda: 1 * 1024 ** 3)

    jid = store.enqueue(mode="montecarlo")
    _prepare_run_dir(w, jid)
    job = store.claim_next()
    w.run_one(job)

    refused = store.get(jid)
    assert refused.status == FAILED
    assert "below the" in refused.error_message and "floor" in refused.error_message
    assert not refused.work_dir or not (Path(refused.work_dir) / "ran.txt").exists()


def test_low_disk_stops_a_running_montecarlo_via_the_stop_flag(tmp_path, store, stubs,
                                                               monkeypatch):
    """MC gets a cooperative stop: in-flight cases finish, the manifest stays consistent and
    the work dir is resumable. The job is reported as a disk failure, not as the runner's
    incidental exit code."""
    monkeypatch.setattr("service.worker._DISK_POLL_SEC", 0.05)
    _, post_py = stubs
    runner_py = tmp_path / "stub_runner_flag.py"
    runner_py.write_text(_STUB_RUNNER_STOP_FLAG)
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(runner_py), post_py=str(post_py), poll=0.05,
               disk_floor_bytes=20 * 1024 ** 3)

    free = {"bytes": 100 * 1024 ** 3}
    monkeypatch.setattr(w, "disk_free_bytes", lambda: free["bytes"])

    jid = store.enqueue(mode="montecarlo")
    run_dir = _prepare_run_dir(w, jid)
    job = store.claim_next()
    t = threading.Thread(target=w.run_one, args=(job,))
    t.start()
    try:
        assert _wait_for(lambda: (run_dir / "_flag_arg").exists())
        assert (run_dir / "_flag_arg").read_text().strip(), \
            "montecarlo must be launched with --stop-flag-file"
        free["bytes"] = 1 * 1024 ** 3  # the volume fills
    finally:
        t.join(30)

    stopped = store.get(jid)
    assert stopped.status == FAILED
    assert "free space fell to" in stopped.error_message
    assert stopped.work_dir and stopped.work_dir in stopped.error_message


def test_stale_stop_flag_is_cleared_before_a_run(tmp_path, store, stubs):
    """A flag left by the previous run would pause a resume the moment it started."""
    _, post_py = stubs
    runner_py = tmp_path / "stub_runner_flag.py"
    runner_py.write_text(_STUB_RUNNER_STOP_FLAG)
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(runner_py), post_py=str(post_py), poll=0.05)

    jid = store.enqueue(mode="montecarlo")
    run_dir = _prepare_run_dir(w, jid)
    (run_dir / "stop.flag").write_text("stale")

    job = store.claim_next()
    t = threading.Thread(target=w.run_one, args=(job,))
    t.start()
    try:
        assert _wait_for(lambda: (run_dir / "_flag_arg").exists())
        time.sleep(0.3)
        assert store.get(jid).status == RUNNING, "a stale flag must not pause the new run"
        (run_dir / "stop.flag").touch()  # let the stub exit
    finally:
        t.join(30)


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


def test_cancel_during_post_takes_effect(tmp_path, store, stubs):
    """Post used to run with no registered process: cancel found nothing to signal, returned
    False, and the UI announced success anyway. The job must stay cancellable until it is
    actually finished."""
    runner_py, _ = stubs
    post_py = tmp_path / "stub_post_slow.py"
    post_py.write_text('import os, sys, time\n'
                       'open(os.path.join(os.getcwd(), "_post_started"), "w").write("1")\n'
                       'time.sleep(60)\n')
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(runner_py), post_py=str(post_py), poll=0.05)

    jid = store.enqueue(mode="montecarlo")
    run_dir = _prepare_run_dir(w, jid)
    job = store.claim_next()
    t = threading.Thread(target=w.run_one, args=(job,))
    t.start()
    try:
        assert _wait_for(lambda: (run_dir / "_post_started").exists())
        assert w.current_job_id() == jid, "the job must still be owned while post runs"
        assert w.cancel(jid) is True
    finally:
        t.join(30)

    assert store.get(jid).status == CANCELLED


def test_cancel_does_not_release_a_job_the_worker_still_owns(tmp_path, store, stubs):
    """force_cancel_running is only for orphan rows. A live run must be killed, never merely
    relabelled, or the row would say cancelled while solvers kept burning cores."""
    _, post_py = stubs
    runner_py = tmp_path / "stub_runner_child.py"
    runner_py.write_text(_STUB_RUNNER_WITH_CHILD)
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(runner_py), post_py=str(post_py), poll=0.05)

    jid = store.enqueue(mode="montecarlo")
    run_dir = _prepare_run_dir(w, jid)
    job = store.claim_next()
    t = threading.Thread(target=w.run_one, args=(job,))
    t.start()
    try:
        assert _wait_for(lambda: (run_dir / "_child_pid").exists())
        assert w.current_job_id() == jid
        w.cancel(jid)
    finally:
        t.join(30)
    assert store.get(jid).status == CANCELLED
