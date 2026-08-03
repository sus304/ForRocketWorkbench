"""Re-run a finished job with byte-identical inputs.

The use case is verifying a deploy: after a solver or Workbench fix, run the *same* case again
and compare. That only works if "the same case" is exact, so the inputs come from the source
job's staged run dir — not from the project it was submitted from, which may have been edited in
the meantime (and for an uploaded closure no longer exists at all). The staged run dir is the
only record of what actually ran.

A re-run is a new job, never an overwrite of the old one: the whole point is to hold the two
results side by side, and the source job's result directory is what the comparison reads.
`rerun_of` links them, `input_hash` proves the inputs matched, and the version columns say which
build produced each result (see service.store).

Monte Carlo carries a caveat the UI states plainly: its error parameters are re-sampled, so a
re-run is a different population and only comparable statistically. Replaying the *same*
population is possible — the realised per-case inputs live in the source work_dir's `cases/`, and
`resume_montecarlo` reuses them rather than re-sampling — but it is deliberately not implemented
here; see docs/compute_server_design.md.
"""
from __future__ import annotations

import re
import shutil

from service.store import PREPARING, QUEUED, RUNNING
from service.uploads import closure_hash, copy_closure, iter_closure_files
from version import workbench_version

_ACTIVE = {PREPARING, QUEUED, RUNNING}

# Trailing "(rerun of #12)" added by a previous re-run, so re-running a re-run does not accrete
# one suffix per generation.
_MEMO_SUFFIX = re.compile(r"\s*\(rerun of #\d+\)\s*$")


class RerunRejected(Exception):
    """The job cannot be re-run at all (nothing to re-run from). Mapped to 422."""


class RerunConflict(RerunRejected):
    """The job could be re-run, but not right now / not any more — it is still active, or its
    inputs have been removed from disk. Mapped to 409."""


class RerunNotFound(RerunRejected):
    """No such job. Mapped to 404."""


def default_memo(memo: str, source_id: int) -> str:
    """Memo for the new job: the source's memo, tagged with where it came from."""
    base = _MEMO_SUFFIX.sub("", memo or "").strip()
    tag = f"(rerun of #{source_id})"
    return f"{base} {tag}" if base else tag


def rerun_job(store, worker, job_id: int, memo=None, use_max_thread=None) -> int:
    """Create a queued copy of `job_id` with the same inputs. Returns the new job id.

    Runs synchronously in the caller's thread (the API hands it to a threadpool): copying a
    staged run dir is filesystem work, not compute, so it must not queue behind a running job.
    """
    job = store.get(job_id)
    if job is None:
        raise RerunNotFound(f"job {job_id} not found")
    if job.status in _ACTIVE:
        raise RerunConflict("job is still active; wait for it to finish or cancel it first")
    if getattr(job, "source_path", ""):
        raise RerunRejected(
            "an imported job holds only a copied result, not the inputs that produced it; "
            "there is nothing to re-run")

    src_dir = worker.run_dir_for(job.id)
    if not src_dir.is_dir() or not any(iter_closure_files(src_dir)):
        raise RerunConflict("the original job's inputs are no longer on disk")

    # Backfill the source's hash if it predates this column, so the UI can compare the pair.
    src_hash = getattr(job, "input_hash", "") or ""
    if not src_hash:
        src_hash = closure_hash(src_dir)
        if src_hash:
            store.set_input_hash(job.id, src_hash)

    new_id = store.create_preparing(
        mode=job.mode,
        model_name=job.model_name,
        use_max_thread=job.use_max_thread if use_max_thread is None else bool(use_max_thread),
        project=getattr(job, "project", "") or "",
        memo=default_memo(getattr(job, "memo", ""), job.id) if memo is None else memo,
        rerun_of=job.id,
        code_version=workbench_version(),
    )
    dest_dir = worker.run_dir_for(new_id)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        copy_closure(src_dir, dest_dir)
    except OSError as e:
        store.mark_failed(new_id, f"rerun input copy failed: {e}")
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise RerunRejected(f"input copy failed: {e}")

    store.set_input_hash(new_id, closure_hash(dest_dir))
    store.mark_queued(new_id)   # claimable only now that the inputs are in place
    return new_id
