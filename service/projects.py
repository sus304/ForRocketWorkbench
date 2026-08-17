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
        raise ProjectError(
            f"config のパス {value!r} がプロジェクトの外を指しています。"
            "ファイルをプロジェクトフォルダの中に置き、"
            "プロジェクトフォルダからの相対パス（例: wind.csv）で指定してください。")


def validate_project_paths(proj: Path) -> None:
    """Every path-valued field in every JSON config must be project-relative (no absolute/../).
    Also reject symlinks anywhere in the tree (escape via link)."""
    for f in proj.rglob("*"):
        if f.is_symlink():
            raise ProjectError(
                f"シンボリックリンク {f.name} は使えません。"
                "リンクではなく実体のファイルをプロジェクトフォルダに置いてください。")
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
        raise ProjectError(f"zip ファイルとして読めません（{e}）。"
                           "壊れていないか、.zip 形式で圧縮されているか確認してください。")
    infos = zf.infolist()
    if len(infos) > MAX_UNZIP_ENTRIES:
        raise ProjectError(
            f"zip 内のファイル数が多すぎます（{len(infos)} 個 > 上限 {MAX_UNZIP_ENTRIES} 個）。"
            "計算結果の work_**** フォルダを除いて、config と入力データだけを圧縮してください。")
    total = 0
    for info in infos:
        name = info.filename
        if name.endswith("/"):
            continue
        # Zip Slip: normalised path must stay under dest.
        target = (dest / name).resolve()
        if dest.resolve() != target and dest.resolve() not in target.parents:
            raise ProjectError(
                f"zip 内の {name} がプロジェクトフォルダの外を指しています。"
                "プロジェクトフォルダを右クリックしてそのまま圧縮した zip を使ってください。")
        # symlink members (Unix mode in external_attr high bits, S_IFLNK=0xA000)
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ProjectError(
                f"zip 内の {name} はシンボリックリンクです。"
                "リンクではなく実体のファイルを含めて圧縮し直してください。")
        total += info.file_size
        if total > MAX_UNZIP_BYTES:
            raise ProjectError(
                f"zip の展開後サイズが上限 {MAX_UNZIP_BYTES // 1024 ** 2} MB を超えます。"
                "計算結果の work_**** フォルダを除いて、config と入力データだけを圧縮してください。")
    for info in infos:
        if info.filename.endswith("/"):
            continue
        target = (dest / info.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, length=1 << 20)


def _top_level_summary(d: Path, limit: int = 8) -> str:
    """What the zip actually had at its top level, for the 'config_solver.json not found' error.
    A stray top-level file (readme.txt, .DS_Store) is what usually defeats _descend_single_top,
    and the user cannot guess that from the rejection alone — so name the entries."""
    try:
        names = sorted(e.name + ("/" if e.is_dir() else "") for e in d.iterdir())
    except OSError:
        return "（読み取れませんでした）"
    if not names:
        return "（空）"
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown} … 他 {len(names) - limit} 件"


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
            raise ProjectError(
                "zip の中に config_solver.json が見つかりません。"
                "config_solver.json は zip の直下か、zip 直下の 1 つのフォルダの直下にある必要があります"
                f"（今回の zip の直下: {_top_level_summary(staging)}）。"
                "プロジェクトフォルダだけを選んで圧縮し直してください"
                "（フォルダの入れ子や、他のファイルの同梱があると読み取れません）。")
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


# ── per-file management (input data files: thrust/wind/CA CSVs, …) ────────────────
# The browser edits config *values* through read_config/write_config; these manage the *files*
# a config references (thrust curves, wind profiles, aero tables) so a stored project can be
# iterated on without re-uploading the whole ZIP. Same containment rules as everything else:
# project-relative only, no absolute/../~ escape, no symlink, and work_* outputs are off-limits.

MAX_FILE_BYTES = 100 * 1024 ** 2   # 100 MB per input file


def _resolve_within(proj: Path, relpath: str) -> Path:
    """Return the absolute path for a project-relative file, rejecting any escape or output dir."""
    if not relpath or not relpath.strip():
        raise ProjectError("empty file path")
    v = relpath.replace("\\", "/").strip()
    if os.path.isabs(relpath) or v.startswith("/") or v.startswith("~") or ".." in Path(v).parts:
        raise ProjectError(f"file path must be project-relative: {relpath!r}")
    if any(part.startswith("work_") for part in Path(v).parts):
        raise ProjectError("cannot manage files under work_ output directories")
    target = proj / v
    rp, tp = proj.resolve(), target.resolve()
    if rp != tp and rp not in tp.parents:
        raise ProjectError(f"file path escapes project: {relpath!r}")
    return target


def list_files(data_root, name: str) -> List[dict]:
    """List every regular file in the project (excluding work_* outputs and symlinks), with size
    and a config/data classification, so the editor can show a file manager."""
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    out = []
    for f in sorted(p.rglob("*")):
        rel = f.relative_to(p)
        if any(part.startswith("work_") for part in rel.parts):
            continue
        if f.is_symlink() or not f.is_file():
            continue
        out.append({
            "path": rel.as_posix(),
            "size": f.stat().st_size,
            "is_config": f.suffix == ".json",
        })
    return out


def read_file(data_root, name: str, relpath: str) -> bytes:
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    target = _resolve_within(p, relpath)
    if target.is_symlink() or not target.is_file():
        raise ProjectNotFound(f"file not found: {relpath}")
    return target.read_bytes()


def write_file(data_root, name: str, relpath: str, data: bytes) -> dict:
    """Create or replace a project input file (atomic tmp + os.replace)."""
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    if len(data) > MAX_FILE_BYTES:
        raise ProjectError(f"file exceeds {MAX_FILE_BYTES} bytes")
    target = _resolve_within(p, relpath)
    if target.is_dir():
        raise ProjectError(f"path is a directory: {relpath}")
    if target.exists() and target.is_symlink():
        raise ProjectError(f"refusing to overwrite a symlink: {relpath}")
    # A .json upload must be a valid config with only project-relative path fields — otherwise a
    # malicious config could slip an absolute wind/thrust path into the trusted store and be read
    # off the server FS at submit time, bypassing the write_config guard (review N-6/R-A).
    if target.suffix == ".json":
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ProjectError(f"invalid JSON config: {e}")
        for _k, val in _iter_path_values(parsed):
            _check_relative(val)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, target)
    return {"path": target.relative_to(p).as_posix(), "size": len(data)}


def delete_file(data_root, name: str, relpath: str) -> None:
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    target = _resolve_within(p, relpath)
    if not target.exists() or target.is_dir():
        raise ProjectNotFound(f"file not found: {relpath}")
    target.unlink()


# ── config templates (sample-valued base files) ─────────────────────────────────
# A project created empty (or hand-assembled from the few configs the user happened to have) is
# missing the ones they never wrote by hand — typically config_montecarlo.json. Instead of making
# them start from a blank file, the editor can drop in the sample-valued base config from the
# version-controlled example project: the same set the runner and the typed forms are written
# against, so it follows the solver schema without a second copy to keep in sync.

def template_dir() -> Path:
    override = os.environ.get("WB_TEMPLATE_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "projects" / "example"


def list_templates() -> List[str]:
    """Config filenames available as base files. JSON only — thrust/wind/aero CSVs are project
    data, not boilerplate, and are managed through the file manager instead."""
    d = template_dir()
    if not d.is_dir():
        return []
    return sorted(f.name for f in d.glob("*.json") if f.is_file() and not f.is_symlink())


def add_template(data_root, name: str, filename: str) -> dict:
    """Copy a sample-valued base config into the project.

    Never overwrites (409 if the file is already there): the button exists to fill a gap, and
    replacing an edited config with sample values would silently destroy work. The create is
    O_EXCL so a concurrent add cannot slip past the check."""
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    if filename not in list_templates():
        raise ProjectError(f"unknown config template: {filename!r}")
    target = _resolve_within(p, filename)
    data = (template_dir() / filename).read_bytes()
    # The template ships with the repo, but it is still config entering the trusted store — hold it
    # to the same parse + project-relative path rules as an upload (review N-6/R-A).
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ProjectError(f"invalid config template {filename}: {e}")
    for _k, val in _iter_path_values(parsed):
        _check_relative(val)
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise ProjectExists(f"file already exists: {filename}")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return {"file": filename, "etag": _etag(p)}


def referenced_files(data_root, name: str) -> List[str]:
    """Every project-relative path a config references (thrust/wind/aero files). Used by the editor
    to flag references whose target file is missing."""
    p = project_dir(data_root, name)
    if not p.is_dir():
        raise ProjectNotFound(f"project not found: {name}")
    refs: set = set()
    for jf in sorted(p.glob("*.json")):
        try:
            data = json.loads(jf.read_text())
        except (OSError, ValueError):
            continue
        for _k, val in _iter_path_values(data):
            v = (val or "").strip()
            if v:
                refs.add(v.replace("\\", "/"))
    return sorted(refs)
