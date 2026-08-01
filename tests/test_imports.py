"""Importing an externally produced result directory into the job ledger (service.imports).

Covers mode detection, the inspect preconditions (mode / size / duplicate / inside-the-store /
symlink), and the full import: copy into the job store, post-processing of the copy, and a
completed job row whose result_dir is inside data_root so the existing result API accepts it.
No ForRocket binary is needed — the fixtures build a work dir by hand and post is a stub.
"""
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service import imports
from service.api import create_app
from service.imports import ImportRejected
from service.store import COMPLETED, JobStore
from service.worker import Worker

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# Stands in for post.py: creates the result_<model>/ directory post_trajectory would produce.
_STUB_POST = (
    "import glob,os,sys\n"
    "wd=sys.argv[-1]\n"
    "for f in glob.glob(os.path.join(wd,'*_flight_log.csv')):\n"
    "    d=os.path.join(wd,'result_'+os.path.basename(f).rsplit('_flight_log.csv',1)[0])\n"
    "    os.mkdir(d)\n"
    "    open(os.path.join(d,'_summary.txt'),'w').write('Apogee,1000 [m]\\n')\n"
)


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


@pytest.fixture
def worker(tmp_path, store):
    (tmp_path / "p.py").write_text(_STUB_POST)
    return Worker(store, tmp_path / "data", python=sys.executable,
                  post_py=str(tmp_path / "p.py"), poll=0.05)


def make_work_dir(base: Path, name: str = "work_trajectory", model: str = "ROCKET-A") -> Path:
    """A minimal stand-in for what runner.py leaves behind for a trajectory run: the flight log
    plus the self-contained copies of its inputs."""
    wd = base / name
    wd.mkdir(parents=True)
    (wd / f"{model}_stage1_flight_log.csv").write_text("Time [s],Altitude [m]\n0,0\n1,10\n")
    (wd / "config_solver.json").write_text(json.dumps({"Model ID": model}))
    (wd / f"{model}_Xcg.csv").write_text("Time,Xcg_fromTail\n0,1.0\n")
    return wd


# ── mode detection ───────────────────────────────────────────────────────────

def test_detect_mode_by_dir_prefix(tmp_path):
    assert imports.detect_mode(make_work_dir(tmp_path)) == "trajectory"
    assert imports.detect_mode(tmp_path / "work_montecarlo_2") == "montecarlo"
    assert imports.detect_mode(tmp_path / "work_area") == "area"


def test_detect_mode_by_marker_when_renamed(tmp_path):
    d = tmp_path / "renamed"
    d.mkdir()
    (d / "result_table.csv").write_text("case,apogee\n0,1\n")
    assert imports.detect_mode(d) == "montecarlo"

    s = tmp_path / "renamed_s"
    s.mkdir()
    (s / "sensitivity_results.csv").write_text("param,value\n")
    assert imports.detect_mode(s) == "sensitivity"


def test_detect_mode_falls_back_to_bare_flight_log(tmp_path):
    d = tmp_path / "renamed_t"
    d.mkdir()
    (d / "ROCKET-A_stage1_flight_log.csv").write_text("Time [s]\n0\n")
    assert imports.detect_mode(d) == "trajectory"


def test_detect_mode_none_for_input_dir_and_for_cases(tmp_path):
    """A case dir holds only inputs (its log lives in the work dir below it), and a renamed
    multi-case dir must not be mistaken for a single trajectory."""
    d = tmp_path / "case_dir"
    d.mkdir()
    (d / "config_solver.json").write_text("{}")
    (d / "ROCKET-A_Xcg.csv").write_text("Time,Xcg_fromTail\n0,1.0\n")
    assert imports.detect_mode(d) is None

    m = tmp_path / "renamed_mc"
    m.mkdir()
    (m / "cases").mkdir()
    (m / "ROCKET-A_stage1_flight_log.csv").write_text("Time [s]\n0\n")
    assert imports.detect_mode(m) is None


def test_is_posted(tmp_path):
    wd = make_work_dir(tmp_path)
    assert not imports.is_posted(wd)
    (wd / "result_ROCKET-A_stage1").mkdir()
    assert imports.is_posted(wd)


# ── inspect ──────────────────────────────────────────────────────────────────

def test_inspect_accepts_a_trajectory_work_dir(tmp_path, store, worker):
    wd = make_work_dir(tmp_path / "src")
    info = imports.inspect(str(wd), store=store, data_root=worker.data_root)
    assert info["ok"] and not info["error"]
    assert info["mode"] == "trajectory"
    assert info["model_id"] == "ROCKET-A"
    assert info["posted"] is False
    assert info["files"] == 3 and info["bytes"] > 0
    assert info["modified"]


def test_inspect_rejects_montecarlo(tmp_path, store, worker):
    wd = tmp_path / "src" / "work_montecarlo"
    wd.mkdir(parents=True)
    info = imports.inspect(str(wd), store=store, data_root=worker.data_root)
    assert not info["ok"]
    assert "not importable" in info["error"]


def test_inspect_rejects_unidentifiable_dir(tmp_path, store, worker):
    d = tmp_path / "src" / "plain"
    d.mkdir(parents=True)
    (d / "notes.txt").write_text("hi")
    info = imports.inspect(str(d), store=store, data_root=worker.data_root)
    assert not info["ok"] and "could not identify" in info["error"]


def test_inspect_rejects_missing_and_symlink(tmp_path, store, worker):
    info = imports.inspect(str(tmp_path / "nope"), store=store, data_root=worker.data_root)
    assert not info["ok"] and "not a directory" in info["error"]

    wd = make_work_dir(tmp_path / "src")
    link = tmp_path / "link_to_wd"
    os.symlink(wd, link)
    info = imports.inspect(str(link), store=store, data_root=worker.data_root)
    assert not info["ok"] and "symlink" in info["error"]


def test_inspect_rejects_a_path_already_inside_the_store(tmp_path, store, worker):
    """Re-importing a job's own work dir would duplicate it under a second id."""
    wd = make_work_dir(worker.run_dir_for(7))
    info = imports.inspect(str(wd), store=store, data_root=worker.data_root)
    assert not info["ok"] and "inside the job store" in info["error"]


def test_inspect_rejects_oversize(tmp_path, store, worker, monkeypatch):
    wd = make_work_dir(tmp_path / "src")
    monkeypatch.setattr(imports, "MAX_IMPORT_BYTES", 10)
    info = imports.inspect(str(wd), store=store, data_root=worker.data_root)
    assert not info["ok"] and "too large" in info["error"]


def test_measure_stops_early_past_the_cap(tmp_path):
    wd = make_work_dir(tmp_path / "src")
    total, count = imports.measure(wd, max_bytes=1)
    assert total > 1 and count >= 1  # returned without walking the whole tree


# ── import ───────────────────────────────────────────────────────────────────

def test_import_copies_posts_and_registers(tmp_path, store, worker):
    wd = make_work_dir(tmp_path / "src")
    job_id = imports.import_result(store, worker, str(wd), memo="spin sweep A1")

    job = store.get(job_id)
    assert job.status == COMPLETED
    assert job.mode == "trajectory"
    assert job.model_name == "ROCKET-A"
    assert job.memo == "spin sweep A1"
    assert job.source_path == str(wd.resolve())

    dest = Path(job.result_dir)
    assert dest == worker.run_dir_for(job_id) / "work_trajectory"
    assert dest.is_dir()
    # the copy is complete and post ran on it
    assert (dest / "ROCKET-A_stage1_flight_log.csv").is_file()
    assert (dest / "config_solver.json").is_file()
    assert (dest / "result_ROCKET-A_stage1" / "_summary.txt").is_file()
    # the source is untouched — post wrote only into our copy
    assert not imports.is_posted(wd)


def test_import_dates_the_job_by_the_source_run(tmp_path, store, worker):
    wd = make_work_dir(tmp_path / "src")
    old = 1_600_000_000  # 2020-09-13
    os.utime(wd, (old, old))
    job = store.get(imports.import_result(store, worker, str(wd)))
    assert job.finished_at.year == 2020
    assert job.started_at == job.finished_at


def test_import_skips_post_when_already_posted(tmp_path, store, worker):
    """post_trajectory does an unconditional mkdir, so re-posting would raise FileExistsError."""
    wd = make_work_dir(tmp_path / "src")
    (wd / "result_ROCKET-A_stage1").mkdir()
    (wd / "result_ROCKET-A_stage1" / "_summary.txt").write_text("Apogee,999 [m]\n")

    job = store.get(imports.import_result(store, worker, str(wd)))
    assert job.status == COMPLETED
    # the pre-existing post output came along untouched (the stub would have written 1000)
    assert '999' in (Path(job.result_dir) / "result_ROCKET-A_stage1" / "_summary.txt").read_text()


def test_import_refuses_a_duplicate(tmp_path, store, worker):
    wd = make_work_dir(tmp_path / "src")
    first = imports.import_result(store, worker, str(wd))
    with pytest.raises(ImportRejected, match=f"#{first}"):
        imports.import_result(store, worker, str(wd))


def test_a_failed_attempt_does_not_lock_the_source_out(tmp_path, store, worker):
    """A transient post failure must not make the directory permanently un-importable."""
    (tmp_path / "p.py").write_text("import sys; sys.exit(3)")
    wd = make_work_dir(tmp_path / "src")
    with pytest.raises(ImportRejected):
        imports.import_result(store, worker, str(wd))

    (tmp_path / "p.py").write_text(_STUB_POST)  # post fixed; retry must be allowed
    job = store.get(imports.import_result(store, worker, str(wd)))
    assert job.status == COMPLETED


def test_import_does_not_copy_symlinks(tmp_path, store, worker):
    wd = make_work_dir(tmp_path / "src")
    secret = tmp_path / "outside.txt"
    secret.write_text("should not be copied")
    os.symlink(secret, wd / "link.csv")

    job = store.get(imports.import_result(store, worker, str(wd)))
    assert not (Path(job.result_dir) / "link.csv").exists()


def test_import_failure_leaves_no_partial_job_dir(tmp_path, store, worker, monkeypatch):
    wd = make_work_dir(tmp_path / "src")

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(imports.shutil, "copytree", boom)

    with pytest.raises(ImportRejected, match="copy failed"):
        imports.import_result(store, worker, str(wd))
    jobs = store.list()
    assert len(jobs) == 1 and jobs[0].status == "failed"
    assert not worker.run_dir_for(jobs[0].id).exists()


def test_import_marks_the_job_failed_when_post_fails(tmp_path, store, worker):
    (tmp_path / "p.py").write_text("import sys; sys.exit(3)")
    wd = make_work_dir(tmp_path / "src")
    with pytest.raises(ImportRejected, match="post-processing failed"):
        imports.import_result(store, worker, str(wd))
    assert store.list()[0].status == "failed"


# ── HTTP surface ─────────────────────────────────────────────────────────────

@pytest.fixture
def api(store, worker):
    return TestClient(create_app(store, worker, TOKEN))


def test_import_endpoints_require_auth(api, tmp_path):
    assert api.get("/imports/inspect", params={"path": str(tmp_path)}).status_code == 401
    assert api.post("/imports", data={"path": str(tmp_path)}).status_code == 401


def test_inspect_endpoint_reports_unsuitable_without_erroring(api, tmp_path):
    r = api.get("/imports/inspect", params={"path": str(tmp_path / "nope")}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_import_endpoint_creates_a_result_api_ready_job(api, tmp_path, worker):
    wd = make_work_dir(tmp_path / "src")
    r = api.post("/imports", data={"path": str(wd), "memo": "sweep"}, headers=AUTH)
    assert r.status_code == 200
    job = r.json()
    assert job["status"] == COMPLETED
    assert job["source_path"] == str(wd.resolve())
    assert job["capability"]["result_api"] is True

    # result_dir is inside data_root, so the existing result API serves it (no boundary change)
    meta = api.get(f"/jobs/{job['id']}/result/meta", headers=AUTH)
    assert meta.status_code == 200
    assert meta.json()["mode"] == "trajectory"


def test_import_endpoint_rejects_unimportable_with_422(api, tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    (d / "notes.txt").write_text("hi")
    r = api.post("/imports", data={"path": str(d)}, headers=AUTH)
    assert r.status_code == 422


def test_deleting_an_imported_job_leaves_the_source(api, tmp_path, worker):
    wd = make_work_dir(tmp_path / "src")
    job = api.post("/imports", data={"path": str(wd)}, headers=AUTH).json()
    assert api.delete(f"/jobs/{job['id']}", headers=AUTH).status_code == 200
    assert not worker.run_dir_for(job["id"]).exists()
    assert wd.is_dir() and (wd / "config_solver.json").is_file()
