"""Pure manifest builder for the embedded 3D viewer (web.service_ui.results_api). The streaming
routes are manual/e2e; here we lock the product-neutral manifest shape and role mapping."""
from __future__ import annotations

from web.service_ui.results_api import build_job_manifest, kml_role


def test_kml_role_mapping():
    assert kml_role("trajectory") == "nominal"
    assert kml_role("iip") == "iip"
    assert kml_role("decent_points") == "points"
    assert kml_role("ballistic_envelope") == "envelope"
    assert kml_role("decent_ellipse") == "ellipse"
    assert kml_role("ellipse") == "ellipse"


def test_build_job_manifest_trajectory():
    status = {"id": 3, "mode": "trajectory", "project": "ROCKET-A"}
    meta = {"mode": "trajectory", "kml": ["trajectory", "iip"], "kinds": ["flight"]}
    m = build_job_manifest(3, status, meta, generated="2026-07-31T20:30:00")
    assert m["schema"] == "result-manifest/1"
    assert m["source"] == {"kind": "job", "id": 3, "mode": "trajectory"}
    assert m["title"] == "ROCKET-A（job 3）"
    ids = [it["id"] for it in m["items"]]
    assert ids == ["trajectory", "iip", "flight_log"]
    traj = m["items"][0]
    assert traj["kind"] == "kml" and traj["role"] == "nominal" and traj["path"] == "kml/trajectory"
    assert traj["group"] == "経路"
    fl = m["items"][-1]
    assert fl["kind"] == "csv" and fl["role"] == "track" and fl["path"] == "flight_log"


def test_build_job_manifest_montecarlo_no_flight_logs():
    status = {"id": 6, "mode": "montecarlo", "project": "ROCKET-A"}
    meta = {"mode": "montecarlo",
            "kml": ["points", "envelope", "ellipse"], "kinds": []}  # stats-only: no per-case logs
    m = build_job_manifest(6, status, meta, generated="t")
    ids = [it["id"] for it in m["items"]]
    assert ids == ["points", "envelope", "ellipse"]        # no flight_log item when no flight kind
    assert all(it["group"] == "分散" for it in m["items"])
    assert [it["role"] for it in m["items"]] == ["points", "envelope", "ellipse"]


def test_build_job_manifest_paths_are_opaque_relative():
    meta = {"mode": "trajectory", "kml": ["trajectory"], "kinds": ["flight"]}
    m = build_job_manifest(1, {"project": "p"}, meta)
    for it in m["items"]:
        assert not it["path"].startswith("/")   # viewer appends path to <base>
