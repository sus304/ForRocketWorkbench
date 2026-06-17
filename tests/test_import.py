"""Tests for importing CLI (runner.py) result directories into the history DB."""
import json

import pytest


@pytest.fixture
def import_env(monkeypatch, tmp_path):
    """Isolated SQLite DB + a temporary projects/ root for import_service."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from web.db.models import Base
    import web.services.import_service as svc

    engine = create_engine(f'sqlite:///{tmp_path / "test.db"}')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(svc, 'get_session', Session)

    projects = tmp_path / 'projects'
    projects.mkdir()
    monkeypatch.setattr(svc, 'projects_dir', lambda: projects)
    return svc, Session, tmp_path, projects


def _make_work_dir(parent, name, *, solver_cfg=None, files=None):
    d = parent / name
    d.mkdir(parents=True)
    if solver_cfg is not None:
        (d / 'config_solver.json').write_text(json.dumps(solver_cfg))
    for rel, content in (files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


# ---------------------------------------------------------------------------
# detect_mode
# ---------------------------------------------------------------------------

def test_detect_mode_by_dirname(import_env, tmp_path):
    svc = import_env[0]
    assert svc.detect_mode(str(tmp_path / 'work_trajectory')) == 'trajectory'
    assert svc.detect_mode(str(tmp_path / 'work_area_03')) == 'area'
    assert svc.detect_mode(str(tmp_path / 'work_montecarlo_01')) == 'montecarlo'
    assert svc.detect_mode(str(tmp_path / 'work_sensitivity')) == 'sensitivity'


def test_detect_mode_by_marker_file(import_env, tmp_path):
    svc = import_env[0]
    d = _make_work_dir(tmp_path, 'renamed_run', files={'sensitivity_results.csv': 'x\n'})
    assert svc.detect_mode(str(d)) == 'sensitivity'
    d2 = _make_work_dir(tmp_path, 'renamed_mc', files={'result_table.csv': 'x\n'})
    assert svc.detect_mode(str(d2)) == 'montecarlo'


def test_detect_mode_bare_flight_log_is_trajectory(import_env, tmp_path):
    svc = import_env[0]
    d = _make_work_dir(tmp_path, 'just_a_run', files={'EXAMPLE_stage1_flight_log.csv': 'a\n'})
    assert svc.detect_mode(str(d)) == 'trajectory'


def test_detect_mode_unknown(import_env, tmp_path):
    svc = import_env[0]
    d = _make_work_dir(tmp_path, 'mystery', files={'notes.txt': 'hi\n'})
    assert svc.detect_mode(str(d)) is None


# ---------------------------------------------------------------------------
# model id extraction
# ---------------------------------------------------------------------------

def test_extract_model_id_toplevel(import_env, tmp_path):
    svc = import_env[0]
    d = _make_work_dir(tmp_path, 'work_trajectory', solver_cfg={'Model ID': 'EXAMPLE'})
    assert svc._extract_model_id(str(d)) == 'EXAMPLE'


def test_extract_model_id_from_cases(import_env, tmp_path):
    svc = import_env[0]
    d = _make_work_dir(tmp_path, 'work_montecarlo',
                       files={'cases/0_solver_config.json': json.dumps({'Model ID': 'EXAMPLE'}),
                              'result_table.csv': 'x\n'})
    assert svc._extract_model_id(str(d)) == 'EXAMPLE'


def test_extract_model_id_missing_returns_empty(import_env, tmp_path):
    svc = import_env[0]
    d = _make_work_dir(tmp_path, 'work_trajectory', files={'flight.csv': 'x\n'})
    assert svc._extract_model_id(str(d)) == ''


# ---------------------------------------------------------------------------
# inspect_result
# ---------------------------------------------------------------------------

def test_inspect_nonexistent_dir(import_env):
    svc = import_env[0]
    info = svc.inspect_result('/no/such/directory')
    assert info['ok'] is False
    assert 'does not exist' in info['error']


def test_inspect_empty_input(import_env):
    svc = import_env[0]
    info = svc.inspect_result('   ')
    assert info['ok'] is False
    assert info['error']


def test_inspect_valid_montecarlo(import_env, tmp_path):
    svc = import_env[0]
    d = _make_work_dir(tmp_path, 'work_montecarlo',
                       files={'cases/0_solver_config.json': json.dumps({'Model ID': 'EXAMPLE'}),
                              'result_table.csv': 'x\n'})
    info = svc.inspect_result(str(d))
    assert info['ok'] is True
    assert info['mode'] == 'montecarlo'
    assert info['model_id'] == 'EXAMPLE'
    assert info['already_registered'] is False


def test_inspect_undetectable_mode_not_ok(import_env, tmp_path):
    svc = import_env[0]
    d = _make_work_dir(tmp_path, 'mystery', files={'notes.txt': 'x\n'})
    info = svc.inspect_result(str(d))
    assert info['ok'] is False
    assert 'mode' in info['error'].lower()


# ---------------------------------------------------------------------------
# register_result
# ---------------------------------------------------------------------------

def test_register_inserts_row(import_env, tmp_path):
    svc, Session = import_env[0], import_env[1]
    from web.db.models import Calculation

    d = _make_work_dir(tmp_path, 'work_trajectory', solver_cfg={'Model ID': 'EXAMPLE'},
                       files={'EXAMPLE_stage1_flight_log.csv': 'a\n'})
    calc_id, err = svc.register_result(str(d))
    assert err == ''
    assert calc_id is not None

    session = Session()
    calc = session.get(Calculation, calc_id)
    assert calc.mode == 'trajectory'
    assert calc.model_name == 'EXAMPLE'
    assert calc.status == 'completed'
    assert calc.result_dir == str(d.resolve())
    session.close()


def test_register_dedup_then_force(import_env, tmp_path):
    svc = import_env[0]
    d = _make_work_dir(tmp_path, 'work_sensitivity',
                       files={'sensitivity_results.csv': 'x\n'})

    first_id, err = svc.register_result(str(d))
    assert err == '' and first_id is not None

    dup_id, err = svc.register_result(str(d))
    assert dup_id is None
    assert 'Already registered' in err

    forced_id, err = svc.register_result(str(d), force=True)
    assert err == ''
    assert forced_id != first_id


def test_register_autolinks_project_under_projects_dir(import_env, tmp_path):
    svc, Session, _tmp, projects = import_env
    from web.db.models import Calculation, Project

    d = _make_work_dir(projects / 'EXAMPLE', 'work_trajectory',
                       solver_cfg={'Model ID': 'EXAMPLE'})
    calc_id, err = svc.register_result(str(d))
    assert err == ''

    session = Session()
    calc = session.get(Calculation, calc_id)
    assert calc.project_id is not None
    assert session.get(Project, calc.project_id).name == 'EXAMPLE'
    session.close()


def test_register_project_override_creates_project(import_env, tmp_path):
    svc, Session = import_env[0], import_env[1]
    from web.db.models import Calculation, Project

    d = _make_work_dir(tmp_path / 'external', 'work_area',
                       files={'EXAMPLE_stage1_flight_log.csv': 'a\n'})
    calc_id, err = svc.register_result(str(d), project_name='ManualProj')
    assert err == ''

    session = Session()
    calc = session.get(Calculation, calc_id)
    assert session.get(Project, calc.project_id).name == 'ManualProj'
    session.close()


def test_register_no_project_when_outside(import_env, tmp_path):
    svc, Session = import_env[0], import_env[1]
    from web.db.models import Calculation

    d = _make_work_dir(tmp_path / 'external', 'work_trajectory',
                       files={'EXAMPLE_stage1_flight_log.csv': 'a\n'})
    calc_id, err = svc.register_result(str(d))
    assert err == ''

    session = Session()
    assert session.get(Calculation, calc_id).project_id is None
    session.close()
