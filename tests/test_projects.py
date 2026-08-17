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


# ── per-file management (input data files) ───────────────────────────────────────

def _project(tmp_path):
    pj.upload_project(tmp_path, "rk", _zip(_valid_project_files()))
    return tmp_path


def test_list_files_reports_size_and_config_flag(tmp_path):
    _project(tmp_path)
    files = {f["path"]: f for f in pj.list_files(tmp_path, "rk")}
    assert "wind.csv" in files and files["wind.csv"]["size"] > 0
    assert files["config_solver.json"]["is_config"] is True
    assert files["wind.csv"]["is_config"] is False


def test_write_read_replace_delete_roundtrip(tmp_path):
    _project(tmp_path)
    pj.write_file(tmp_path, "rk", "thrust.csv", b"t,F\n0,100\n")
    assert pj.read_file(tmp_path, "rk", "thrust.csv") == b"t,F\n0,100\n"
    pj.write_file(tmp_path, "rk", "thrust.csv", b"t,F\n0,200\n")   # replace
    assert pj.read_file(tmp_path, "rk", "thrust.csv") == b"t,F\n0,200\n"
    pj.delete_file(tmp_path, "rk", "thrust.csv")
    with pytest.raises(pj.ProjectNotFound):
        pj.read_file(tmp_path, "rk", "thrust.csv")


def test_referenced_files_lists_config_paths(tmp_path):
    _project(tmp_path)
    refs = pj.referenced_files(tmp_path, "rk")
    assert "wind.csv" in refs and "winds.zip" in refs


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.csv", "~/secret",
                                 "sub/../../escape.csv", "work_trajectory/x.csv"])
def test_file_ops_reject_escapes(tmp_path, bad):
    _project(tmp_path)
    with pytest.raises(pj.ProjectError):
        pj.write_file(tmp_path, "rk", bad, b"x")
    with pytest.raises(pj.ProjectError):
        pj.read_file(tmp_path, "rk", bad)
    with pytest.raises(pj.ProjectError):
        pj.delete_file(tmp_path, "rk", bad)


def test_write_json_file_revalidates_relative_paths(tmp_path):
    """A .json upload with an absolute path field must be rejected — it would otherwise smuggle a
    server-FS read past the write_config guard (review N-6/R-A)."""
    _project(tmp_path)
    bad = json.dumps({"Wind Condition": {"Wind File Path": "/etc/passwd"}}).encode()
    with pytest.raises(pj.ProjectError):
        pj.write_file(tmp_path, "rk", "config_solver.json", bad)
    good = json.dumps({"Wind Condition": {"Wind File Path": "wind.csv"}}).encode()
    pj.write_file(tmp_path, "rk", "config_solver.json", good)  # relative path ok
    # non-JSON bytes into a .json target are rejected as invalid config
    with pytest.raises(pj.ProjectError):
        pj.write_file(tmp_path, "rk", "config_solver.json", b"not json")


def test_write_file_size_cap(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(pj, "MAX_FILE_BYTES", 8)
    with pytest.raises(pj.ProjectError):
        pj.write_file(tmp_path, "rk", "big.csv", b"0123456789")


def test_file_ops_missing_project(tmp_path):
    with pytest.raises(pj.ProjectNotFound):
        pj.list_files(tmp_path, "nope")
    with pytest.raises(pj.ProjectNotFound):
        pj.write_file(tmp_path, "nope", "a.csv", b"x")


# ── config templates (sample-valued base files) ──────────────────────────────────

def test_templates_come_from_the_example_project():
    """The shipped example project is the template source, so the base files stay in step with the
    solver schema without a second copy to maintain."""
    names = pj.list_templates()
    assert "config_montecarlo.json" in names
    assert "config_solver.json" in names
    assert all(n.endswith(".json") for n in names)   # data CSVs are not boilerplate


def test_add_template_fills_a_missing_config(tmp_path):
    pj.create_project(tmp_path, "rk")
    res = pj.add_template(tmp_path, "rk", "config_montecarlo.json")
    assert res["file"] == "config_montecarlo.json"
    cfg = pj.read_config(tmp_path, "rk")
    assert cfg["files"]["config_montecarlo.json"]["MonteCarlo Case Count"] > 0
    assert cfg["etag"] == res["etag"]


def test_add_template_never_overwrites(tmp_path):
    _project(tmp_path)
    before = pj.read_config(tmp_path, "rk")["files"]["config_solver.json"]
    with pytest.raises(pj.ProjectExists):
        pj.add_template(tmp_path, "rk", "config_solver.json")
    assert pj.read_config(tmp_path, "rk")["files"]["config_solver.json"] == before


def test_add_template_rejects_unknown_and_escaping_names(tmp_path):
    pj.create_project(tmp_path, "rk")
    for bad in ("nope.json", "wind.csv", "../evil.json", "/etc/passwd"):
        with pytest.raises(pj.ProjectError):
            pj.add_template(tmp_path, "rk", bad)


def test_add_template_missing_project(tmp_path):
    with pytest.raises(pj.ProjectNotFound):
        pj.add_template(tmp_path, "nope", "config_solver.json")


def test_add_template_rejects_absolute_path_in_template(tmp_path, monkeypatch):
    """A template is still config entering the trusted store: an absolute wind path in it must be
    refused exactly like an upload would be."""
    tpl = tmp_path / "tpl"
    tpl.mkdir()
    (tpl / "config_solver.json").write_text(
        json.dumps({"Wind Condition": {"Wind File Path": "/etc/wind.csv"}}))
    monkeypatch.setenv("WB_TEMPLATE_DIR", str(tpl))
    pj.create_project(tmp_path, "rk")
    with pytest.raises(pj.ProjectError):
        pj.add_template(tmp_path, "rk", "config_solver.json")
    assert not (Path(tmp_path) / "projects" / "rk" / "config_solver.json").exists()
