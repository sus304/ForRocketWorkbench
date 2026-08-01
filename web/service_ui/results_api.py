"""Browser-facing result endpoints for an embedded 3D viewer (docs/ui_refresh_design §12 / the
RocketEarth-integration survey §10.6).

These live on the webui app (same origin as the pages, under AuthMiddleware → session-cookie
authed) so an embedded viewer's browser JS can fetch a run's data WITHOUT the jobsvc Bearer token
(the token stays inside webui). The webui proxies each request to jobsvc via ServiceClient and
streams the bytes back. The manifest is a product-neutral contract (`result-manifest/1`): the
viewer reads only `<base>/index.json` then `<base>/<path>`, so data sources can be added without
changing the viewer.

Job results reuse the already-validated jobsvc result API (KML by logical name, flight_log via
extract) — no new filesystem traversal here. Generic filesystem roots are served separately
(WB_RESULT_ROOTS), where real relative paths are validated with containment/symlink/ext checks.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response
from nicegui import app

from web.service_ui import config

# manifest role → display label. list_kml logical names are "{qualifier}_{kind}" (qualifier is a
# phase like stage1/ballistic, or an MC scenario like decent/ballistic) or a bare kind.
_ROLE_NAME = {
    "nominal": "飛行経路", "iip": "IIP 軌跡", "points": "落下点群",
    "envelope": "3σ 包絡", "ellipse": "分散楕円", "track": "flight_log",
}
# kind token (suffix of the logical name) → role.
_KIND_ROLE = (("trajectory", "nominal"), ("iip", "iip"), ("points", "points"),
              ("envelope", "envelope"), ("ellipse", "ellipse"))


def kml_role(logical: str) -> str:
    """Map a list_kml logical name to a manifest role, matching on the kind token so phase- or
    scenario-qualified names (stage1_trajectory, decent_points, ballistic_iip) classify correctly."""
    for kind, role in _KIND_ROLE:
        if logical == kind or logical.endswith("_" + kind):
            return role
    return "nominal"


def _kml_label(logical: str, role: str) -> str:
    """Readable, unambiguous name: '<qualifier> <role label>' (e.g. 'stage1 飛行経路'), or just
    the role label when unqualified."""
    for kind, _r in _KIND_ROLE:
        if logical == kind:
            return _ROLE_NAME.get(role, logical)
        if logical.endswith("_" + kind):
            qualifier = logical[: -(len(kind) + 1)]
            return f"{qualifier} {_ROLE_NAME.get(role, kind)}".strip()
    return _ROLE_NAME.get(role, logical)


def build_job_manifest(job_id: int, status: dict, meta: dict, generated: str = "") -> dict:
    """Synthesise the viewer manifest for a job from its status + result meta. Pure/deterministic
    (timestamp is injected by the caller) so it is unit-testable."""
    project = status.get("project") or status.get("model_name") or f"job {job_id}"
    items = []
    for logical in meta.get("kml", []):
        role = kml_role(logical)
        items.append({
            "id": logical,
            "name": _kml_label(logical, role),
            "kind": "kml",
            "path": f"kml/{logical}",
            "role": role,
            "group": "経路" if role in ("nominal", "iip") else "分散",
        })
    # One flight_log per phase (stage1 ascent / ballistic descent). `path` is pure path segments —
    # the viewer encodeURIComponents each segment, so a query string (?phase=) would break; the
    # phase is a path segment instead (review: RocketEarth feedback #2).
    for phase in meta.get("phases", []):
        items.append({
            "id": f"flight_log_{phase}", "name": f"{phase} flight_log", "kind": "csv",
            "path": f"flight_log/{phase}", "role": "track", "group": "経路",
        })
    return {
        "schema": "result-manifest/1",
        "title": f"{project}（job {job_id}）",
        "generated": generated,
        "source": {"kind": "job", "id": job_id, "mode": meta.get("mode")},
        "items": items,
    }


def _client():
    return config.get_client()


@app.get("/api/results/jobs/{job_id}/index.json")
def job_manifest(job_id: int):
    c = _client()
    try:
        status = c.status(job_id)
        meta = c.result_meta(job_id)
    except Exception as exc:  # jobsvc unreachable / no result yet
        raise HTTPException(404, f"no result for job {job_id}: {exc}")
    manifest = build_job_manifest(job_id, status, meta,
                                  generated=datetime.datetime.now().isoformat(timespec="seconds"))
    return manifest


@app.get("/api/results/jobs/{job_id}/kml/{name}")
def job_kml(job_id: int, name: str):
    try:
        data = _client().result_kml(job_id, name)
    except Exception as exc:
        raise HTTPException(404, f"kml not available: {exc}")
    return Response(content=data, media_type="application/vnd.google-earth.kml+xml")


@app.get("/api/results/jobs/{job_id}/flight_log/{phase}")
def job_flight_log(job_id: int, phase: str):
    # Phase is a path segment (not a query) so the viewer's per-segment encodeURIComponent keeps it
    # intact. csv export needs the selection to resolve to exactly one log, which a single phase
    # (stage1 / ballistic) of the nominal case does.
    try:
        data = _client().extract_file(job_id, "nominal", fmt="csv", phase=phase, max_points=0)
    except Exception as exc:
        raise HTTPException(404, f"flight_log not available: {exc}")
    return Response(content=data, media_type="text/csv")


# ── generic read-only filesystem result gateway (WB_RESULT_ROOTS) ─────────────────
# Serves result files (and a synthesised manifest) from admin-configured roots so results that
# aren't Workbench jobs (e.g. analysis outputs elsewhere on the server) can be viewed too. The
# code is product-neutral: it classifies by file EXTENSION only and carries no directory/tool
# names — those live on the server filesystem + the WB_RESULT_ROOTS env value, never in the repo.
# Owners may drop a static index.json to control roles/labels; otherwise a neutral manifest is
# synthesised. Security: containment (realpath under the root), no symlinks, extension allow-list,
# `cases/` excluded (a Monte-Carlo cases/ can hold tens of thousands of files).
_VIEW_EXTS = {".kml", ".kmz", ".csv", ".geojson", ".json"}
_KIND_BY_EXT = {".kml": "kml", ".kmz": "kmz", ".csv": "csv", ".geojson": "geojson"}
_MEDIA = {".kml": "application/vnd.google-earth.kml+xml", ".kmz": "application/vnd.google-earth.kmz",
          ".csv": "text/csv", ".geojson": "application/geo+json", ".json": "application/json"}
_MAX_LIST_DEPTH = 3


def fs_scan_manifest(target: Path, root: str, rel: str, generated: str = "") -> dict:
    """Neutral manifest for a directory: a static index.json wins; otherwise synthesise items from
    the directory's own files, classifying by extension only (no domain knowledge). Pure/testable."""
    idx = target / "index.json"
    if idx.is_file() and not idx.is_symlink():
        try:
            data = json.loads(idx.read_text())
        except (ValueError, OSError):
            data = None
        # Only trust it if it actually looks like a viewer manifest — a dir may hold an unrelated
        # index.json; otherwise fall back to synthesis (review: RocketEarth feedback #3).
        if isinstance(data, dict) and str(data.get("schema", "")).startswith("result-manifest/"):
            return data
    items = []
    for name in sorted(os.listdir(target)):
        p = target / name
        if p.is_symlink() or not p.is_file():
            continue
        kind = _KIND_BY_EXT.get(p.suffix.lower())
        if not kind:
            continue
        items.append({
            "id": name, "name": name, "kind": kind, "path": name,
            "role": "track" if kind == "csv" else "nominal",   # neutral defaults; owner may override
            "group": "", "bytes": p.stat().st_size,
        })
    return {"schema": "result-manifest/1", "title": rel or root, "generated": generated,
            "source": {"kind": "fs", "root": root, "rel": rel}, "items": items}


def _root_dir(root: str) -> Path:
    d = config.result_roots().get(root)
    if d is None or not d.is_dir():
        raise HTTPException(404, f"unknown result root: {root}")
    return d


def _safe_target(root_dir: Path, rel: str) -> Path:
    """Resolve root_dir/rel, refusing traversal, symlinks and cases/. Containment via realpath."""
    v = (rel or "").replace("\\", "/").strip("/")
    if not v:
        return root_dir
    parts = v.split("/")
    if ".." in parts or v.startswith("~") or "cases" in parts:
        raise HTTPException(404, "not served")
    target = root_dir / v
    rp, tp = root_dir.resolve(), target.resolve()
    if rp != tp and rp not in tp.parents:
        raise HTTPException(400, "path escapes root")
    return target


@app.get("/api/results/roots")
def result_roots_list():
    return {"roots": sorted(config.result_roots().keys())}


def scan_result_sets(root_dir: Path) -> list:
    """Directories (depth ≤ 3, cases/ and symlinks skipped) under root_dir that hold at least one
    viewable file. Names come from the live filesystem, not code. Shared by the _list endpoint and
    the Workbench results-browser UI (so the viewer never has to know Workbench URLs — feedback #1)."""
    sets = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        rel = os.path.relpath(dirpath, root_dir)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= _MAX_LIST_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames
                       if d != "cases" and not os.path.islink(os.path.join(dirpath, d))]
        if any(os.path.splitext(f)[1].lower() in _KIND_BY_EXT for f in filenames):
            sets.append("" if rel == "." else rel.replace(os.sep, "/"))
    return sorted(sets)


@app.get("/api/results/fs/{root}/_list")
def fs_list(root: str):
    return {"root": root, "sets": scan_result_sets(_root_dir(root))}


@app.get("/api/results/fs/{root}/{sub:path}")
def fs_get(root: str, sub: str):
    root_dir = _root_dir(root)
    if sub == "index.json" or sub.endswith("/index.json"):
        rel = sub[: -len("index.json")].strip("/")
        target = _safe_target(root_dir, rel)
        if not target.is_dir() or target.is_symlink():
            raise HTTPException(404, "not a result directory")
        return fs_scan_manifest(target, root, rel,
                                datetime.datetime.now().isoformat(timespec="seconds"))
    target = _safe_target(root_dir, sub)
    if target.is_symlink() or not target.is_file():
        raise HTTPException(404, "not found")
    ext = target.suffix.lower()
    if ext not in _VIEW_EXTS:
        raise HTTPException(415, "unsupported file type")
    return Response(content=target.read_bytes(), media_type=_MEDIA.get(ext, "application/octet-stream"))
