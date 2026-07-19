"""HTTP tests for the remote result API routes (docs/result_retrieval_design.md §4-5, step 5).

Binary-free: a completed job is fabricated with a synthetic MC work_dir, then the result routes
are driven through the FastAPI TestClient. Auth, artifact-existence capability, and the
410/409/404/422 mapping are covered here; the pure resolution/rendering logic is tested in
test_results.py / test_plots.py.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.store import JobStore
from service.worker import Worker
from service.api import create_app

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_FLIGHT_HEADER = "Time [s],Altitude [m],Latitude [deg],Longitude [deg]"


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


@pytest.fixture
def worker(tmp_path, store):
    (tmp_path / "r.py").write_text("import sys; sys.exit(0)\n")
    (tmp_path / "p.py").write_text("import sys; sys.exit(0)\n")
    return Worker(store, tmp_path / "data", python=sys.executable,
                  runner_py=str(tmp_path / "r.py"), post_py=str(tmp_path / "p.py"), poll=0.05)


@pytest.fixture
def client(store, worker):
    return TestClient(create_app(store, worker, TOKEN))


def _flight(path: Path, n=5):
    rows = [_FLIGHT_HEADER]
    for i in range(n):
        rows.append(f"{i*0.5},{100+i},{35+i*0.01},{139+i*0.01}")
    path.write_text("\n".join(rows) + "\n")


def _fabricate_mc(store, worker):
    jid = store.create_preparing(mode="montecarlo")
    store.mark_queued(jid)
    run_dir = worker.run_dir_for(jid)
    run_dir.mkdir(parents=True)
    store.claim_next()
    wd = run_dir / "work_montecarlo"
    (wd / "cases").mkdir(parents=True)
    for c in range(4):
        _flight(wd / "cases" / f"{c}_stage1_flight_log.csv")
        _flight(wd / "cases" / f"{c}_ballistic_flight_log.csv")
    hdr = "case,maxQ,mach,time_apogee,altitude_apogee,vel_apogee,downrange_impact,lat_impact,lon_impact\n"
    (wd / "decent_result_table.csv").write_text(
        hdr + "".join(f"{c},5e4,1.5,20,3000,150,{1000*(c+1)},{35+c},139\n" for c in range(4)))
    (wd / "ballistic_result_table.csv").write_text(
        hdr + "".join(f"{c},5e4,1.5,20,3000,150,{5000-500*c},{36+c},140\n" for c in range(4)))
    store.set_work_dir(jid, str(wd.resolve()))
    store.mark_completed(jid, result_dir=str(wd.resolve()))
    return jid


def test_meta_and_capability(client, store, worker):
    jid = _fabricate_mc(store, worker)
    assert client.get(f"/jobs/{jid}", headers=AUTH).json()["capability"]["result_api"] is True
    r = client.get(f"/jobs/{jid}/result/meta", headers=AUTH)
    assert r.status_code == 200
    meta = r.json()
    assert set(meta["tables"]) == {"decent_result_table", "ballistic_result_table"}
    assert meta["case_count"] == 4


def test_result_routes_require_auth(client, store, worker):
    jid = _fabricate_mc(store, worker)
    assert client.get(f"/jobs/{jid}/result/meta").status_code == 401


def test_tables_and_cases(client, store, worker):
    jid = _fabricate_mc(store, worker)
    t = client.get(f"/jobs/{jid}/result/tables/ballistic_result_table", headers=AUTH).json()
    assert "downrange_impact" in t["columns"] and len(t["rows"]) == 4
    cases = client.get(f"/jobs/{jid}/result/cases",
                       params={"select": "top:2:downrange_impact:stage1"}, headers=AUTH).json()
    assert [c["case"] for c in cases["cases"]] == [3, 2]


def test_extract_json_csv_zip(client, store, worker):
    jid = _fabricate_mc(store, worker)
    j = client.get(f"/jobs/{jid}/result/extract",
                   params={"select": "id:0", "phase": "stage1", "columns": "Altitude [m]"},
                   headers=AUTH).json()
    assert j["logs"][0]["columns"] == ["Time [s]", "Altitude [m]"]

    csv = client.get(f"/jobs/{jid}/result/extract",
                     params={"select": "id:0", "phase": "stage1", "format": "csv"}, headers=AUTH)
    assert csv.status_code == 200 and "Time [s]" in csv.text

    # csv with a multi-log selection is rejected
    bad = client.get(f"/jobs/{jid}/result/extract",
                     params={"select": "id:0", "phase": "all", "format": "csv"}, headers=AUTH)
    assert bad.status_code == 422

    z = client.get(f"/jobs/{jid}/result/extract",
                   params={"select": "id:0,1", "phase": "stage1", "format": "zip"}, headers=AUTH)
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert len(names) == 2


def test_plots_png(client, store, worker):
    jid = _fabricate_mc(store, worker)
    r = client.get(f"/jobs/{jid}/result/plots/dispersion",
                   params={"table": "ballistic_result_table", "axes": "ne"}, headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_bad_metric_is_422(client, store, worker):
    jid = _fabricate_mc(store, worker)
    r = client.get(f"/jobs/{jid}/result/cases", params={"select": "top:2:nope"}, headers=AUTH)
    assert r.status_code == 422


def test_swept_workdir_is_410(client, store, worker):
    jid = _fabricate_mc(store, worker)
    import shutil
    shutil.rmtree(worker.run_dir_for(jid) / "work_montecarlo")  # simulate retention sweep
    r = client.get(f"/jobs/{jid}/result/meta", headers=AUTH)
    assert r.status_code == 410
    # capability now reflects the missing artifact
    assert client.get(f"/jobs/{jid}", headers=AUTH).json()["capability"]["result_api"] is False


def test_result_not_ready_is_409(client, store, worker):
    jid = store.create_preparing(mode="montecarlo")
    store.mark_queued(jid)
    r = client.get(f"/jobs/{jid}/result/meta", headers=AUTH)
    assert r.status_code == 409


def test_unknown_job_is_404(client):
    assert client.get("/jobs/9999/result/meta", headers=AUTH).status_code == 404


def test_kml_route(client, store, worker):
    jid = _fabricate_mc(store, worker)
    wd = worker.run_dir_for(jid) / "work_montecarlo"
    (wd / "decent_impact_points.kml").write_text("<kml>points</kml>")
    (wd / "decent_ellipse_impact_3sigma_envelop.kml").write_text("<kml>ellipse</kml>")
    meta = client.get(f"/jobs/{jid}/result/meta", headers=AUTH).json()
    assert "decent_points" in meta["kml"] and "decent_ellipse" in meta["kml"]
    r = client.get(f"/jobs/{jid}/result/kml", params={"name": "decent_ellipse"}, headers=AUTH)
    assert r.status_code == 200 and r.content == b"<kml>ellipse</kml>"
    assert client.get(f"/jobs/{jid}/result/kml",
                      params={"name": "nope"}, headers=AUTH).status_code == 422


def test_empty_token_fails_closed(store, worker):
    """An empty service token must reject every request, not authenticate 'Bearer ' (review Y15)."""
    c = TestClient(create_app(store, worker, ""))
    assert c.get("/jobs").status_code == 401
    assert c.get("/jobs", headers={"Authorization": "Bearer "}).status_code == 401
