"""Register results produced outside the WebUI (e.g. runner.py run from a
terminal) into the calculation history DB.

The result page renders purely from ``result_dir`` contents + ``mode``, so a
CLI run becomes visible in the WebUI as soon as a matching ``Calculation`` row
points at its work directory — no re-computation needed.
"""
from __future__ import annotations

import datetime
import glob
import json
import os
from pathlib import Path

from web.db.database import get_session
from web.db.models import Calculation, Project
from web.services.project_service import projects_dir

# Work-directory name prefix → mode (see path_define.py)
_DIR_PREFIX_MODE = {
    'work_trajectory': 'trajectory',
    'work_area': 'area',
    'work_montecarlo': 'montecarlo',
    'work_sensitivity': 'sensitivity',
}

# Fallback: marker files that uniquely identify a mode when the directory was
# renamed and no longer carries a ``work_<mode>`` prefix.
_MARKER_MODE = [
    ('sensitivity', ['sensitivity_results.csv']),
    ('montecarlo', ['result_table.csv', 'decent_result_table.csv', 'ballistic_result_table.csv']),
]


def detect_mode(result_dir: str) -> str | None:
    """Infer the calculation mode from the work directory name, falling back to
    marker files. Returns None if undetectable."""
    name = os.path.basename(os.path.normpath(result_dir))
    for prefix, mode in _DIR_PREFIX_MODE.items():
        if name == prefix or name.startswith(prefix + '_'):
            return mode

    for mode, markers in _MARKER_MODE:
        if any(os.path.isfile(os.path.join(result_dir, m)) for m in markers):
            return mode

    # A bare flight log with no MC/sensitivity markers is a single trajectory run.
    if glob.glob(os.path.join(result_dir, '*_flight_log.csv')):
        return 'trajectory'
    return None


def _find_solver_config(result_dir: str) -> str | None:
    """Locate a solver config json inside the work directory.

    Trajectory/area copy ``config_solver.json`` to the work-dir top level;
    montecarlo/sensitivity only keep per-case copies under ``cases/``.
    """
    top = os.path.join(result_dir, 'config_solver.json')
    if os.path.isfile(top):
        return top
    for pat in ('cases/*_solver_config.json', '*_solver_config.json'):
        hits = sorted(glob.glob(os.path.join(result_dir, pat)))
        if hits:
            return hits[0]
    return None


def _extract_model_id(result_dir: str) -> str:
    path = _find_solver_config(result_dir)
    if not path:
        return ''
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f).get('Model ID', '') or ''
    except Exception:
        return ''


def _project_name_for_dir(result_dir: str) -> str | None:
    """If result_dir lives under projects/<name>/, return <name>, else None."""
    try:
        rel = Path(result_dir).resolve().relative_to(projects_dir().resolve())
    except ValueError:
        return None
    parts = rel.parts
    return parts[0] if parts else None


def _find_existing(session, abs_dir: str) -> 'Calculation | None':
    return session.query(Calculation).filter_by(result_dir=abs_dir).first()


def inspect_result(result_dir: str) -> dict:
    """Examine a work directory without modifying the DB.

    Returns a dict the import dialog can render before the user confirms:
    ``ok``, ``error``, ``abs_dir``, ``mode``, ``model_id``,
    ``suggested_project``, ``already_registered``, ``existing_id``.
    """
    info = {
        'ok': False, 'error': '', 'abs_dir': '', 'mode': None,
        'model_id': '', 'suggested_project': None,
        'already_registered': False, 'existing_id': None,
    }
    if not result_dir or not result_dir.strip():
        info['error'] = 'No directory given.'
        return info

    abs_dir = str(Path(result_dir).expanduser().resolve())
    info['abs_dir'] = abs_dir
    if not os.path.isdir(abs_dir):
        info['error'] = 'Directory does not exist.'
        return info

    mode = detect_mode(abs_dir)
    info['mode'] = mode
    info['model_id'] = _extract_model_id(abs_dir)
    info['suggested_project'] = _project_name_for_dir(abs_dir)

    session = get_session()
    try:
        existing = _find_existing(session, abs_dir)
        if existing:
            info['already_registered'] = True
            info['existing_id'] = existing.id
    finally:
        session.close()

    if mode is None:
        info['error'] = ('Could not detect calculation mode. Expected a '
                         'work_trajectory / work_area / work_montecarlo / '
                         'work_sensitivity directory.')
        return info

    info['ok'] = True
    return info


def _get_or_create_project(session, project_name: str) -> int:
    proj = session.query(Project).filter_by(name=project_name).first()
    if proj:
        return proj.id
    directory = projects_dir() / project_name
    proj = Project(name=project_name, directory=str(directory))
    session.add(proj)
    session.flush()
    return proj.id


def register_result(result_dir: str, project_name: str | None = None,
                    force: bool = False) -> tuple[int | None, str]:
    """Insert a completed ``Calculation`` row pointing at ``result_dir``.

    ``project_name`` overrides auto-detection; pass None to auto-link by path
    (projects/<name>/...) or leave the calc project-less. Set ``force=True`` to
    register again even if the directory is already in the DB.

    Returns ``(calc_id, '')`` on success or ``(None, error_message)``.
    """
    info = inspect_result(result_dir)
    if not info['ok']:
        return None, info['error']

    abs_dir = info['abs_dir']
    if info['already_registered'] and not force:
        return None, f"Already registered as calc #{info['existing_id']}."

    link_name = project_name or info['suggested_project']
    started = datetime.datetime.now()
    try:
        started = datetime.datetime.fromtimestamp(os.path.getmtime(abs_dir))
    except OSError:
        pass

    session = get_session()
    try:
        project_id = _get_or_create_project(session, link_name) if link_name else None
        calc = Calculation(
            project_id=project_id,
            mode=info['mode'],
            model_name=info['model_id'],
            status='completed',
            started_at=started,
            finished_at=started,
            result_dir=abs_dir,
            memo='Imported from CLI',
        )
        session.add(calc)
        session.commit()
        return calc.id, ''
    finally:
        session.close()
