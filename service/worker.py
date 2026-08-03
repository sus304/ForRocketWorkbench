"""Single-FIFO worker: the compute service's executor.

It claims the oldest queued job, creates and persists the run's work_dir *before* launching
so a crash mid-run leaves a resume anchor, spawns runner.py as a subprocess it owns (the run
therefore outlives any UI), runs post, and records the terminal state. Jobs run strictly one
at a time: the MC solver is memory-bandwidth bound, so serial execution is the design choice
(docs/compute_server_design.md §4.2). cancel terminates the running subprocess.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
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


class Worker:
    def __init__(self, store: JobStore, data_root, python: str = sys.executable,
                 runner_py: Optional[str] = None, post_py: Optional[str] = None,
                 poll: float = 0.5, on_event=None):
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

        self._lock = threading.Lock()
        self._current = None  # {"job_id", "proc", "cancelled"} while a job runs
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def data_root(self) -> Path:
        return self._data_root

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
        self._execute(job, cmd, run_dir, work_name, job.work_dir)

    def _execute(self, job, cmd, run_dir: Path, work_name: str, abs_work_dir: str) -> None:
        self._record_solver_version(job.id, run_dir)
        rc, out = self._spawn(job.id, cmd, run_dir)

        with self._lock:
            cur = self._current
            cancelled = bool(cur and cur["job_id"] == job.id and cur["cancelled"])
            self._current = None

        if cancelled:
            self._store.mark_cancelled(job.id)  # user-initiated; no notification
            return
        if rc != 0:
            self._store.mark_failed(job.id, f"runner.py exit {rc}\n{out[-_OUTPUT_TAIL:]}")
            self._emit(job.id, FAILED)
            return

        post_flag = _POST_FLAG.get(job.mode)
        if post_flag is not None:
            prc, pout = self._run_plain([self._python, self._post_py, post_flag, work_name], run_dir)
            if prc != 0:
                self._store.mark_failed(job.id, f"post.py exit {prc}\n{pout[-_OUTPUT_TAIL:]}")
                self._emit(job.id, FAILED)
                return

        self._store.mark_completed(job.id, result_dir=abs_work_dir)
        self._emit(job.id, COMPLETED)

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

    def _spawn(self, job_id: int, cmd, run_dir: Path):
        proc = subprocess.Popen(cmd, cwd=str(run_dir), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=self._env)
        with self._lock:
            self._current = {"job_id": job_id, "proc": proc, "cancelled": False}
        out, _ = proc.communicate()
        return proc.returncode, out or ""

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
        with self._lock:
            cur = self._current
            if cur and cur["job_id"] == job_id and cur["proc"].poll() is None:
                cur["cancelled"] = True
                proc = cur["proc"]
        if proc is not None:
            proc.terminate()
            return True
        return self._store.cancel_if_queued(job_id)

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
        for job in self.recover():
            if self._stop.is_set():
                return
            self.resume_one(job)
        self._loop()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self._store.claim_next()
            if job is None:
                self._stop.wait(self._poll)
                continue
            self.run_one(job)
