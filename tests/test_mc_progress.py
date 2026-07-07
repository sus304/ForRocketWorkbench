"""Tests for the montecarlo live-progress helper in the web calc service.

The helper is read-only over artifacts the runner already produces (the completion
manifest written for pause/resume), so these tests fabricate a fake project dir with a
work_montecarlo directory and drive web.services.calc_service.montecarlo_progress().
"""
import json
import os
import sys
import time

import pytest

# calc_service uses module-level PEP 604 annotations (`X | None`) — importable on 3.10+.
pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 10),
    reason='web.services.calc_service requires Python 3.10+',
)


@pytest.fixture
def svc():
    import web.services.calc_service as calc_service
    return calc_service


@pytest.fixture
def mc_env(svc, monkeypatch, tmp_path):
    """Fake projects root with one project prepared for a montecarlo run.

    Returns (project_dir, set_job) where set_job(**fields) installs a fresh JobState.
    """
    projects = tmp_path / 'projects'
    project_dir = projects / 'proj'
    project_dir.mkdir(parents=True)
    (project_dir / 'config_montecarlo.json').write_text(
        json.dumps({'MonteCarlo Case Count': 10}))
    monkeypatch.setattr(svc, 'projects_dir', lambda: projects)

    def set_job(**fields):
        job = svc.JobState(project_name='proj', **fields)
        monkeypatch.setattr(svc, '_job', job)
        return job

    return project_dir, set_job


def _write_manifest(work_dir, n, torn_tail=False):
    text = ''.join(f'{i}_solver_config.json\n' for i in range(n))
    if torn_tail:
        text += '99_solver_c'  # append in flight: no trailing newline yet
    (work_dir / 'completed_cases.txt').write_text(text)


# ---------------------------------------------------------------------------
# low-level helpers
# ---------------------------------------------------------------------------

def test_count_completed_cases_counts_lines(svc, tmp_path):
    _write_manifest(tmp_path, 4)
    assert svc._count_completed_cases(str(tmp_path)) == 4


def test_count_completed_cases_ignores_torn_final_line(svc, tmp_path):
    _write_manifest(tmp_path, 4, torn_tail=True)
    assert svc._count_completed_cases(str(tmp_path)) == 4


def test_count_completed_cases_missing_file(svc, tmp_path):
    assert svc._count_completed_cases(str(tmp_path)) == 0


def test_read_mc_case_count(svc, tmp_path):
    (tmp_path / 'config_montecarlo.json').write_text(json.dumps({'MonteCarlo Case Count': 300}))
    assert svc._read_mc_case_count(tmp_path) == 300


def test_read_mc_case_count_missing_or_bad(svc, tmp_path):
    assert svc._read_mc_case_count(tmp_path) == 0
    (tmp_path / 'config_montecarlo.json').write_text('{}')
    assert svc._read_mc_case_count(tmp_path) == 0


def test_find_mc_work_dir_prefers_dir_touched_after_start(svc, tmp_path):
    started = time.time()
    old = tmp_path / 'work_montecarlo'
    old.mkdir()
    stale = started - 100
    os.utime(old, (stale, stale))
    assert svc._find_mc_work_dir(tmp_path, started) == ''

    new = tmp_path / 'work_montecarlo_01'
    new.mkdir()
    assert svc._find_mc_work_dir(tmp_path, started) == str(new)


# ---------------------------------------------------------------------------
# montecarlo_progress
# ---------------------------------------------------------------------------

def test_progress_none_when_not_montecarlo(svc, mc_env):
    _, set_job = mc_env
    set_job(mode='trajectory', status='running', step=2)
    assert svc.montecarlo_progress() is None


def test_progress_none_outside_solver_step(svc, mc_env):
    _, set_job = mc_env
    set_job(mode='montecarlo', status='running', step=3, mc_total=10,
            run_started_at=time.time() - 30)
    assert svc.montecarlo_progress() is None


def test_progress_none_before_work_dir_exists(svc, mc_env):
    _, set_job = mc_env
    set_job(mode='montecarlo', status='running', step=2, mc_total=10,
            run_started_at=time.time() - 30)
    assert svc.montecarlo_progress() is None


def test_progress_running_reports_done_and_eta(svc, mc_env):
    project_dir, set_job = mc_env
    set_job(mode='montecarlo', status='running', step=2, mc_total=10,
            run_started_at=time.time() - 30)
    work = project_dir / 'work_montecarlo'
    work.mkdir()
    _write_manifest(work, 4)

    p = svc.montecarlo_progress()
    assert p is not None
    assert (p.done, p.total) == (4, 10)
    assert p.session_elapsed > 0
    # 4 cases in ~30 s → ~7.5 s/case × 6 remaining ≈ 45 s
    assert 30 < p.eta < 60


def test_progress_zero_done_has_no_eta(svc, mc_env):
    project_dir, set_job = mc_env
    set_job(mode='montecarlo', status='running', step=2, mc_total=10,
            run_started_at=time.time() - 30)
    (project_dir / 'work_montecarlo').mkdir()  # cases still generating, no manifest yet

    p = svc.montecarlo_progress()
    assert p is not None
    assert p.done == 0
    assert p.eta < 0


def test_progress_resume_baseline_excluded_from_eta_rate(svc, mc_env):
    project_dir, set_job = mc_env
    work = project_dir / 'work_montecarlo'
    work.mkdir()
    _write_manifest(work, 6)
    # Resumed session: 4 cases predate this session, 2 ran in the last ~30 s.
    set_job(mode='montecarlo', status='running', step=2, mc_total=10,
            run_started_at=time.time() - 30, mc_work_dir=str(work), mc_baseline_done=4)

    p = svc.montecarlo_progress()
    assert p is not None
    assert (p.done, p.total) == (6, 10)
    # 2 session cases in ~30 s → ~15 s/case × 4 remaining ≈ 60 s
    assert 45 < p.eta < 75


def test_progress_paused_reports_counts_without_eta(svc, mc_env):
    project_dir, set_job = mc_env
    work = project_dir / 'work_montecarlo'
    work.mkdir()
    _write_manifest(work, 7)
    set_job(mode='montecarlo', status='paused', step=2, mc_total=10,
            run_started_at=time.time() - 30, mc_work_dir=str(work))

    p = svc.montecarlo_progress()
    assert p is not None
    assert (p.done, p.total) == (7, 10)
    assert p.eta < 0
