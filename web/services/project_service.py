from __future__ import annotations

import json
from pathlib import Path

from web.db.database import get_session
from web.db.models import Project

_WORKBENCH_ROOT = Path(__file__).resolve().parent.parent.parent
_PROJECTS_DIR = _WORKBENCH_ROOT / 'projects'

_CONFIG_FILES = [
    'config_solver.json',
    'param_list_stage1.json',
    'param_rocket.json',
    'param_engine.json',
    'sequence_of_event.json',
    'config_area.json',
    'config_montecarlo.json',
    'config_sensitivity.json',
]


def projects_dir() -> Path:
    return _PROJECTS_DIR


def scan_projects() -> list[str]:
    """Scan projects/ directory and register any new projects in the DB."""
    if not _PROJECTS_DIR.exists():
        _PROJECTS_DIR.mkdir(parents=True)
        return []

    session = get_session()
    try:
        names = []
        for d in sorted(_PROJECTS_DIR.iterdir()):
            if d.is_dir() and (d / 'config_solver.json').exists():
                names.append(d.name)
                if not session.query(Project).filter_by(name=d.name).first():
                    session.add(Project(name=d.name, directory=str(d)))
        session.commit()
        return names
    finally:
        session.close()


def get_project_files(project_name: str) -> dict[str, bool]:
    """Return {filename: exists} for all expected config files."""
    d = _PROJECTS_DIR / project_name
    return {f: (d / f).exists() for f in _CONFIG_FILES}


def get_model_id(project_name: str) -> str:
    path = _PROJECTS_DIR / project_name / 'config_solver.json'
    if not path.exists():
        return ''
    with open(path) as f:
        return json.load(f).get('Model ID', '')


def load_json(project_name: str, filename: str) -> dict | list | None:
    path = _PROJECTS_DIR / project_name / filename
    if not path.exists():
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_json(project_name: str, filename: str, data: dict | list):
    path = _PROJECTS_DIR / project_name / filename
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def create_project(name: str) -> tuple[bool, str]:
    """Create a new project directory. Returns (success, error_message)."""
    d = _PROJECTS_DIR / name
    if d.exists():
        return False, f'Project "{name}" already exists.'
    d.mkdir(parents=True)
    return True, ''
