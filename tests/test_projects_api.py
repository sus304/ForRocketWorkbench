"""HTTP tests for the projects API routes (docs/ui_refresh_design.md §3), driven through the
ServiceClient over an in-process app. Binary-free."""
from __future__ import annotations

import io
import json
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

from service.store import JobStore
from service.worker import Worker
from service.api import create_app
from service.client import ServiceClient

TOKEN = "proj-token"


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


@pytest.fixture
def worker(tmp_path, store):
    (tmp_path / "r.py").write_text("import sys;sys.exit(0)\n")
    (tmp_path / "p.py").write_text("import sys;sys.exit(0)\n")
    return Worker(store, tmp_path / "data", python=sys.executable,
                  runner_py=str(tmp_path / "r.py"), post_py=str(tmp_path / "p.py"), poll=0.05)


@pytest.fixture
def sc(store, worker):
    return ServiceClient("", TOKEN, session=TestClient(create_app(store, worker, TOKEN)))


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, c in files.items():
            zf.writestr(n, c)
    return buf.getvalue()


def _proj_files():
    return {"config_solver.json": json.dumps({"Wind Condition": {"Wind File Path": "wind.csv"}}),
            "wind.csv": "t\n0\n"}


def test_projects_crud_and_config(sc):
    sc.upload_project("rk", _zip(_proj_files()))
    assert "rk" in [p["name"] for p in sc.list_projects()]
    cfg = sc.get_project_config("rk")
    assert "config_solver.json" in cfg["files"]
    # edit + save with etag
    cfg["files"]["config_solver.json"]["Wind Condition"]["Wind File Path"] = "wind2.csv"
    sc.put_project_config("rk", cfg["files"], if_match=cfg["etag"])
    cfg2 = sc.get_project_config("rk")
    assert cfg2["files"]["config_solver.json"]["Wind Condition"]["Wind File Path"] == "wind2.csv"
    # copy + delete
    sc.copy_project("rk", "rk2")
    assert "rk2" in [p["name"] for p in sc.list_projects()]
    sc.delete_project("rk2")
    assert "rk2" not in [p["name"] for p in sc.list_projects()]


def test_projects_download(sc):
    sc.upload_project("rk", _zip(_proj_files()))
    blob = sc.download_project("rk")
    assert any(n.endswith("config_solver.json") for n in zipfile.ZipFile(io.BytesIO(blob)).namelist())


def test_projects_routes_require_auth(store, worker):
    c = TestClient(create_app(store, worker, TOKEN))
    assert c.get("/projects").status_code == 401


def test_upload_absolute_path_rejected_422(sc):
    files = _proj_files()
    files["config_solver.json"] = json.dumps({"Wind Condition": {"Wind File Path": "/etc/passwd"}})
    with pytest.raises(Exception):  # ServiceClient raises on 422
        sc.upload_project("rk", _zip(files))


def _zip_dir(d):
    import os
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for root, _dirs, files in os.walk(d):
            for f in files:
                full = os.path.join(root, f)
                if any(p.startswith("work_") for p in os.path.relpath(full, d).split(os.sep)):
                    continue
                zf.write(full, arcname=os.path.relpath(full, d))
    return buf.getvalue()


def test_submit_from_stored_project_stages_and_queues(sc, store, worker, projects_dir):
    # Upload the tracked example project, then submit a trajectory run by reference (no worker
    # started): the closure must be packed from the store and staged into the run_dir before the
    # job is queued (review N-2), and the job records its source project.
    sc.upload_project("ex", _zip_dir(str(projects_dir / "example")))
    res = sc.submit_project("ex", "trajectory")
    jid = res["id"]
    assert sc.status(jid)["status"] in ("queued", "preparing", "running", "completed")
    assert sc.status(jid)["project"] == "ex"
    run_dir = worker.run_dir_for(jid)
    assert (run_dir / "config_solver.json").is_file()  # closure staged (confirmed snapshot)


def test_config_etag_conflict_409(store, worker):
    app = create_app(store, worker, TOKEN)
    c = TestClient(app)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    c.post("/projects/rk/upload", headers=auth,
           files={"payload": ("p.zip", _zip(_proj_files()), "application/zip")})
    cfg = c.get("/projects/rk/config", headers=auth).json()
    body = {"files": json.dumps(cfg["files"]), "if_match": "stale-etag"}
    r = c.put("/projects/rk/config", headers=auth, data=body)
    assert r.status_code == 409


def test_project_files_crud_over_http(sc):
    sc.upload_project("rk", _zip(_proj_files()))
    listing = sc.list_project_files("rk")
    paths = {f["path"] for f in listing["files"]}
    assert {"config_solver.json", "wind.csv"} <= paths
    assert "wind.csv" in listing["referenced"]

    # add a new input file, read it back, then replace and delete
    sc.upload_project_file("rk", "thrust.csv", b"t,F\n0,100\n")
    assert sc.download_project_file("rk", "thrust.csv") == b"t,F\n0,100\n"
    sc.upload_project_file("rk", "thrust.csv", b"t,F\n0,200\n")
    assert sc.download_project_file("rk", "thrust.csv") == b"t,F\n0,200\n"
    sc.delete_project_file("rk", "thrust.csv")
    assert "thrust.csv" not in {f["path"] for f in sc.list_project_files("rk")["files"]}


def test_project_file_escape_rejected_over_http(sc):
    sc.upload_project("rk", _zip(_proj_files()))
    with pytest.raises(Exception):  # 422 -> raise_for_status
        sc.upload_project_file("rk", "../escape.csv", b"x")
    with pytest.raises(Exception):
        sc.download_project_file("rk", "/etc/passwd")


def test_project_file_json_upload_revalidated_over_http(sc):
    sc.upload_project("rk", _zip(_proj_files()))
    bad = json.dumps({"Wind Condition": {"Wind File Path": "/etc/passwd"}}).encode()
    with pytest.raises(Exception):
        sc.upload_project_file("rk", "config_solver.json", bad)
