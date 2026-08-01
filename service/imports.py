"""Import a result directory produced outside the job service into the job ledger.

Analysis work elsewhere on the server drives the same `runner.py` from its own tree, so the
`work_trajectory` directories it leaves behind are structurally identical to a job's work_dir
and are self-contained (the runner copies every referenced config/CSV into the work dir). A
result therefore only needs to be copied into the job store, post-processed, and recorded as a
completed job — no re-computation.

**Copy, not reference.** The result_dir stays inside data_root, so the existing result-API
boundary (`api.resolve_result_dir`) and the delete semantics (`jobs/<id>` removal) are unchanged,
and `post.py` writes its plots/KML/summary into *our* copy — never into the source tree, which
belongs to another repository.

**Path trust boundary.** This module validates a path structurally (exists, real directory, no
symlink, outside data_root, detectable mode, within the size cap) but holds no allow-list: the
caller supplies an absolute path and must be authorised to name it. The browser never reaches
here directly — the webui resolves a user's choice against its configured result roots
(`WB_RESULT_ROOTS`) before calling the API with the bearer token, mirroring how the read-only
filesystem gateway serves the same trees.

Only trajectory is importable. Monte Carlo populations are GB-scale and are submitted as jobs
instead, which is also the only way their per-case statistics get produced.
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import shutil
from pathlib import Path
from typing import Optional

from service.store import CANCELLED, FAILED

# Work-directory name prefix -> mode (mirrors path_define's work dir names).
_DIR_PREFIX_MODE = {
    "work_trajectory": "trajectory",
    "work_area": "area",
    "work_montecarlo": "montecarlo",
    "work_sensitivity": "sensitivity",
}

# Fallback markers for a work dir that was renamed and no longer carries a `work_<mode>` prefix.
_MARKER_MODE = [
    ("sensitivity", ["sensitivity_results.csv"]),
    ("montecarlo", ["result_table.csv", "decent_result_table.csv", "ballistic_result_table.csv"]),
]

# What may be imported. Deliberately narrow: an MC work dir is GB-scale and its result tables are
# only produced by a full post run over the population.
IMPORTABLE_MODES = ("trajectory",)

# Refuse anything that is not plausibly a single trajectory run. A trajectory work dir is tens of
# MB (one flight log plus the copied inputs); this cap is the guard against pointing the importer
# at a population directory by mistake.
MAX_IMPORT_BYTES = 2 * 1024 ** 3
MAX_IMPORT_FILES = 5000


class ImportRejected(Exception):
    """The source directory cannot be imported (not a result dir, wrong mode, too large,
    already imported, ...). Mapped to 422 by the API layer."""


def detect_mode(result_dir) -> Optional[str]:
    """Infer the run mode from the work directory name, falling back to marker files and finally
    to a bare flight log. None if undetectable."""
    result_dir = str(result_dir)
    name = os.path.basename(os.path.normpath(result_dir))
    for prefix, mode in _DIR_PREFIX_MODE.items():
        if name == prefix or name.startswith(prefix + "_"):
            return mode
    for mode, markers in _MARKER_MODE:
        if any(os.path.isfile(os.path.join(result_dir, m)) for m in markers):
            return mode
    # cases/ means a multi-case run; without the tables above we cannot tell which, so only a
    # flat flight log at the top level identifies a single trajectory run.
    if os.path.isdir(os.path.join(result_dir, "cases")):
        return None
    if glob.glob(os.path.join(result_dir, "*_flight_log.csv")):
        return "trajectory"
    return None


def is_posted(result_dir) -> bool:
    """True if post.py has already run here (it creates one `result_<model>/` per flight log).
    post_trajectory does an unconditional mkdir, so re-posting an already-posted directory
    raises FileExistsError — the importer skips post in that case."""
    return any(p.is_dir() for p in Path(result_dir).glob("result_*"))


def _extract_model_id(result_dir) -> str:
    path = Path(result_dir) / "config_solver.json"
    if not path.is_file():
        return ""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("Model ID", "") or ""
    except (OSError, ValueError):
        return ""


def measure(result_dir, max_bytes: int = MAX_IMPORT_BYTES, max_files: int = MAX_IMPORT_FILES):
    """Return (bytes, files) for the tree, stopping early once a cap is exceeded so pointing at a
    huge directory costs a partial walk rather than a full one. Symlinks are not followed and are
    not counted (they are dropped by the copy as well)."""
    total = 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(result_dir):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for f in filenames:
            p = os.path.join(dirpath, f)
            if os.path.islink(p):
                continue
            count += 1
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
            if total > max_bytes or count > max_files:
                return total, count
    return total, count


def _resolve(source: str) -> Path:
    if not source or not str(source).strip():
        raise ImportRejected("no directory given")
    p = Path(source).expanduser()
    if p.is_symlink():
        raise ImportRejected("source is a symlink")
    p = p.resolve()
    if not p.is_dir():
        raise ImportRejected(f"not a directory: {p}")
    return p


def inspect(source: str, store=None, data_root=None) -> dict:
    """Examine a candidate directory without touching it or the store.

    Returns the fields the confirmation dialog renders. `ok` is True only if an import would be
    accepted; otherwise `error` says why. Never raises for a merely unsuitable directory — only
    for an unusable path.
    """
    info = {
        "ok": False, "error": "", "source": "", "name": "", "mode": None,
        "model_id": "", "posted": False, "bytes": 0, "files": 0,
        "duplicate_job_id": None, "modified": None,
    }
    try:
        src = _resolve(source)
    except ImportRejected as e:
        info["error"] = str(e)
        return info

    info["source"] = str(src)
    info["name"] = src.name

    if data_root is not None:
        root = Path(data_root).resolve()
        if src == root or root in src.parents:
            info["error"] = "already inside the job store"
            return info

    info["mode"] = detect_mode(src)
    info["model_id"] = _extract_model_id(src)
    info["posted"] = is_posted(src)
    try:
        info["modified"] = datetime.datetime.fromtimestamp(src.stat().st_mtime).isoformat(
            timespec="seconds")
    except OSError:
        pass

    if store is not None:
        existing = store.find_by_source(str(src))
        # A failed or cancelled attempt is not a duplicate: a transient post/copy failure must not
        # lock the source out of ever being imported again.
        if existing is not None and existing.status not in (FAILED, CANCELLED):
            info["duplicate_job_id"] = existing.id

    if info["mode"] is None:
        info["error"] = ("could not identify a result directory (expected a work_trajectory "
                         "directory, or one holding a *_flight_log.csv)")
        return info
    if info["mode"] not in IMPORTABLE_MODES:
        info["error"] = (f"{info['mode']} results are not importable; submit them as a job "
                         "instead")
        return info

    # Caps passed explicitly (not via the default args, which bind at import time) so the early
    # exit and the checks below always agree on the same limits.
    total, count = measure(src, MAX_IMPORT_BYTES, MAX_IMPORT_FILES)
    info["bytes"], info["files"] = total, count
    if total > MAX_IMPORT_BYTES:
        info["error"] = f"too large ({total} bytes > {MAX_IMPORT_BYTES})"
        return info
    if count > MAX_IMPORT_FILES:
        info["error"] = f"too many files ({count} > {MAX_IMPORT_FILES})"
        return info
    if info["duplicate_job_id"] is not None:
        info["error"] = f"already imported as job #{info['duplicate_job_id']}"
        return info

    info["ok"] = True
    return info


def _ignore_symlinks(dirpath, names):
    """copytree filter: never follow or reproduce a symlink, and never pull in a `cases/`
    population (a trajectory dir has none; this is belt-and-braces)."""
    drop = {n for n in names if os.path.islink(os.path.join(dirpath, n))}
    drop.add("cases")
    return drop


def import_result(store, worker, source: str, memo: str = "") -> int:
    """Copy a result directory into the job store, post-process the copy, and record it as a
    completed job. Returns the new job id; raises ImportRejected if it is not importable.

    Runs synchronously in the caller's thread (no worker queue): nothing is computed, so an
    import must not have to wait behind a running Monte Carlo.
    """
    info = inspect(source, store=store, data_root=worker.data_root)
    if not info["ok"]:
        raise ImportRejected(info["error"])

    src = Path(info["source"])
    mode = info["mode"]
    job_id = store.create_preparing(mode=mode, model_name=info["model_id"],
                                    source_path=str(src), memo=memo)
    run_dir = worker.run_dir_for(job_id)
    dest = run_dir / src.name
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, symlinks=False, ignore=_ignore_symlinks)
    except (OSError, shutil.Error) as e:
        store.mark_failed(job_id, f"import copy failed: {e}")
        shutil.rmtree(run_dir, ignore_errors=True)
        raise ImportRejected(f"copy failed: {e}")

    if not info["posted"]:
        rc, out = worker.run_post(run_dir, src.name, mode)
        if rc != 0:
            store.mark_failed(job_id, f"post.py exit {rc}\n{out[-4000:]}")
            raise ImportRejected(f"post-processing failed (exit {rc})")

    store.mark_completed(job_id, result_dir=str(dest))
    # Date the job by the source run, not by when it was imported, so the ledger orders by when
    # the result was actually produced.
    stamp = _parse_iso(info["modified"])
    if stamp is not None:
        store.set_times(job_id, started_at=stamp, finished_at=stamp)
    return job_id


def _parse_iso(value) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
