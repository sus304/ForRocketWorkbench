"""Single-FIFO worker: the compute service's executor.

It claims the oldest queued job, creates and persists the run's work_dir *before* launching
so a crash mid-run leaves a resume anchor, spawns runner.py as a subprocess it owns (the run
therefore outlives any UI), runs post, and records the terminal state. Jobs run strictly one
at a time: the MC solver is memory-bandwidth bound, so serial execution is the design choice
(docs/compute_server_design.md §4.2). cancel terminates the running subprocess.

Two properties matter as much as the happy path, both learned from a run that filled the
volume: the loop must survive any single job blowing up (an exception escaping it used to
kill the worker thread and silently stop the whole queue), and a run must be stopped while
there is still disk left, because ENOSPC tears case configs and logs to 0 bytes and leaves
the work dir unresumable.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from path_define import (
    chdir, make_unique_work_dir,
    runner_trajectory_directory, runner_area_directory,
    runner_montecarlo_directory, runner_sensitivity_directory,
)
from service.store import JobStore, RUNNING, COMPLETED, FAILED

# mode -> (runner mode flags, work_dir base name, post.py flag or None)
_MODE_FLAGS = {
    "trajectory": [],
    "area": ["-a", "config_area.json"],
    "montecarlo": ["-m", "config_montecarlo.json"],
    "sensitivity": ["-e", "config_sensitivity.json"],
}
_MODE_DIR = {
    "trajectory": runner_trajectory_directory,
    "area": runner_area_directory,
    "montecarlo": runner_montecarlo_directory,
    "sensitivity": runner_sensitivity_directory,
}
# post.py handles trajectory/area/montecarlo; runner.py posts sensitivity itself.
_POST_FLAG = {"trajectory": "-c", "area": "-a", "montecarlo": "-m"}
_MAX_THREAD_MODES = {"area", "montecarlo", "sensitivity"}

_OUTPUT_TAIL = 4000  # chars of runner/post output kept in error_message

log = logging.getLogger(__name__)

# Free-space floor for the volume holding the run tree. A run is refused below it and a run
# in progress is stopped when it drops below it, so the fill never reaches ENOSPC. 20 GiB is
# ~3 minutes of a 10k-case MC at the observed ~24 MB/case: enough room for the in-flight
# cases to land and for post to write its outputs. Override with WB_DISK_FLOOR_BYTES.
_DISK_FLOOR_DEFAULT = 20 * 1024 ** 3
_DISK_POLL_SEC = 15.0
# How long a cooperative stop (MC stop flag) is given to land before the run is killed.
_DISK_STOP_GRACE_SEC = 120.0
# How long SIGTERM is given before SIGKILL when tearing down a run's process group.
_TERM_GRACE_SEC = 15.0
# Pause after a store/worker error so a persistent failure (unwritable DB) cannot spin.
_ERROR_BACKOFF_SEC = 5.0

_STOP_FLAG_NAME = "stop.flag"


def _gb(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GiB"


class Worker:
    def __init__(self, store: JobStore, data_root, python: str = sys.executable,
                 runner_py: Optional[str] = None, post_py: Optional[str] = None,
                 poll: float = 0.5, on_event=None, disk_floor_bytes: Optional[int] = None):
        self._store = store
        self._data_root = Path(data_root)
        self._python = python
        # on_event(job_id, status, summary="") fires on terminal completed/failed states so a
        # notifier (or anything else) can react. Failures here never affect the job.
        self._on_event = on_event or (lambda *a, **k: None)
        repo_root = Path(__file__).resolve().parent.parent
        self._runner_py = runner_py or str(repo_root / "runner.py")
        self._post_py = post_py or str(repo_root / "post.py")
        self._poll = poll

        # The service runs headless (Ubuntu Server VM, or WSL). Force non-interactive
        # matplotlib/Qt so post-processing can plot without a display.
        self._env = dict(os.environ, MPLBACKEND="Agg", QT_QPA_PLATFORM="offscreen")

        floor = disk_floor_bytes
        if floor is None:
            try:
                floor = int(os.environ.get("WB_DISK_FLOOR_BYTES", "") or _DISK_FLOOR_DEFAULT)
            except ValueError:
                floor = _DISK_FLOOR_DEFAULT
        self._disk_floor = max(0, floor)

        self._lock = threading.Lock()
        # {"job_id", "proc", "cancelled", "disk_abort"} while a job runs. disk_abort holds the
        # free-byte reading that triggered a low-disk stop, so _execute can report the real
        # reason instead of the runner's incidental exit code.
        self._current = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def data_root(self) -> Path:
        return self._data_root

    @property
    def disk_floor_bytes(self) -> int:
        return self._disk_floor

    def disk_free_bytes(self) -> Optional[int]:
        """Free bytes on the volume holding the run tree, or None if it cannot be read."""
        probe = self._data_root if self._data_root.exists() else self._data_root.parent
        try:
            return shutil.disk_usage(str(probe)).free
        except OSError:
            return None

    def run_dir_for(self, job_id: int) -> Path:
        return self._data_root / "jobs" / str(job_id)

    def current_job_id(self) -> Optional[int]:
        with self._lock:
            return self._current["job_id"] if self._current else None

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # --- single job ---------------------------------------------------------

    def run_one(self, job) -> None:
        """Run a fresh job: create+persist its work_dir, then execute the runner."""
        run_dir = self.run_dir_for(job.id)
        if not run_dir.is_dir():
            self._store.mark_failed(job.id, f"run directory missing: {run_dir}")
            self._emit(job.id, FAILED)
            return

        mode = job.mode
        with chdir(str(run_dir)):
            work_name = os.path.basename(os.path.normpath(make_unique_work_dir(_MODE_DIR[mode])))
        abs_work_dir = str((run_dir / work_name).resolve())
        # persist the anchor immediately (design §4.2): the DB now knows the run's dir even
        # if the process dies before the run finishes, so recovery can resume from it.
        self._store.set_work_dir(job.id, abs_work_dir)

        cmd = [self._python, self._runner_py, "-s", "config_solver.json"]
        cmd += _MODE_FLAGS[mode]
        cmd += ["-w", work_name]
        if job.use_max_thread and mode in _MAX_THREAD_MODES:
            cmd += ["-X"]
        cmd += self._stop_flag_args(mode, run_dir)
        self._execute(job, cmd, run_dir, work_name, abs_work_dir)

    def resume_one(self, job) -> None:
        """Resume a Monte Carlo job in its persisted work_dir, running only the cases that
        did not complete before the interruption (runner.py -r)."""
        run_dir = self.run_dir_for(job.id)
        work_name = os.path.basename(os.path.normpath(job.work_dir))
        cmd = [self._python, self._runner_py, "-s", "config_solver.json",
               "-m", "config_montecarlo.json", "-r", work_name]
        if job.use_max_thread:
            cmd += ["-X"]
        cmd += self._stop_flag_args(job.mode, run_dir)
        self._execute(job, cmd, run_dir, work_name, job.work_dir)

    def _stop_flag_args(self, mode: str, run_dir: Path):
        """--stop-flag-file for the modes that can pause cooperatively (montecarlo only).

        The flag lets the low-disk guard end a long run *between* cases: in-flight cases
        finish, the completion manifest stays consistent, and the work dir is resumable. Any
        flag left behind by a previous run is cleared here, or a resume would pause instantly.
        """
        if mode != "montecarlo":
            return []
        flag = run_dir / _STOP_FLAG_NAME
        try:
            flag.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            log.warning("could not clear the stale stop flag at %s", flag)
        return ["--stop-flag-file", str(flag)]

    def _execute(self, job, cmd, run_dir: Path, work_name: str, abs_work_dir: str) -> None:
        free = self.disk_free_bytes()
        if free is not None and free < self._disk_floor:
            # Refuse rather than start a run that cannot finish: a run that hits ENOSPC does
            # not just fail, it corrupts its own work dir on the way down.
            msg = (f"not started: {_gb(free)} free on the run volume, below the "
                   f"{_gb(self._disk_floor)} floor. Free space, then re-run.")
            self._store.mark_failed(job.id, msg)
            self._emit(job.id, FAILED, msg)
            return

        self._record_solver_version(job.id, run_dir)
        stop_flag = run_dir / _STOP_FLAG_NAME if "--stop-flag-file" in cmd else None
        try:
            rc, out = self._spawn(job.id, cmd, run_dir, stop_flag)
            cancelled, disk_abort = self._run_state(job.id)

            if cancelled:
                self._store.mark_cancelled(job.id)  # user-initiated; no notification
                return
            if disk_abort is not None:
                # Checked before rc: the runner's exit code here is incidental (a signal, or a
                # write error on the way out), and the disk is the fact worth reporting.
                msg = (f"stopped: free space fell to {_gb(disk_abort)}, below the "
                       f"{_gb(self._disk_floor)} floor. The work directory is preserved at "
                       f"{abs_work_dir}.")
                self._store.mark_failed(job.id, msg)
                self._emit(job.id, FAILED, msg)
                return
            if rc != 0:
                self._store.mark_failed(job.id, f"runner.py exit {rc}\n{out[-_OUTPUT_TAIL:]}")
                self._emit(job.id, FAILED)
                return

            post_flag = _POST_FLAG.get(job.mode)
            if post_flag is not None:
                # Post runs through _spawn too, so the job stays cancellable and disk-guarded
                # for its whole active life. While post held no registered process, a cancel
                # during it did nothing at all — and, worse, looked like it had worked.
                prc, pout = self._spawn(
                    job.id, [self._python, self._post_py, post_flag, work_name], run_dir)
                cancelled, disk_abort = self._run_state(job.id)
                if cancelled:
                    self._store.mark_cancelled(job.id)
                    return
                if prc != 0:
                    reason = (f"post.py exit {prc}\n{pout[-_OUTPUT_TAIL:]}" if disk_abort is None
                              else f"post stopped: free space fell to {_gb(disk_abort)}, below "
                                   f"the {_gb(self._disk_floor)} floor.")
                    self._store.mark_failed(job.id, reason)
                    self._emit(job.id, FAILED)
                    return

            self._store.mark_completed(job.id, result_dir=abs_work_dir)
            self._emit(job.id, COMPLETED)
        finally:
            with self._lock:
                if self._current and self._current["job_id"] == job.id:
                    self._current = None

    def _run_state(self, job_id: int):
        """(cancelled, disk_abort) recorded against the job's current phase."""
        with self._lock:
            cur = self._current
            if not cur or cur["job_id"] != job_id:
                return False, None
            return bool(cur["cancelled"]), cur["disk_abort"]

    def _record_solver_version(self, job_id: int, run_dir: Path) -> None:
        """Stamp the job with the solver build about to run it, resolved from the same directory
        the runner is launched in so it names the binary that actually runs. Best-effort: a blank
        version must never stop a run."""
        try:
            from runner_tool.solver_control import solver_version_string
            version = solver_version_string(run_dir)
        except Exception:
            return
        if version:
            self._store.set_solver_version(job_id, version)

    def _emit(self, job_id: int, status: str, summary: str = "") -> None:
        try:
            self._on_event(job_id, status, summary)
        except Exception:
            pass  # a broken notifier must never affect the job

    # --- startup recovery ---------------------------------------------------

    def _resumable(self, job) -> bool:
        wd = job.work_dir
        return bool(wd and Path(wd).is_dir() and (Path(wd) / "cases").is_dir())

    def recover(self):
        """Reconcile jobs left `running` after a crash/reboot. MC runs with a usable
        work_dir are returned as resumable (left running, to be resumed in place); everything
        else is requeued for a fresh re-run. Returns resumables in enqueue order."""
        resumable = []
        for job in self._store.list(status=RUNNING):
            if job.mode == "montecarlo" and self._resumable(job):
                resumable.append(job)
            else:
                self._store.requeue(job.id)
        resumable.sort(key=lambda j: j.id)
        return resumable

    def _spawn(self, job_id: int, cmd, run_dir: Path, stop_flag: Optional[Path] = None):
        # start_new_session puts the runner and every solver it spawns in one process group,
        # so cancel can signal the whole tree. Signalling only the direct child left solver
        # processes orphaned and still burning cores after a cancel.
        proc = subprocess.Popen(cmd, cwd=str(run_dir), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=self._env,
                                start_new_session=True)
        with self._lock:
            prev = self._current
            # A cancel that landed between two phases of the same job (runner finished, post
            # not yet spawned) must not be lost when the phase's process is swapped in.
            carried = bool(prev and prev["job_id"] == job_id and prev["cancelled"])
            self._current = {"job_id": job_id, "proc": proc, "cancelled": carried,
                             "disk_abort": None}
        if carried:
            self._kill_tree(proc)
        finished = threading.Event()
        watch = threading.Thread(target=self._watch_disk,
                                 args=(job_id, proc, stop_flag, finished), daemon=True)
        watch.start()
        try:
            out, _ = proc.communicate()
        finally:
            finished.set()
        return proc.returncode, out or ""

    def _watch_disk(self, job_id: int, proc, stop_flag: Optional[Path],
                    finished: threading.Event) -> None:
        """Stop the run before the volume fills.

        Runs for the lifetime of one spawn. On the first reading below the floor it records
        the reason (so _execute can report it), then asks a Monte Carlo run to pause via its
        stop flag — in-flight cases finish and the work dir stays resumable. Anything still
        alive after the grace period, and every mode without a cooperative pause, is killed.
        """
        while not finished.wait(_DISK_POLL_SEC):
            free = self.disk_free_bytes()
            if free is None or free >= self._disk_floor:
                continue
            log.error("job %s: free space %s is below the %s floor; stopping the run",
                      job_id, _gb(free), _gb(self._disk_floor))
            with self._lock:
                cur = self._current
                if cur and cur["job_id"] == job_id and cur["disk_abort"] is None:
                    cur["disk_abort"] = free
            if stop_flag is not None:
                try:
                    stop_flag.touch()
                except OSError:
                    log.exception("job %s: could not write the stop flag", job_id)
                else:
                    if finished.wait(_DISK_STOP_GRACE_SEC):
                        return  # paused on its own; nothing to kill
                    log.error("job %s: did not stop within the grace period; killing", job_id)
            self._kill_tree(proc)
            return

    def _kill_tree(self, proc) -> None:
        """SIGTERM the run's whole process group, then SIGKILL whatever is left.

        The runner spawns the solver as its own child, so terminating just the direct child
        leaves solvers running as orphans. _spawn gives the run its own session, which makes
        the process group the unit to signal.
        """
        if os.name != "posix":  # pragma: no cover - the service is Linux-only
            proc.terminate()
            return
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            proc.terminate()
            return
        for sig, grace in ((signal.SIGTERM, _TERM_GRACE_SEC), (signal.SIGKILL, 0.0)):
            try:
                os.killpg(pgid, sig)
            except OSError:
                return  # already gone
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    return
                time.sleep(0.05)

    def run_post(self, run_dir, work_name: str, mode: str):
        """Post-process a work dir that already holds solver output. The normal path posts inside
        _execute; this is the entry point for service.imports, which registers a result computed
        elsewhere and still needs the plots/KML/summary the result API and 3D viewer read.
        Returns (returncode, output); (0, "") for a mode post.py does not handle."""
        flag = _POST_FLAG.get(mode)
        if flag is None:
            return 0, ""
        return self._run_plain([self._python, self._post_py, flag, work_name], Path(run_dir))

    def _run_plain(self, cmd, run_dir: Path):
        proc = subprocess.Popen(cmd, cwd=str(run_dir), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=self._env)
        out, _ = proc.communicate()
        return proc.returncode, out or ""

    # --- control ------------------------------------------------------------

    def cancel(self, job_id: int) -> bool:
        """Terminate the running job, or cancel it while still queued. Returns True if a
        cancel took effect."""
        proc = None
        owned = False
        with self._lock:
            cur = self._current
            if cur and cur["job_id"] == job_id:
                # Flag it even when this phase's process has already exited: the job may be
                # between the runner and post, and the flag is what stops the next phase from
                # starting and completing a job the user cancelled.
                owned = True
                cur["cancelled"] = True
                if cur["proc"].poll() is None:
                    proc = cur["proc"]
        if proc is not None:
            self._kill_tree(proc)
        if owned:
            return True
        if self._store.cancel_if_queued(job_id):
            return True
        # Not owned by the worker and not queued, yet the row can still say `running` — left
        # there by a crash, or by a worker that died before it could record a terminal state.
        # Such a job is stuck active forever: it cannot be deleted or re-run, and it reads as
        # a permanently stalled run. Cancel is the only way out, so let it release the row.
        return self._store.force_cancel_running(job_id)

    def is_running(self, job_id: int) -> bool:
        with self._lock:
            cur = self._current
            return bool(cur and cur["job_id"] == job_id and cur["proc"].poll() is None)

    # --- loop ---------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, join_timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(join_timeout)

    def _run(self) -> None:
        # On start, resume any MC job that was running when the process last died, then
        # process the normal queue (design §4.2).
        try:
            resumable = self.recover()
        except Exception:
            log.exception("startup recovery failed; continuing with the queue")
            resumable = []
        for job in resumable:
            if self._stop.is_set():
                return
            try:
                self.resume_one(job)
            except Exception as exc:
                self._fail_safely(job.id, f"worker error during resume: {exc!r}")
        self._loop()

    def _loop(self) -> None:
        # Nothing a single job does may end this loop. A worker thread that dies takes the
        # whole queue with it and says nothing: jobs stay `running` forever, cancel has no
        # process to signal, and only a service restart brings execution back. That is what a
        # full disk did — the ENOSPC surfaced as a SQLite write error inside mark_failed, and
        # the exception unwound straight out of the thread.
        while not self._stop.is_set():
            try:
                job = self._store.claim_next()
            except Exception:
                log.exception("could not claim the next job; retrying")
                self._stop.wait(_ERROR_BACKOFF_SEC)
                continue
            if job is None:
                self._stop.wait(self._poll)
                continue
            try:
                self.run_one(job)
            except Exception as exc:
                self._fail_safely(job.id, f"worker error: {exc!r}")

    def _fail_safely(self, job_id: int, message: str) -> None:
        """Record a job's failure without letting the recording itself kill the worker.

        The store can be the thing that is broken (a full disk fails the SQLite commit), so
        the write is retried once after a backoff and then given up on. A job left `running`
        is recoverable — cancel releases it, and a restart re-runs or resumes it — whereas a
        dead worker is not.
        """
        log.error("job %s: %s", job_id, message)
        for attempt in (0, 1):
            if attempt:
                self._stop.wait(_ERROR_BACKOFF_SEC)
            try:
                self._store.mark_failed(job_id, message)
                self._emit(job_id, FAILED, message)
                return
            except Exception:
                log.exception("job %s: could not record the failure (attempt %d)",
                              job_id, attempt + 1)
