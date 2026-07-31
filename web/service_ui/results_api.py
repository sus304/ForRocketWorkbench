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
    if "flight" in (meta.get("kinds") or []):
        items.append({
            "id": "flight_log", "name": "flight_log", "kind": "csv",
            "path": "flight_log", "role": "track", "group": "経路",
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
    import datetime
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


@app.get("/api/results/jobs/{job_id}/flight_log")
def job_flight_log(job_id: int, phase: str = "stage1"):
    # csv export needs the selection to resolve to exactly one log; a trajectory job has a
    # stage1 (ascent) and a ballistic log per case, so pin a phase (default the ascent track).
    try:
        data = _client().extract_file(job_id, "nominal", fmt="csv", phase=phase, max_points=0)
    except Exception as exc:
        raise HTTPException(404, f"flight_log not available: {exc}")
    return Response(content=data, media_type="text/csv")
