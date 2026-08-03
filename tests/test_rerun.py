"""Re-running a finished job with identical inputs (service.rerun).

The feature exists to verify a deploy — same case, new build — so the tests are mostly about the
guarantee that makes the comparison meaningful: the new job's inputs are byte-identical to the
source job's *staged* inputs, and the outputs the source left behind (its work_* directories) do
not come along. The rest covers the refusals: an active job, an imported job, and a job whose
inputs have been swept off disk.

No ForRocket binary is needed: the run dirs are built by hand and the worker never runs.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service import rerun
from service.api import create_app
from service.rerun import RerunConflict, RerunNotFound, RerunRejected
from service.store import COMPLETED, JobStore, QUEUED, RUNNING
from service.uploads import closure_hash, iter_closure_files
from service.worker import Worker

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


@pytest.fixture
def worker(tmp_path, store):
    return Worker(store, tmp_path / "data", python=sys.executable, poll=0.05)


@pytest.fixture
def api(store, worker):
    return TestClient(create_app(store, worker, TOKEN))


def finished_job(store, worker, mode="trajectory", with_work_dir=True, **kwargs):
    """A completed job with a realistic staged run dir: inputs at the top level, one in a
    subdirectory, and the work_* directory the finished run left behind."""
    job_id = store.create_preparing(mode=mode, model_name="ROCKET-A", **kwargs)
    run_dir = worker.run_dir_for(job_id)
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "config_solver.json").write_text(json.dumps({"Model ID": "ROCKET-A"}))
    (run_dir / "config_montecarlo.json").write_text(json.dumps({"MonteCarlo Case Count": 4}))
    (run_dir / "inputs" / "thrust.csv").write_text("Time,Thrust\n0,1000\n")

    result_dir = run_dir / "work_trajectory"
    if with_work_dir:
        result_dir.mkdir()
        (result_dir / "ROCKET-A_stage1_flight_log.csv").write_text("Time [s]\n0\n")
        (result_dir / "config_solver.json").write_text("{}")  # the run's own copy of its inputs

    store.set_input_hash(job_id, closure_hash(run_dir))
    store.mark_completed(job_id, result_dir=str(result_dir))
    return job_id


def relative_files(root: Path):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# ── the guarantee: identical inputs, no outputs ──────────────────────────────

def test_rerun_copies_inputs_verbatim(store, worker):
    src = finished_job(store, worker)
    new_id = rerun.rerun_job(store, worker, src)

    src_dir = worker.run_dir_for(src)
    new_dir = worker.run_dir_for(new_id)
    inputs = {"config_solver.json", "config_montecarlo.json", "inputs/thrust.csv"}
    assert relative_files(new_dir) == inputs
    for rel in inputs:
        assert (new_dir / rel).read_bytes() == (src_dir / rel).read_bytes()


def test_rerun_leaves_the_source_work_dir_behind(store, worker):
    src = finished_job(store, worker)
    new_id = rerun.rerun_job(store, worker, src)
    # The source's outputs are still there (it is kept for comparison) and were not copied.
    assert (worker.run_dir_for(src) / "work_trajectory").is_dir()
    assert not (worker.run_dir_for(new_id) / "work_trajectory").exists()


def test_rerun_input_hash_matches_the_source(store, worker):
    src = finished_job(store, worker)
    new_id = rerun.rerun_job(store, worker, src)
    src_hash = store.get(src).input_hash
    assert src_hash
    assert store.get(new_id).input_hash == src_hash


def test_rerun_backfills_a_source_hash_recorded_before_the_column_existed(store, worker):
    src = finished_job(store, worker)
    store.set_input_hash(src, "")
    new_id = rerun.rerun_job(store, worker, src)
    assert store.get(src).input_hash  # backfilled from the staged inputs
    assert store.get(src).input_hash == store.get(new_id).input_hash


def test_closure_hash_changes_when_an_input_changes(store, worker):
    src = finished_job(store, worker)
    run_dir = worker.run_dir_for(src)
    before = closure_hash(run_dir)
    (run_dir / "inputs" / "thrust.csv").write_text("Time,Thrust\n0,1001\n")
    assert closure_hash(run_dir) != before


def test_closure_hash_ignores_work_dirs(store, worker):
    """Otherwise the hash would depend on the run's own output and never match a re-run's."""
    src = finished_job(store, worker)
    run_dir = worker.run_dir_for(src)
    before = closure_hash(run_dir)
    (run_dir / "work_trajectory" / "extra_output.csv").write_text("x\n")
    assert closure_hash(run_dir) == before


# ── the new job's shape ──────────────────────────────────────────────────────

def test_rerun_is_a_new_queued_job_linked_to_the_source(store, worker):
    src = finished_job(store, worker, project="example", use_max_thread=True)
    new_id = rerun.rerun_job(store, worker, src)

    new = store.get(new_id)
    assert new_id != src
    assert new.status == QUEUED
    assert new.rerun_of == src
    assert new.mode == "trajectory"
    assert new.model_name == "ROCKET-A"
    assert new.project == "example"
    assert new.use_max_thread is True       # inherited
    assert new.code_version                  # stamped with the build that queued it
    assert store.get(src).status == COMPLETED  # source untouched


def test_rerun_can_override_max_thread(store, worker):
    src = finished_job(store, worker, mode="montecarlo", use_max_thread=True)
    new_id = rerun.rerun_job(store, worker, src, use_max_thread=False)
    assert store.get(new_id).use_max_thread is False


def test_rerun_memo_defaults_to_the_source_memo_tagged(store, worker):
    src = finished_job(store, worker, memo="baseline sweep")
    new_id = rerun.rerun_job(store, worker, src)
    assert store.get(new_id).memo == f"baseline sweep (rerun of #{src})"


def test_rerun_memo_can_be_given(store, worker):
    src = finished_job(store, worker, memo="baseline")
    new_id = rerun.rerun_job(store, worker, src, memo="after solver fix")
    assert store.get(new_id).memo == "after solver fix"


def test_default_memo_does_not_accrete_suffixes():
    """Re-running a re-run must not produce '... (rerun of #1) (rerun of #2)'."""
    assert rerun.default_memo("baseline (rerun of #1)", 2) == "baseline (rerun of #2)"
    assert rerun.default_memo("", 7) == "(rerun of #7)"
    assert rerun.default_memo(None, 7) == "(rerun of #7)"


# ── refusals ────────────────────────────────────────────────────────────────

def test_rerun_refuses_an_unknown_job(store, worker):
    with pytest.raises(RerunNotFound):
        rerun.rerun_job(store, worker, 999)


@pytest.mark.parametrize("status", [QUEUED, RUNNING])
def test_rerun_refuses_an_active_job(store, worker, status):
    src = finished_job(store, worker)
    store._update(src, status=status)
    with pytest.raises(RerunConflict):
        rerun.rerun_job(store, worker, src)


def test_rerun_refuses_an_imported_job(store, worker, tmp_path):
    """An imported job holds a copied result, not the inputs that produced it."""
    src = finished_job(store, worker, source_path=str(tmp_path / "elsewhere"))
    with pytest.raises(RerunRejected) as e:
        rerun.rerun_job(store, worker, src)
    assert not isinstance(e.value, RerunConflict)   # 422, not 409


def test_rerun_refuses_when_the_inputs_are_gone(store, worker):
    import shutil
    src = finished_job(store, worker)
    shutil.rmtree(worker.run_dir_for(src))
    with pytest.raises(RerunConflict):
        rerun.rerun_job(store, worker, src)


def test_rerun_refuses_a_run_dir_holding_only_outputs(store, worker):
    """A run dir swept down to its work dir has no inputs left to copy."""
    src = finished_job(store, worker)
    run_dir = worker.run_dir_for(src)
    for f in list(iter_closure_files(run_dir)):
        f.unlink()
    with pytest.raises(RerunConflict):
        rerun.rerun_job(store, worker, src)


# ── HTTP surface ─────────────────────────────────────────────────────────────

def test_api_rerun_returns_the_new_job(api, store, worker):
    src = finished_job(store, worker, memo="baseline")
    r = api.post(f"/jobs/{src}/rerun", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["rerun_of"] == src
    assert body["status"] == QUEUED
    assert body["input_hash"] == store.get(src).input_hash
    assert body["memo"] == f"baseline (rerun of #{src})"


def test_api_rerun_accepts_a_memo(api, store, worker):
    src = finished_job(store, worker)
    r = api.post(f"/jobs/{src}/rerun", headers=AUTH, data={"memo": "after v4.5.0"})
    assert r.json()["memo"] == "after v4.5.0"


def test_api_rerun_requires_a_token(api, store, worker):
    src = finished_job(store, worker)
    assert api.post(f"/jobs/{src}/rerun").status_code == 401


def test_api_rerun_status_codes(api, store, worker, tmp_path):
    assert api.post("/jobs/999/rerun", headers=AUTH).status_code == 404

    active = finished_job(store, worker)
    store._update(active, status=RUNNING)
    assert api.post(f"/jobs/{active}/rerun", headers=AUTH).status_code == 409

    imported = finished_job(store, worker, source_path=str(tmp_path / "elsewhere"))
    assert api.post(f"/jobs/{imported}/rerun", headers=AUTH).status_code == 422


def test_api_capability_can_rerun(api, store, worker, tmp_path):
    src = finished_job(store, worker)
    imported = finished_job(store, worker, source_path=str(tmp_path / "elsewhere"))
    by_id = {j["id"]: j for j in api.get("/jobs", headers=AUTH).json()["jobs"]}
    assert by_id[src]["capability"]["can_rerun"] is True
    assert by_id[imported]["capability"]["can_rerun"] is False


def test_health_reports_the_workbench_version(api):
    from version import workbench_version
    assert api.get("/health").json()["workbench_version"] == workbench_version()
