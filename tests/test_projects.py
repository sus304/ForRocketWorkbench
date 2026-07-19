"""Project store (service.projects) — CRUD, ZIP-safe extract, path validation, atomic swap,
etag concurrency. Pure/filesystem, binary-free (docs/ui_refresh_design.md §3)."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from service import projects as pj


def _zip(files: dict, prefix: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(prefix + name, content)
    return buf.getvalue()


def _valid_project_files():
    return {
        "config_solver.json": json.dumps({"Wind Condition": {"Wind File Path": "wind.csv"}}),
        "config_montecarlo.json": json.dumps(
            {"Error Parameters": {"Wind": {"Wind Files Zip Path": "winds.zip"}}}),
        "wind.csv": "t,u,v\n0,0,0\n",
    }


def test_name_sanitize(tmp_path):
    with pytest.raises(pj.ProjectError):
        pj.project_dir(tmp_path, "../evil")
    with pytest.raises(pj.ProjectError):
        pj.project_dir(tmp_path, "a/b")
    assert pj.project_dir(tmp_path, "rocket-a").name == "rocket-a"


def test_create_copy_delete_list(tmp_path):
    pj.create_project(tmp_path, "p1")
    with pytest.raises(pj.ProjectExists):
        pj.create_project(tmp_path, "p1")
    pj.copy_project(tmp_path, "p1", "p2")
    with pytest.raises(pj.ProjectExists):
        pj.copy_project(tmp_path, "p1", "p2")
    names = {p["name"] for p in pj.list_projects(tmp_path)}
    assert names == {"p1", "p2"}
    pj.delete_project(tmp_path, "p2")
    assert {p["name"] for p in pj.list_projects(tmp_path)} == {"p1"}
    with pytest.raises(pj.ProjectNotFound):
        pj.delete_project(tmp_path, "p2")


def test_upload_and_download_roundtrip(tmp_path):
    pj.upload_project(tmp_path, "rk", _zip(_valid_project_files()))
    cfg = pj.read_config(tmp_path, "rk")
    assert "config_solver.json" in cfg["files"]
    blob = pj.download_project(tmp_path, "rk")
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert any(n.endswith("config_solver.json") for n in names)


def test_upload_descends_single_wrapper_dir(tmp_path):
    # OS "compress folder" wraps everything under one top dir.
    pj.upload_project(tmp_path, "rk", _zip(_valid_project_files(), prefix="rk/"))
    assert (pj.project_dir(tmp_path, "rk") / "config_solver.json").is_file()


def test_upload_rejects_zip_slip(tmp_path):
    with pytest.raises(pj.ProjectError):
        pj.safe_unzip(_zip({"../escape.txt": "x"}), tmp_path / "d")


def test_upload_rejects_absolute_wind_path(tmp_path):
    files = _valid_project_files()
    files["config_solver.json"] = json.dumps(
        {"Wind Condition": {"Wind File Path": "/etc/passwd"}})
    with pytest.raises(pj.ProjectError):
        pj.upload_project(tmp_path, "rk", _zip(files))


def test_upload_rejects_traversal_in_config_path(tmp_path):
    files = _valid_project_files()
    files["config_montecarlo.json"] = json.dumps(
        {"Error Parameters": {"Wind": {"Wind Files Zip Path": "../../secrets/winds.zip"}}})
    with pytest.raises(pj.ProjectError):
        pj.upload_project(tmp_path, "rk", _zip(files))


def test_upload_atomic_keeps_old_on_bad_update(tmp_path):
    pj.upload_project(tmp_path, "rk", _zip(_valid_project_files()))
    bad = _valid_project_files()
    bad["config_solver.json"] = json.dumps({"Wind Condition": {"Wind File Path": "/abs/path"}})
    with pytest.raises(pj.ProjectError):
        pj.upload_project(tmp_path, "rk", _zip(bad))
    # old good project survives
    assert (pj.project_dir(tmp_path, "rk") / "config_solver.json").is_file()


def test_write_config_etag_conflict(tmp_path):
    pj.upload_project(tmp_path, "rk", _zip(_valid_project_files()))
    cfg = pj.read_config(tmp_path, "rk")
    etag = cfg["etag"]
    files = cfg["files"]
    files["config_solver.json"]["Wind Condition"]["Wind File Path"] = "wind2.csv"
    pj.write_config(tmp_path, "rk", files, if_match=etag)          # ok
    with pytest.raises(pj.ProjectConflict):
        pj.write_config(tmp_path, "rk", files, if_match=etag)      # stale etag -> 409


def test_write_config_rejects_absolute_path(tmp_path):
    pj.upload_project(tmp_path, "rk", _zip(_valid_project_files()))
    cfg = pj.read_config(tmp_path, "rk")
    cfg["files"]["config_solver.json"]["Wind Condition"]["Wind File Path"] = "/etc/passwd"
    with pytest.raises(pj.ProjectError):
        pj.write_config(tmp_path, "rk", cfg["files"])
