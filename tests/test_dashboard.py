"""Tests for dashboard filter + deletion helpers."""
import datetime

import pytest

from web.services.history_service import delete_calculations, filter_rows


@pytest.fixture
def sample_rows():
    return [
        {'id': 1, 'mode': 'trajectory',  'model': 'ROCKET-A', 'project': 'P1', 'status': 'completed', 'memo': 'first run'},
        {'id': 2, 'mode': 'montecarlo',  'model': 'ROCKET-B', 'project': 'P1', 'status': 'failed',    'memo': 'thrust issue'},
        {'id': 3, 'mode': 'area',        'model': 'ROCKET-A', 'project': 'P2', 'status': 'completed', 'memo': ''},
        {'id': 4, 'mode': 'sensitivity', 'model': 'NEW',      'project': 'P2', 'status': 'running',   'memo': 'overnight'},
    ]


# ---------------------------------------------------------------------------
# filter_rows
# ---------------------------------------------------------------------------

def test_filter_all_returns_everything(sample_rows):
    assert filter_rows(sample_rows) == sample_rows


def test_filter_by_mode(sample_rows):
    out = filter_rows(sample_rows, mode='montecarlo')
    assert [r['id'] for r in out] == [2]


def test_filter_by_project(sample_rows):
    out = filter_rows(sample_rows, project='P2')
    assert sorted(r['id'] for r in out) == [3, 4]


def test_filter_search_matches_memo(sample_rows):
    out = filter_rows(sample_rows, search='thrust')
    assert [r['id'] for r in out] == [2]


def test_filter_search_is_case_insensitive(sample_rows):
    out = filter_rows(sample_rows, search='rocket-a')
    assert sorted(r['id'] for r in out) == [1, 3]


def test_filter_search_matches_status(sample_rows):
    out = filter_rows(sample_rows, search='running')
    assert [r['id'] for r in out] == [4]


def test_filter_combined(sample_rows):
    out = filter_rows(sample_rows, mode='trajectory', project='P1', search='first')
    assert [r['id'] for r in out] == [1]


def test_filter_combined_no_match(sample_rows):
    out = filter_rows(sample_rows, mode='area', project='P1')
    assert out == []


# ---------------------------------------------------------------------------
# delete_calculations  (isolated SQLite DB)
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    """Swap the history service's session factory for an isolated SQLite DB."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from web.db.models import Base

    engine = create_engine(f'sqlite:///{tmp_path / "test.db"}')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    import web.services.history_service as svc
    monkeypatch.setattr(svc, 'get_session', Session)
    return Session


def _make_calc(session, result_dir, mode='trajectory'):
    from web.db.models import Calculation
    c = Calculation(
        mode=mode,
        model_name='ROCKET-A',
        status='completed',
        started_at=datetime.datetime.now(),
        result_dir=result_dir,
    )
    session.add(c)
    session.commit()
    return c.id


def test_delete_removes_db_row_and_result_dir(isolated_db, tmp_path):
    from web.db.models import Calculation

    rdir = tmp_path / 'work_trajectory_01'
    rdir.mkdir()
    (rdir / 'flight_log.csv').write_text('a,b,c\n1,2,3\n')

    session = isolated_db()
    cid = _make_calc(session, str(rdir))
    session.close()

    deleted, errors = delete_calculations([cid])
    assert deleted == 1
    assert errors == []
    assert not rdir.exists()

    session = isolated_db()
    assert session.query(Calculation).filter_by(id=cid).first() is None
    session.close()


def test_delete_missing_result_dir_is_silent(isolated_db, tmp_path):
    """Empty / non-existent result_dir → DB row still deleted, no errors."""
    from web.db.models import Calculation

    session = isolated_db()
    cid_empty   = _make_calc(session, '')
    cid_missing = _make_calc(session, str(tmp_path / 'does_not_exist'))
    session.close()

    deleted, errors = delete_calculations([cid_empty, cid_missing])
    assert deleted == 2
    assert errors == []

    session = isolated_db()
    assert session.query(Calculation).count() == 0
    session.close()


def test_delete_unknown_id_is_skipped(isolated_db):
    deleted, errors = delete_calculations([9999])
    assert deleted == 0
    assert errors == []


def test_delete_multiple_keeps_others(isolated_db):
    from web.db.models import Calculation

    session = isolated_db()
    keep_id   = _make_calc(session, '', mode='area')
    drop_id_1 = _make_calc(session, '', mode='trajectory')
    drop_id_2 = _make_calc(session, '', mode='montecarlo')
    session.close()

    deleted, errors = delete_calculations([drop_id_1, drop_id_2])
    assert deleted == 2
    assert errors == []

    session = isolated_db()
    remaining = [c.id for c in session.query(Calculation).all()]
    assert remaining == [keep_id]
    session.close()
