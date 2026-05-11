import datetime
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from web.db.database import get_session
from web.db.models import Calculation, Project
from web.services.project_service import projects_dir, get_model_id

_WORKBENCH_ROOT = Path(__file__).resolve().parent.parent.parent
_RUNNER = str(_WORKBENCH_ROOT / 'runner.py')
_POST = str(_WORKBENCH_ROOT / 'post.py')

_STEP_LABELS = ['', 'Preparing files...', 'Running solver...', 'Post processing...', 'Saving results...']


class _CalcCancelled(Exception):
    pass


@dataclass
class JobState:
    calc_id: int = 0
    step: int = 0
    status: str = 'idle'   # idle / running / cancelling / completed / failed / cancelled
    error: str = ''
    project_name: str = ''
    mode: str = ''
    result_dir: str = ''

    @property
    def step_label(self) -> str:
        return _STEP_LABELS[self.step] if 0 <= self.step < len(_STEP_LABELS) else ''

    @property
    def progress(self) -> float:
        return self.step / 4.0


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


def _build_runner_cmd(mode: str, use_max_thread: bool) -> list[str]:
    cmd = [sys.executable, _RUNNER, '-s', 'config_solver.json']
    if mode == 'area':
        cmd += ['-a', 'config_area.json']
    elif mode == 'montecarlo':
        cmd += ['-m', 'config_montecarlo.json']
    elif mode == 'sensitivity':
        cmd += ['-e', 'config_sensitivity.json']
    if use_max_thread and mode in ('area', 'montecarlo', 'sensitivity'):
        cmd += ['-X']
    return cmd


def _run_runner(mode: str, project_dir: Path, use_max_thread: bool) -> str:
    """Spawn runner.py subprocess; return relative work directory path."""
    proc = subprocess.Popen(
        _build_runner_cmd(mode, use_max_thread),
        cwd=str(project_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _set_proc(proc)
    stdout, _ = proc.communicate()
    _set_proc(None)

    with _lock:
        if _job.status == 'cancelling':
            raise _CalcCancelled()

    if proc.returncode != 0:
        raise RuntimeError(f'runner.py failed (exit {proc.returncode}):\n{stdout}')

    for line in stdout.splitlines():
        if line.startswith('Work Directory:'):
            return line.split(':', 1)[1].strip()
    return '.'


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

    with _lock:
        _job.calc_id = calc_id
        _job.step = 0
        _job.status = 'running'
        _job.error = ''
        _job.project_name = project_name
        _job.mode = mode
        _job.result_dir = ''

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
        if _job.status == 'running':
            _job.status = 'cancelling'
    with _proc_lock:
        if _current_proc is not None:
            _current_proc.terminate()


def _run_job(calc_id: int, project_name: str, mode: str, use_max_thread: bool):
    project_dir = (projects_dir() / project_name).resolve()
    result_dir = ''
    try:
        _set_step(1)
        _set_step(2)
        work_dir_rel = _run_runner(mode, project_dir, use_max_thread)

        _set_step(3)
        if mode != 'sensitivity':  # runner.py handles sensitivity post internally
            _run_post_proc(mode, work_dir_rel, project_dir)

        result_dir = str((project_dir / work_dir_rel).resolve())
        _set_step(4)
        _update_db_done(calc_id, 'completed', result_dir)
        with _lock:
            _job.result_dir = result_dir
        _set_status('completed')

    except _CalcCancelled:
        _update_db_done(calc_id, 'cancelled')
        with _lock:
            _job.status = 'cancelled'
            _job.step = 0

    except Exception as e:
        _update_db_done(calc_id, 'failed', error_message=str(e))
        _set_status('failed', str(e))
