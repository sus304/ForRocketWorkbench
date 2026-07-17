"""Job input packaging and hardened extraction (design §6, §7).

Job submission uploads a project's input closure as a tar.gz and the service extracts it
into a per-job run dir, then runs a subprocess there. That is effectively remote code
execution by an authenticated user, so extraction rejects path traversal (Zip Slip),
absolute paths, symlinks/special members, and oversized payloads (review 🔴G).

The closure is the whole self-contained project (minus work dirs and caches) plus one input
the runner reads from outside the project: the Monte Carlo Wind Files Zip, which
runner_montecarlo unpacks from a config path (review 🔴B). When that zip lives outside the
project it is bundled in and the config is rewritten to a relative name so the run dir is
self-contained.
"""
from __future__ import annotations

import io
import json
import os
import tarfile
from copy import deepcopy
from pathlib import Path
from typing import Iterator

from path_define import (
    runner_trajectory_directory, runner_area_directory,
    runner_montecarlo_directory, runner_sensitivity_directory,
)

_WORK_PREFIXES = (
    runner_trajectory_directory, runner_area_directory,
    runner_montecarlo_directory, runner_sensitivity_directory,
)
_EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ipynb_checkpoints"}

_BUNDLED_WIND_ZIP = "winds_input.zip"

# extraction limits (defaults; overridable per call / by the API)
_MAX_FILES = 5000
_MAX_TOTAL_BYTES = 1024 * 1024 * 1024      # 1 GiB
_MAX_FILE_BYTES = 512 * 1024 * 1024        # 512 MiB


class UploadError(Exception):
    """An upload was rejected (unsafe member or over a limit) or could not be built."""


def _is_excluded_dir(name: str) -> bool:
    return name in _EXCLUDE_DIRS or any(name.startswith(p) for p in _WORK_PREFIXES)


def _iter_closure_files(project_dir: Path) -> Iterator[Path]:
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if not _is_excluded_dir(d)]
        for f in files:
            if f.endswith(".pyc"):
                continue
            yield Path(root) / f


def pack_closure(project_dir, mode: str) -> bytes:
    """Build a tar.gz of the run's input closure. Raises UploadError if a referenced input
    is missing."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        raise UploadError(f"project directory not found: {project_dir}")

    rewritten = None       # (arcname, bytes) config file to substitute
    external = []           # [(arcname, source_path)] inputs pulled in from outside

    if mode == "montecarlo":
        rewritten, external = _resolve_external_mc_wind(project_dir)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in _iter_closure_files(project_dir):
            arc = f.relative_to(project_dir).as_posix()
            if rewritten and arc == rewritten[0]:
                continue  # replaced with the path-rewritten version below
            tar.add(str(f), arcname=arc)
        if rewritten:
            _add_bytes(tar, rewritten[0], rewritten[1])
        for arc, src in external:
            tar.add(str(src), arcname=arc)
    return buf.getvalue()


def _resolve_external_mc_wind(project_dir: Path):
    """If MC wind error is enabled and its zip lives outside the project, return the config
    rewrite and the external file to bundle. Otherwise ('', []) style empties."""
    mc_path = project_dir / "config_montecarlo.json"
    if not mc_path.exists():
        return None, []
    cfg = json.loads(mc_path.read_text())
    wind = cfg.get("Error Parameters", {}).get("Wind", {})
    if not wind.get("Enable"):
        return None, []
    raw = wind.get("Wind Files Zip Path") or ""
    if not raw:
        raise UploadError("montecarlo wind error enabled but Wind Files Zip Path is empty")
    zp = Path(raw)
    src = zp if zp.is_absolute() else (project_dir / zp)
    if not src.exists():
        raise UploadError(f"wind files zip not found: {src}")
    # inside the project already: captured by the normal walk, no rewrite needed
    try:
        src.resolve().relative_to(project_dir.resolve())
        return None, []
    except ValueError:
        pass
    new_cfg = deepcopy(cfg)
    new_cfg["Error Parameters"]["Wind"]["Wind Files Zip Path"] = _BUNDLED_WIND_ZIP
    return ("config_montecarlo.json", json.dumps(new_cfg).encode("utf-8")), [(_BUNDLED_WIND_ZIP, src)]


def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    ti = tarfile.TarInfo(arcname)
    ti.size = len(data)
    tar.addfile(ti, io.BytesIO(data))


def safe_extract(data: bytes, dest_dir, max_files: int = _MAX_FILES,
                 max_total_bytes: int = _MAX_TOTAL_BYTES,
                 max_file_bytes: int = _MAX_FILE_BYTES) -> Path:
    """Validate every member, then extract into dest_dir. Nothing is written if any member
    is unsafe or a limit is exceeded (validation runs fully before extraction)."""
    dest = Path(dest_dir).resolve()

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = tar.getmembers()
        total = 0
        count = 0
        for m in members:
            _reject_unsafe_name(m.name, dest)
            if m.isdir():
                continue
            if not m.isfile():  # symlink, hardlink, device, fifo
                raise UploadError(f"unsupported archive member type: {m.name}")
            count += 1
            if count > max_files:
                raise UploadError(f"too many files (> {max_files})")
            if m.size > max_file_bytes:
                raise UploadError(f"member too large: {m.name}")
            total += m.size
            if total > max_total_bytes:
                raise UploadError(f"upload too large (> {max_total_bytes} bytes)")

        dest.mkdir(parents=True, exist_ok=True)
        for m in members:
            if m.isdir() or m.isfile():
                tar.extract(m, path=str(dest))
    return dest


def pack_result(work_dir, full: bool = False) -> bytes:
    """tar.gz a finished run's work_dir for download. Light (default) omits the per-case
    `cases/` logs, which can be GB-scale for MC, and returns just the post-processed
    statistics/plots/manifest at the work_dir root. full=True includes everything
    (design §6)."""
    work_dir = Path(work_dir)
    if not work_dir.is_dir():
        raise UploadError(f"result directory not found: {work_dir}")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for root, dirs, files in os.walk(work_dir):
            if not full and Path(root) == work_dir:
                dirs[:] = [d for d in dirs if d != "cases"]
            for f in files:
                p = Path(root) / f
                tar.add(str(p), arcname=p.relative_to(work_dir).as_posix())
    return buf.getvalue()


def _reject_unsafe_name(name: str, dest: Path) -> None:
    if os.path.isabs(name) or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise UploadError(f"absolute path in archive: {name}")
    parts = Path(name).parts
    if ".." in parts:
        raise UploadError(f"parent traversal in archive: {name}")
    target = (dest / name).resolve()
    if target != dest and dest not in target.parents:
        raise UploadError(f"path escapes destination: {name}")
