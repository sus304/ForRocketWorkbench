"""Server-side project store for the UI-refresh model (docs/ui_refresh_design.md §3).

The compute service (jobsvc) persistently owns projects under WB_DATA_ROOT/projects/<name>/ as
plain directories of config/input files (DB-free). The browser edits a stored project's config
through the projects API and submits runs by reference; pack_closure then runs against the
trusted store. All write entry points (upload, config save, copy) enforce:
  - project name sanitisation ([A-Za-z0-9_-], within projects/),
  - every path-valued config field stays inside the project (no absolute / .. / symlink escape;
    generic scan of *Path* / *File List* keys across all JSON, so no hand-list to drift — review
    N-6),
  - a dedicated ZIP-safe extractor (tar's safe_extract does not cover ZIP; Zip Slip, symlinks,
    decompression bombs — review R-C),
  - atomic swap on update (a torn extract never corrupts a good project — review N-15),
  - optimistic-concurrency etag on config save (409 on stale write — review N-10).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_UNZIP_BYTES = 500 * 1024 ** 2   # 500 MB uncompressed total (review §14 default)
MAX_UNZIP_ENTRIES = 5000


class ProjectError(Exception):
    """Bad request against a project (invalid name/path, malformed zip) -> 400/422."""


class ProjectNotFound(ProjectError):
    """Project does not exist -> 404."""


class ProjectExists(ProjectError):
    """Target project already exists -> 409."""


class ProjectConflict(ProjectError):
    """Stale config write (etag mismatch) -> 409."""


def _projects_root(data_root) -> Path:
    return Path(data_root) / "projects"


def _safe_name(name: str) -> str:
    if not name or not _NAME_RE.match(name):
        raise ProjectError(f"invalid project name: {name!r}")
    return name


def project_dir(data_root, name: str) -> Path:
    root = _projects_root(data_root)
    p = root / _safe_name(name)
    # defence in depth: the sanitised name cannot escape, but confirm containment anyway.
    if root.resolve() != p.resolve().parent:
        raise ProjectError(f"project path escapes store: {name!r}")
    return p


# ── path-field validation (review N-6) ──────────────────────────────────────────

def _is_path_key(key: str) -> bool:
    return key.endswith("Path") or key.endswith("File List")


def _iter_path_values(obj):
    """Yield every string value under a path-like key, recursively (nested config dicts)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and _is_path_key(k):
                yield k, v
            else:
                yield from _iter_path_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_path_values(v)


def _check_relative(value: str) -> None:
    if not value:
        return
    v = value.replace("\\", "/")
    if os.path.isabs(value) or v.startswith("/") or ".." in Path(v).parts or v.startswith("~"):
        raise ProjectError(f"config path must be inside the project (relative): {value!r}")


def validate_project_paths(proj: Path) -> None:
    """Every path-valued field in every JSON config must be project-relative (no absolute/../).
    Also reject symlinks anywhere in the tree (escape via link)."""
    for f in proj.rglob("*"):
        if f.is_symlink():
            raise ProjectError(f"symlink not allowed in project: {f.name}")
    for jf in sorted(proj.glob("*.json")):
        try:
            data = json.loads(jf.read_text())
        except (OSError, ValueError):
            continue
        for _k, val in _iter_path_values(data):
            _check_relative(val)


# ── ZIP-safe extractor (review R-C) ─────────────────────────────────────────────

def safe_unzip(zip_bytes: bytes, dest: Path) -> None:
    """Extract a project ZIP into dest with Zip Slip / symlink / decompression-bomb guards.
    Validates all members before writing any (a bad entry aborts the whole extract)."""
    dest = Path(dest)
    try:
        zf = zipfile.ZipFile(__import__("io").BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise ProjectError(f"not a valid zip: {e}")
    infos = zf.infolist()
    if len(infos) > MAX_UNZIP_ENTRIES:
        raise ProjectError(f"too many entries ({len(infos)} > {MAX_UNZIP_ENTRIES})")
    total = 0
    for info in infos:
        name = info.filename
        if name.endswith("/"):
            continue
        # Zip Slip: normalised path must stay under dest.
        target = (dest / name).resolve()
        if dest.resolve() != target and dest.resolve() not in target.parents:
            raise ProjectError(f"zip entry escapes destination: {name}")
        # symlink members (Unix mode in external_attr high bits, S_IFLNK=0xA000)
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ProjectError(f"symlink in zip not allowed: {name}")
        total += info.file_size
        if total > MAX_UNZIP_BYTES:
            raise ProjectError(f"uncompressed size exceeds {MAX_UNZIP_BYTES} bytes")
    for info in infos:
        if info.filename.endswith("/"):
            continue
        target = (dest / info.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, length=1 << 20)


def _descend_single_top(d: Path) -> Path:
    """If the extract produced a single top-level directory (OS 'compress folder' wraps one
    level) and no top-level config, descend into it (review N-5/1階層ネスト)."""
    entries = [e for e in d.iterdir() if e.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir() and not (d / "config_solver.json").exists():
        return entries[0]
    return d


# ── store operations ────────────────────────────────────────────────────────────

def list_projects(data_root) -> List[dict]:
    root = _projects_root(data_root)
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and _NAME_RE.match(p.name):
            out.append({"name": p.name, "updated_at": p.stat().st_mtime})
    return out


def create_project(data_root, name: str) -> Path:
    p = project_dir(data_root, name)
    if p.exists():
        raise ProjectExists(f"project already exists: {name}")
    p.mkdir(parents=True)
    return p


def copy_project(data_root, src: str, dst: str) -> Path:
    s = project_dir(data_root, src)
    if not s.is_dir():
        raise ProjectNotFound(f"project not found: {src}")
    d = project_dir(data_root, dst)   # sanitises the destination name too (review SEC)
    if d.exists():
        raise ProjectExists(f"project already exists: {dst}")
    shutil.copytree(s, d, symlinks=False, ignore=shutil.ignore_patterns("work_*"))
    return d


def delete_project(data_root, name: str) -> None:
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    shutil.rmtree(p)


def _etag(proj: Path) -> str:
    mtimes = [f.stat().st_mtime_ns for f in proj.glob("*.json")]
    return str(max(mtimes)) if mtimes else "0"


def read_config(data_root, name: str) -> dict:
    """Return {'etag': str, 'files': {filename: parsed_json}} for the project's JSON configs."""
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    files = {}
    for jf in sorted(p.glob("*.json")):
        try:
            files[jf.name] = json.loads(jf.read_text())
        except (OSError, ValueError):
            continue
    return {"etag": _etag(p), "files": files}


def write_config(data_root, name: str, files: dict, if_match: Optional[str] = None) -> dict:
    """Write edited JSON config files back into the project. Validates path fields, checks the
    optimistic etag (409 on mismatch), and writes each file atomically (tmp + os.replace)."""
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    if if_match is not None and if_match != _etag(p):
        raise ProjectConflict("project changed since it was loaded (stale write)")
    # Validate before writing anything (all-or-nothing).
    for fname, content in files.items():
        if "/" in fname or "\\" in fname or fname.startswith("."):
            raise ProjectError(f"invalid config filename: {fname}")
        for _k, val in _iter_path_values(content):
            _check_relative(val)
    for fname, content in files.items():
        target = p / fname
        fd, tmp = tempfile.mkstemp(dir=str(p), suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(content, fh, indent=4)
        os.replace(tmp, target)
    return {"etag": _etag(p)}


def upload_project(data_root, name: str, zip_bytes: bytes) -> Path:
    """Create/update a project from an uploaded ZIP. Safe-unzip to a temp dir, descend a single
    wrapper dir, validate paths, then atomically swap into place (old kept on failure)."""
    root = _projects_root(data_root)
    root.mkdir(parents=True, exist_ok=True)
    dest = project_dir(data_root, name)
    staging = Path(tempfile.mkdtemp(dir=str(root), prefix=".upload_"))
    try:
        safe_unzip(zip_bytes, staging)
        content = _descend_single_top(staging)
        validate_project_paths(content)
        if not (content / "config_solver.json").exists():
            raise ProjectError("upload missing config_solver.json at project root")
        # atomic swap
        backup = None
        if dest.exists():
            backup = root / f".bak_{name}_{os.getpid()}"
            os.replace(dest, backup)
        try:
            os.replace(content, dest)
        except OSError:
            if backup is not None:
                os.replace(backup, dest)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return dest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def download_project(data_root, name: str) -> bytes:
    """Zip the project directory (excluding work_* outputs) for download."""
    import io
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(p.rglob("*")):
            if f.is_file() and not any(part.startswith("work_") for part in f.relative_to(p).parts):
                zf.write(f, arcname=str(Path(name) / f.relative_to(p)))
    return buf.getvalue()
