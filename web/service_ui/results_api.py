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

# logical KML name (from result_meta['kml']) → manifest role. Non-flight-path (MC dispersion)
# logical names end with the kind token, so match on that.
_ROLE_NAME = {
    "nominal": "飛行経路", "iip": "IIP 軌跡", "points": "落下点群",
    "envelope": "3σ 包絡", "ellipse": "分散楕円", "track": "flight_log",
}


def kml_role(logical: str) -> str:
    """Map a list_kml logical name to a manifest role (nominal/iip/points/envelope/ellipse)."""
    if logical == "trajectory":
        return "nominal"
    if logical == "iip":
        return "iip"
    for kind in ("points", "ellipse", "envelope"):
        if logical.endswith(kind):
            return kind
    return "nominal"


def build_job_manifest(job_id: int, status: dict, meta: dict, generated: str = "") -> dict:
    """Synthesise the viewer manifest for a job from its status + result meta. Pure/deterministic
    (timestamp is injected by the caller) so it is unit-testable."""
    project = status.get("project") or status.get("model_name") or f"job {job_id}"
    items = []
    for logical in meta.get("kml", []):
        role = kml_role(logical)
        items.append({
            "id": logical,
            "name": _ROLE_NAME.get(logical) or _ROLE_NAME.get(role) or logical,
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
def job_flight_log(job_id: int):
    try:
        data = _client().extract_file(job_id, "nominal", fmt="csv", max_points=0)
    except Exception as exc:
        raise HTTPException(404, f"flight_log not available: {exc}")
    return Response(content=data, media_type="text/csv")
