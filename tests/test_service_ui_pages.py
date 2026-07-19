"""Tests for the pure helpers behind the service-native GUI pages (Phase 9).

The NiceGUI page bodies are covered by manual/e2e verification; here we lock the pure display
logic — duration/ETA formatting and progress shaping — that drives the live job view.
"""
import datetime

from web.service_ui import pages


def test_filter_jobs_by_mode_and_query():
    jobs = [
        {"id": 1, "mode": "montecarlo", "model_name": "ROCKET-A", "project": "p1", "memo": "5%"},
        {"id": 2, "mode": "trajectory", "model_name": "ROCKET-B", "project": "p2", "memo": ""},
        {"id": 3, "mode": "montecarlo", "model_name": "ROCKET-A", "project": "p3", "memo": "resonance"},
    ]
    assert [j["id"] for j in pages.filter_jobs(jobs, mode="montecarlo")] == [1, 3]
    assert [j["id"] for j in pages.filter_jobs(jobs, query="resonance")] == [3]
    assert [j["id"] for j in pages.filter_jobs(jobs, query="p2")] == [2]
    assert [j["id"] for j in pages.filter_jobs(jobs, query="", mode="all")] == [1, 2, 3]


def test_fmt_hms():
    assert pages.fmt_hms(0) == '0:00'
    assert pages.fmt_hms(75) == '1:15'
    assert pages.fmt_hms(3661) == '1:01:01'
    assert pages.fmt_hms(-1) == '—'
    assert pages.fmt_hms(None) == '—'


def test_parse_iso_roundtrip():
    now = datetime.datetime(2026, 7, 18, 12, 0, 0)
    assert pages.parse_iso(now.isoformat()) == now
    assert pages.parse_iso(None) is None
    assert pages.parse_iso('not-a-date') is None


def test_elapsed_seconds():
    start = datetime.datetime(2026, 7, 18, 12, 0, 0)
    now = datetime.datetime(2026, 7, 18, 12, 1, 30)
    assert pages.elapsed_seconds(start.isoformat(), now=now) == 90.0
    assert pages.elapsed_seconds(None) is None


def test_eta_seconds():
    # 3 of 12 done in 30s → 90s remaining at the same rate
    assert pages.eta_seconds(3, 12, 30.0) == 90.0
    assert pages.eta_seconds(0, 12, 30.0) is None      # nothing done yet
    assert pages.eta_seconds(12, 12, 30.0) is None     # complete
    assert pages.eta_seconds(3, 12, 0.0) is None       # no elapsed time


def test_progress_fraction():
    assert pages.progress_fraction({'done': 3, 'total': 12}) == 0.25
    assert pages.progress_fraction({'done': 0, 'total': 0}) is None
    assert pages.progress_fraction(None) is None
    assert pages.progress_fraction({'done': 20, 'total': 10}) == 1.0  # clamped
