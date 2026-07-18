from __future__ import annotations

import datetime
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from path_define import runner_montecarlo_directory
from runner_tool.run_manifest import RunManifest

from web.db.database import get_session
from web.db.models import Calculation, Project
from web.services.project_service import projects_dir, get_model_id

_WORKBENCH_ROOT = Path(__file__).resolve().parent.parent.parent
_RUNNER = str(_WORKBENCH_ROOT / 'runner.py')
_POST = str(_WORKBENCH_ROOT / 'post.py')

_STEP_LABELS = ['', 'Preparing files...', 'Running solver...', 'Post processing...', 'Saving results...']


class _CalcCancelled(Exception):
    pass


class _CalcPaused(Exception):
    """Raised when a montecarlo run stopped gracefully on a pause request. Carries the
    (resumable) work directory relative to the project dir."""
    def __init__(self, work_dir: str):
        super().__init__('calculation paused')
        self.work_dir = work_dir


@dataclass
class JobState:
    calc_id: int = 0
    step: int = 0
    # idle / running / cancelling / completed / failed / cancelled / pausing / paused
    status: str = 'idle'
    error: str = ''
    project_name: str = ''
    mode: str = ''
    result_dir: str = ''
    work_dir: str = ''            # resumable work dir (relative to project) when paused
    use_max_thread: bool = False  # remembered so resume re-runs with the same threading
    run_started_at: float = 0.0   # time.time() when this session's runner was launched
    mc_total: int = 0             # montecarlo: total case count (0 = unknown)
    mc_work_dir: str = ''         # montecarlo: absolute work dir when known (pause/resume)
    mc_baseline_done: int = 0     # montecarlo: cases already complete when this session started

    @property
    def step_label(self) -> str:
        return _STEP_LABELS[self.step] if 0 <= self.step < len(_STEP_LABELS) else ''

    @property
    def progress(self) -> float:
        return self.step / 4.0


@dataclass
class McProgress:
    """Live per-case progress of a montecarlo job (see montecarlo_progress)."""
    done: int
    total: int
    session_elapsed: float  # seconds since this session's runner started
    eta: float              # estimated seconds remaining; negative when unknown


_job = JobState()
_lock = threading.Lock()
_current_thread: threading.Thread | None = None
_current_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()


def current_job() -> JobState:
    return _job


def join_current_job(timeout: float = 10.0):
    """Block until the background calc thread finishes. Intended for tests."""
    if _current_thread is not None and _current_thread.is_alive():
        _current_thread.join(timeout)


def _set_step(step: int):
    with _lock:
        _job.step = step


def _set_status(status: str, error: str = ''):
    with _lock:
        _job.status = status
        _job.error = error


def _set_proc(proc: 'subprocess.Popen | None'):
    global _current_proc
    with _proc_lock:
        _current_proc = proc


def _update_db_done(calc_id: int, status: str, result_dir: str = '', error_message: str = ''):
    session = get_session()
    try:
        calc = session.get(Calculation, calc_id)
        if calc:
            calc.status = status
            calc.finished_at = datetime.datetime.now()
            calc.result_dir = result_dir
            calc.error_message = error_message
            session.commit()
    finally:
        session.close()


def _update_db_status(calc_id: int, status: str, result_dir: 'str | None' = None):
    """Update status (and optionally result_dir) WITHOUT stamping finished_at — for
    transient states like 'paused' / 'running' that are not terminal."""
    session = get_session()
    try:
        calc = session.get(Calculation, calc_id)
        if calc:
            calc.status = status
            if result_dir is not None:
                calc.result_dir = result_dir
            session.commit()
    finally:
        session.close()


def _read_mc_case_count(project_dir: Path) -> int:
    try:
        with open(project_dir / 'config_montecarlo.json') as f:
            return int(json.load(f).get('MonteCarlo Case Count') or 0)
    except (OSError, TypeError, ValueError):
        return 0


def _count_completed_cases(work_dir: str) -> int:
    """Completed-case count from the runner's manifest. Counting newline bytes ignores a
    torn final line from a concurrent append."""
    try:
        with open(Path(work_dir) / RunManifest.FILENAME, 'rb') as f:
            return f.read().count(b'\n')
    except OSError:
        return 0


def _find_mc_work_dir(project_dir: Path, started_at: float) -> str:
    """Locate the running montecarlo work dir: only one job runs at a time, so it is the
    newest work_montecarlo* directory touched since this session's runner started (older
    runs' dirs are no longer written to). Returns '' while the runner has not created it
    yet. Rescanned every poll — cheap, and self-correcting against a transient mismatch."""
    best, best_mtime = '', started_at - 1.0  # slack for coarse filesystem timestamps
    for d in project_dir.glob(runner_montecarlo_directory + '*'):
        try:
            mtime = d.stat().st_mtime
        except OSError:
            continue
        if d.is_dir() and mtime > best_mtime:
            best, best_mtime = str(d), mtime
    return best


def montecarlo_progress() -> 'McProgress | None':
    """Live per-case progress of the current montecarlo job, read from the completion
    manifest (completed_cases.txt) the runner already maintains for pause/resume — the
    solver pipeline itself is untouched. Returns None when no montecarlo job is in its
    solver step or the work dir / case count are not known yet."""
    with _lock:
        if _job.mode != 'montecarlo' or _job.status not in ('running', 'pausing', 'paused'):
            return None
        if _job.step != 2:  # per-case progress only exists while the solver step runs
            return None
        status = _job.status
        total = _job.mc_total
        work_dir = _job.mc_work_dir
        baseline = _job.mc_baseline_done
        started_at = _job.run_started_at
        project_name = _job.project_name

    if total <= 0:
        return None
    if not work_dir:
        work_dir = _find_mc_work_dir((projects_dir() / project_name).resolve(), started_at)
        if not work_dir:
            return None

    done = _count_completed_cases(work_dir)
    elapsed = time.time() - started_at
    eta = -1.0
    session_done = done - baseline
    if status == 'running' and session_done > 0 and elapsed > 0 and done < total:
        eta = (total - done) * (elapsed / session_done)
    return McProgress(done=done, total=total, session_elapsed=elapsed, eta=eta)


def _stop_flag_path(project_dir: Path) -> Path:
    """Sentinel file the runner watches to pause gracefully (see runner._watch_stop_flag)."""
    return project_dir / '.calc_stop.flag'


def _clear_stop_flag(project_dir: Path):
    flag = _stop_flag_path(project_dir)
    try:
        if flag.exists():
            flag.unlink()
    except OSError:
        pass


def _build_runner_cmd(mode: str, use_max_thread: bool,
                      resume_work_dir: 'str | None' = None,
                      stop_flag: 'Path | None' = None) -> list[str]:
    cmd = [sys.executable, _RUNNER, '-s', 'config_solver.json']
    if mode == 'area':
        cmd += ['-a', 'config_area.json']
    elif mode == 'montecarlo':
        cmd += ['-m', 'config_montecarlo.json']
        if stop_flag is not None:
            cmd += ['--stop-flag-file', str(stop_flag)]
        if resume_work_dir:
            cmd += ['-r', resume_work_dir]
    elif mode == 'sensitivity':
        cmd += ['-e', 'config_sensitivity.json']
    if use_max_thread and mode in ('area', 'montecarlo', 'sensitivity'):
        cmd += ['-X']
    return cmd


def _run_runner(mode: str, project_dir: Path, use_max_thread: bool,
                resume_work_dir: 'str | None' = None) -> str:
    """Spawn runner.py subprocess; return relative work directory path.

    For montecarlo, a stop-flag file enables a graceful pause: when requested the runner
    finishes in-flight cases and exits 0 with a resumable work dir, which we surface via
    _CalcPaused so the job is marked 'paused' (not 'completed').
    """
    stop_flag = _stop_flag_path(project_dir) if mode == 'montecarlo' else None
    if stop_flag is not None:
        _clear_stop_flag(project_dir)  # never start a run already flagged to stop

    proc = subprocess.Popen(
        _build_runner_cmd(mode, use_max_thread, resume_work_dir, stop_flag),
        cwd=str(project_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _set_proc(proc)
    stdout, _ = proc.communicate()
    _set_proc(None)

    work_dir_rel = '.'
    for line in stdout.splitlines():
        if line.startswith('Work Directory:'):
            work_dir_rel = line.split(':', 1)[1].strip()

    with _lock:
        pausing = _job.status == 'pausing'
        cancelling = _job.status == 'cancelling'

    if pausing:
        _clear_stop_flag(project_dir)
        raise _CalcPaused(work_dir_rel)
    if cancelling:
        raise _CalcCancelled()
    if proc.returncode != 0:
        raise RuntimeError(f'runner.py failed (exit {proc.returncode}):\n{stdout}')

    return work_dir_rel


def _run_post_proc(mode: str, work_dir: str, project_dir: Path):
    """Spawn post.py subprocess for trajectory/area/montecarlo modes."""
    flag = {
        'trajectory': '-c',
        'area': '-a',
        'montecarlo': '-m',
    }[mode]
    proc = subprocess.Popen(
        [sys.executable, _POST, flag, work_dir],
        cwd=str(project_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _set_proc(proc)
    stdout, _ = proc.communicate()
    _set_proc(None)

    if proc.returncode != 0:
        raise RuntimeError(f'post.py failed (exit {proc.returncode}):\n{stdout}')


def start_calculation(project_name: str, mode: str, use_max_thread: bool) -> int:
    """Register a new Calculation in the DB, start background thread, return calc_id."""
    session = get_session()
    try:
        proj = session.query(Project).filter_by(name=project_name).first()
        calc = Calculation(
            project_id=proj.id if proj else None,
            mode=mode,
            model_name=get_model_id(project_name),
            status='running',
            started_at=datetime.datetime.now(),
            use_max_thread=use_max_thread,
        )
        session.add(calc)
        session.commit()
        calc_id = calc.id
    finally:
        session.close()

    project_dir = (projects_dir() / project_name).resolve()
    mc_total = _read_mc_case_count(project_dir) if mode == 'montecarlo' else 0

    with _lock:
        _job.calc_id = calc_id
        _job.step = 0
        _job.status = 'running'
        _job.error = ''
        _job.project_name = project_name
        _job.mode = mode
        _job.result_dir = ''
        _job.work_dir = ''
        _job.use_max_thread = use_max_thread
        _job.run_started_at = time.time()
        _job.mc_total = mc_total
        _job.mc_work_dir = ''  # discovered by montecarlo_progress once the runner creates it
        _job.mc_baseline_done = 0

    global _current_thread
    t = threading.Thread(
        target=_run_job,
        args=(calc_id, project_name, mode, use_max_thread),
        daemon=True,
    )
    t.start()
    _current_thread = t
    return calc_id


def cancel_calculation():
    with _lock:
        if _job.status in ('running', 'pausing'):
            _job.status = 'cancelling'
    with _proc_lock:
        if _current_proc is not None:
            _current_proc.terminate()


def pause_calculation():
    """Request a graceful pause of the running montecarlo job: in-flight cases finish,
    then the runner stops with a resumable work dir. Cross-platform (flag-file based)."""
    with _lock:
        if _job.status != 'running' or _job.mode != 'montecarlo':
            return
        _job.status = 'pausing'
        project_name = _job.project_name
    project_dir = (projects_dir() / project_name).resolve()
    _stop_flag_path(project_dir).write_text('stop')


def resume_calculation():
    """Resume a paused montecarlo job from its work dir, running only the cases that did
    not complete before the pause."""
    with _lock:
        if _job.status != 'paused':
            return
        calc_id = _job.calc_id
        project_name = _job.project_name
        mode = _job.mode
        use_max_thread = _job.use_max_thread
        work_dir = _job.work_dir
        _job.status = 'running'
        _job.step = 2
        _job.error = ''
        _job.run_started_at = time.time()

    # Baseline the manifest so the ETA rate counts only cases run in THIS session.
    mc_work_dir = str(((projects_dir() / project_name) / work_dir).resolve())
    baseline = _count_completed_cases(mc_work_dir)
    with _lock:
        _job.mc_work_dir = mc_work_dir
        _job.mc_baseline_done = baseline

    _update_db_status(calc_id, 'running')

    global _current_thread
    t = threading.Thread(
        target=_run_job,
        args=(calc_id, project_name, mode, use_max_thread),
        kwargs={'resume_work_dir': work_dir},
        daemon=True,
    )
    t.start()
    _current_thread = t


def _run_job(calc_id: int, project_name: str, mode: str, use_max_thread: bool,
             resume_work_dir: 'str | None' = None):
    project_dir = (projects_dir() / project_name).resolve()
    result_dir = ''
    try:
        if not resume_work_dir:
            _set_step(1)
        _set_step(2)
        work_dir_rel = _run_runner(mode, project_dir, use_max_thread, resume_work_dir)

        _set_step(3)
        if mode != 'sensitivity':  # runner.py handles sensitivity post internally
            _run_post_proc(mode, work_dir_rel, project_dir)

        result_dir = str((project_dir / work_dir_rel).resolve())
        _set_step(4)
        _update_db_done(calc_id, 'completed', result_dir)
        with _lock:
            _job.result_dir = result_dir
        _set_status('completed')

    except _CalcPaused as e:
        result_dir = str((project_dir / e.work_dir).resolve())
        _update_db_status(calc_id, 'paused', result_dir)
        with _lock:
            _job.work_dir = e.work_dir
            _job.result_dir = result_dir
            _job.status = 'paused'
            _job.mc_work_dir = result_dir

    except _CalcCancelled:
        _update_db_done(calc_id, 'cancelled')
        with _lock:
            _job.status = 'cancelled'
            _job.step = 0

    except Exception as e:
        _update_db_done(calc_id, 'failed', error_message=str(e))
        _set_status('failed', str(e))
