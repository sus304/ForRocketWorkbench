"""Job store (service.store) tests.

The job store is the authoritative record of the compute-service queue. It replaces the
GUI-owned in-memory JobState singleton: state lives in SQLite so the worker can recover
after a crash/reboot (see docs/compute_server_design.md §4.2). These tests exercise the
store data layer only -- no worker, no runner, no ForRocket binary -- so they run anywhere.
"""
import datetime

import pytest

from service.store import (
    JobStore,
    PREPARING, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED,
)


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


def test_enqueue_creates_queued_job(store):
    jid = store.enqueue(mode="montecarlo", model_name="ROCKET-A")
    job = store.get(jid)
    assert job is not None
    assert job.id == jid
    assert job.mode == "montecarlo"
    assert job.model_name == "ROCKET-A"
    assert job.status == QUEUED
    assert job.enqueued_at is not None
    assert job.started_at is None
    assert job.finished_at is None
    assert job.work_dir == ""
    assert job.result_dir == ""


def test_get_missing_returns_none(store):
    assert store.get(999) is None


def test_list_filters_by_status_and_orders_newest_first(store):
    a = store.enqueue(mode="trajectory")
    b = store.enqueue(mode="area")
    c = store.enqueue(mode="montecarlo")
    ids = [j.id for j in store.list()]
    # list() returns newest-first for display
    assert ids == [c, b, a]
    assert [j.id for j in store.list(status=QUEUED)] == [c, b, a]
    assert store.list(status=RUNNING) == []


def test_claim_next_picks_oldest_queued_and_marks_running(store):
    a = store.enqueue(mode="trajectory")
    b = store.enqueue(mode="area")
    claimed = store.claim_next()
    assert claimed is not None
    assert claimed.id == a  # FIFO: oldest enqueued first
    assert claimed.status == RUNNING
    assert claimed.started_at is not None
    # b is still queued
    assert store.get(b).status == QUEUED


def test_claim_next_skips_running_returns_next_queued(store):
    a = store.enqueue(mode="trajectory")
    b = store.enqueue(mode="area")
    first = store.claim_next()
    assert first.id == a
    second = store.claim_next()
    assert second is not None
    assert second.id == b  # does not re-claim the already-running a
    assert store.claim_next() is None  # nothing left


def test_claim_next_on_empty_returns_none(store):
    assert store.claim_next() is None


def test_set_work_dir_persists(store):
    jid = store.enqueue(mode="montecarlo")
    store.claim_next()
    store.set_work_dir(jid, "/abs/projects/example/work_montecarlo")
    assert store.get(jid).work_dir == "/abs/projects/example/work_montecarlo"


def test_mark_completed(store):
    jid = store.enqueue(mode="trajectory")
    store.claim_next()
    store.mark_completed(jid, result_dir="/abs/work_trajectory", summary="ok")
    job = store.get(jid)
    assert job.status == COMPLETED
    assert job.result_dir == "/abs/work_trajectory"
    assert job.summary == "ok"
    assert job.finished_at is not None


def test_mark_failed_records_error(store):
    jid = store.enqueue(mode="area")
    store.claim_next()
    store.mark_failed(jid, "runner.py failed (exit 1)")
    job = store.get(jid)
    assert job.status == FAILED
    assert "exit 1" in job.error_message
    assert job.finished_at is not None


def test_mark_cancelled(store):
    jid = store.enqueue(mode="montecarlo")
    store.claim_next()
    store.mark_cancelled(jid)
    job = store.get(jid)
    assert job.status == CANCELLED
    assert job.finished_at is not None


def test_cancel_if_queued_flips_queued_job(store):
    jid = store.enqueue(mode="montecarlo")
    assert store.cancel_if_queued(jid) is True
    assert store.get(jid).status == CANCELLED
    # never got claimed
    assert store.get(jid).started_at is None


def test_cancel_if_queued_leaves_running_job_untouched(store):
    jid = store.enqueue(mode="montecarlo")
    store.claim_next()
    assert store.cancel_if_queued(jid) is False
    assert store.get(jid).status == RUNNING


def test_requeue_running_job_for_recovery(store):
    """Short modes left running after a crash are re-run from scratch: requeue -> queued."""
    jid = store.enqueue(mode="trajectory")
    store.claim_next()
    store.set_work_dir(jid, "/abs/work_trajectory")
    store.requeue(jid)
    job = store.get(jid)
    assert job.status == QUEUED
    assert job.started_at is None
    # re-claimable
    assert store.claim_next().id == jid


def test_list_running_for_recovery(store):
    a = store.enqueue(mode="montecarlo")
    b = store.enqueue(mode="trajectory")
    store.claim_next()  # a -> running
    running = store.list(status=RUNNING)
    assert [j.id for j in running] == [a]
    assert store.get(b).status == QUEUED


def test_wal_and_busy_timeout_enabled(store):
    assert store.pragma("journal_mode").lower() == "wal"
    assert int(store.pragma("busy_timeout")) >= 1000


def test_state_persists_across_reopen(tmp_path):
    path = tmp_path / "jobs.db"
    s1 = JobStore(path)
    jid = s1.enqueue(mode="montecarlo", model_name="ROCKET-A")
    s1.claim_next()
    s1.set_work_dir(jid, "/abs/work_montecarlo")
    s1.close()

    s2 = JobStore(path)
    job = s2.get(jid)
    assert job is not None
    assert job.status == RUNNING
    assert job.model_name == "ROCKET-A"
    assert job.work_dir == "/abs/work_montecarlo"
    s2.close()


def test_create_preparing_is_not_claimable_until_marked_queued(store):
    """The API stages inputs while a job is `preparing`; only mark_queued makes it runnable,
    closing the race where the worker could claim before inputs are extracted."""
    jid = store.create_preparing(mode="montecarlo", model_name="ROCKET-A")
    assert store.get(jid).status == PREPARING
    assert store.claim_next() is None  # not claimable while preparing
    store.mark_queued(jid)
    assert store.get(jid).status == QUEUED
    assert store.claim_next().id == jid


def test_cancel_if_queued_also_cancels_preparing(store):
    """A submission that fails during input staging must be cancellable before it runs."""
    jid = store.create_preparing(mode="area")
    assert store.cancel_if_queued(jid) is True
    assert store.get(jid).status == CANCELLED


def test_enqueued_at_is_monotonic_for_fifo(store):
    ids = [store.enqueue(mode="trajectory") for _ in range(5)]
    # claim order must equal enqueue order regardless of same-second timestamps
    claimed = []
    while True:
        j = store.claim_next()
        if j is None:
            break
        claimed.append(j.id)
        store.mark_completed(j.id, result_dir="/x")
    assert claimed == ids
