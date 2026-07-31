"""Pure manifest builder for the embedded 3D viewer (web.service_ui.results_api). The streaming
routes are manual/e2e; here we lock the product-neutral manifest shape and role mapping."""
from __future__ import annotations

from web.service_ui.results_api import build_job_manifest, kml_role


def test_kml_role_mapping():
    # bare kinds
    assert kml_role("trajectory") == "nominal"
    assert kml_role("iip") == "iip"
    assert kml_role("ellipse") == "ellipse"
    # phase-qualified (trajectory jobs) and scenario-qualified (MC) both classify by kind token
    assert kml_role("stage1_trajectory") == "nominal"
    assert kml_role("ballistic_trajectory") == "nominal"
    assert kml_role("stage1_iip") == "iip"       # the bug: this used to fall through to nominal
    assert kml_role("decent_points") == "points"
    assert kml_role("ballistic_envelope") == "envelope"
    assert kml_role("decent_ellipse") == "ellipse"


def test_build_job_manifest_trajectory_phases():
    status = {"id": 3, "mode": "trajectory", "project": "ROCKET-A"}
    # a real trajectory job has stage1 + ballistic phase KML
    meta = {"mode": "trajectory",
            "kml": ["stage1_trajectory", "stage1_iip", "ballistic_trajectory", "ballistic_iip"],
            "kinds": ["flight"]}
    m = build_job_manifest(3, status, meta, generated="2026-07-31T20:30:00")
    assert m["schema"] == "result-manifest/1"
    assert m["source"] == {"kind": "job", "id": 3, "mode": "trajectory"}
    assert m["title"] == "ROCKET-A（job 3）"
    ids = [it["id"] for it in m["items"]]
    assert ids == ["stage1_trajectory", "stage1_iip", "ballistic_trajectory", "ballistic_iip", "flight_log"]
    by_id = {it["id"]: it for it in m["items"]}
    assert by_id["stage1_trajectory"]["role"] == "nominal"
    assert by_id["stage1_iip"]["role"] == "iip"           # not misclassified as nominal
    assert by_id["ballistic_iip"]["name"] == "ballistic IIP 軌跡"
    assert by_id["stage1_trajectory"]["name"] == "stage1 飛行経路"
    assert by_id["stage1_trajectory"]["path"] == "kml/stage1_trajectory"
    assert m["items"][-1]["kind"] == "csv" and m["items"][-1]["role"] == "track"


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
