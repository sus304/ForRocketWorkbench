"""Authoritative job store for the compute service.

State lives in SQLite (WAL) instead of an in-memory singleton, so the worker can recover
after a crash or host reboot: a job left `running` when the process died is discoverable,
and its persisted `work_dir` is the anchor for a deterministic Monte Carlo resume
(docs/compute_server_design.md §4.2). This module is the data layer only; the worker
(service.worker) drives the runner subprocess and interprets the recovery.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import List, Optional, Union

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String, Text,
    create_engine, event, select, update,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Job status values. `paused` is intentionally absent: user-initiated pause was a laptop
# feature; the compute service uses cancel for interruption and automatic startup resume
# for reboot survival (design §8).
# `preparing`: the job row exists but its inputs are still being staged into the run dir by
# the API; it is not claimable until mark_queued(). This closes the submit race where the
# worker could claim a job before its inputs are extracted.
PREPARING = "preparing"
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({COMPLETED, FAILED, CANCELLED})


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mode = Column(String, nullable=False)
    model_name = Column(String, default="")
    status = Column(String, default=QUEUED, nullable=False, index=True)
    use_max_thread = Column(Boolean, default=False)

    enqueued_at = Column(DateTime, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    # work_dir is persisted the moment the runner reports it (design §4.1/§4.2); it is the
    # anchor for automatic MC resume after a crash. result_dir is the finished location.
    work_dir = Column(String, default="")
    result_dir = Column(String, default="")

    # input_ref points at the per-job saved copy of the input closure (design §6);
    # input_snapshot keeps the legacy submit-time JSON string for display parity.
    input_ref = Column(String, default="")
    input_snapshot = Column(Text, default="")

    # project: the server-side project this job was submitted from (UI refresh design §5); used to
    # group a project's recent jobs. Empty for closure-upload (wb) submits. memo: free-text label
    # for triage (design §6 / review N-1); the legacy web.db had memo, the job store did not.
    project = Column(String, default="")
    memo = Column(Text, default="")

    summary = Column(Text, default="")
    error_message = Column(Text, default="")


def _now() -> datetime.datetime:
    return datetime.datetime.now()


class JobStore:
    """Thin SQLite-backed store. One instance per process; methods are self-contained
    (open session, act, close) so they are safe to call from the worker thread and API
    handlers concurrently, backed by WAL + busy_timeout."""

    def __init__(self, db_path: Union[str, Path]):
        self._path = str(db_path)
        self._engine = create_engine(
            f"sqlite:///{self._path}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self._engine, "connect")
        def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)
        Base.metadata.create_all(self._engine)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created. create_all() does not ALTER an
        existing table, so a jobs.db from before `project`/`memo` needs them added explicitly."""
        from sqlalchemy import text
        with self._engine.begin() as conn:
            existing = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
            for col in ("project", "memo"):
                if col not in existing:
                    coltype = "VARCHAR" if col == "project" else "TEXT"
                    conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col} {coltype} DEFAULT ''"))

    # --- writes -------------------------------------------------------------

    def enqueue(self, mode: str, model_name: str = "", use_max_thread: bool = False,
                input_ref: str = "", input_snapshot: str = "") -> int:
        with self._Session() as session:
            job = Job(
                mode=mode,
                model_name=model_name,
                use_max_thread=use_max_thread,
                status=QUEUED,
                enqueued_at=_now(),
                input_ref=input_ref,
                input_snapshot=input_snapshot,
            )
            session.add(job)
            session.commit()
            return job.id

    def create_preparing(self, mode: str, model_name: str = "", use_max_thread: bool = False,
                         input_ref: str = "", input_snapshot: str = "", project: str = "") -> int:
        """Create a job in `preparing` (not yet claimable). Call mark_queued() once inputs
        are staged."""
        with self._Session() as session:
            job = Job(
                mode=mode,
                model_name=model_name,
                use_max_thread=use_max_thread,
                status=PREPARING,
                enqueued_at=_now(),
                input_ref=input_ref,
                input_snapshot=input_snapshot,
                project=project,
            )
            session.add(job)
            session.commit()
            return job.id

    def set_memo(self, job_id: int, memo: str) -> None:
        self._update(job_id, memo=memo)

    def mark_queued(self, job_id: int) -> None:
        self._update(job_id, status=QUEUED)

    def claim_next(self) -> Optional[Job]:
        """Atomically move the oldest queued job to running and return it, else None.

        The conditional UPDATE (WHERE status=queued) serialises the transition so a job is
        never claimed twice even if a second caller races (design §4.2). FIFO by
        (enqueued_at, id); id breaks same-timestamp ties in enqueue order."""
        with self._Session() as session:
            row = session.execute(
                select(Job.id)
                .where(Job.status == QUEUED)
                .order_by(Job.enqueued_at.asc(), Job.id.asc())
                .limit(1)
            ).first()
            if row is None:
                return None
            jid = row[0]
            res = session.execute(
                update(Job)
                .where(Job.id == jid, Job.status == QUEUED)
                .values(status=RUNNING, started_at=_now())
            )
            session.commit()
            if res.rowcount != 1:
                return None  # lost the race; a single worker never hits this
            job = session.get(Job, jid)
            session.expunge(job)
            return job

    def set_work_dir(self, job_id: int, work_dir: str) -> None:
        self._update(job_id, work_dir=work_dir)

    def mark_completed(self, job_id: int, result_dir: str, summary: str = "") -> None:
        self._update(job_id, status=COMPLETED, result_dir=result_dir, summary=summary,
                     finished_at=_now())

    def mark_failed(self, job_id: int, error_message: str) -> None:
        self._update(job_id, status=FAILED, error_message=error_message, finished_at=_now())

    def mark_cancelled(self, job_id: int) -> None:
        self._update(job_id, status=CANCELLED, finished_at=_now())

    def cancel_if_queued(self, job_id: int) -> bool:
        """Cancel a not-yet-started job atomically (queued or still preparing). Returns True
        iff it flipped to cancelled. A running job is left untouched (the worker terminates
        it)."""
        with self._Session() as session:
            res = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status.in_([QUEUED, PREPARING]))
                .values(status=CANCELLED, finished_at=_now())
            )
            session.commit()
            return res.rowcount == 1

    def requeue(self, job_id: int) -> None:
        """Reset a job to queued for recovery re-run (short modes have no resume path)."""
        self._update(job_id, status=QUEUED, started_at=None, finished_at=None, work_dir="")

    def _update(self, job_id: int, **values) -> None:
        with self._Session() as session:
            session.execute(update(Job).where(Job.id == job_id).values(**values))
            session.commit()

    # --- reads --------------------------------------------------------------

    def get(self, job_id: int) -> Optional[Job]:
        with self._Session() as session:
            job = session.get(Job, job_id)
            if job is not None:
                session.expunge(job)
            return job

    def list(self, status: Optional[str] = None, limit: int = 500) -> List[Job]:
        """Newest-first for display."""
        with self._Session() as session:
            stmt = select(Job)
            if status is not None:
                stmt = stmt.where(Job.status == status)
            stmt = stmt.order_by(Job.id.desc()).limit(limit)
            jobs = list(session.execute(stmt).scalars())
            session.expunge_all()
            return jobs

    def pragma(self, name: str):
        with self._engine.connect() as conn:
            return conn.exec_driver_sql(f"PRAGMA {name}").scalar()

    def close(self) -> None:
        self._engine.dispose()
