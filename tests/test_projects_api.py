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
