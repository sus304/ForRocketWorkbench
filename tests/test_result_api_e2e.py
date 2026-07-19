"""End-to-end result-API test through a real worker + ForRocket binary (design §10 step 9).

Submits a small Monte Carlo run, waits for completion, then drives the whole result path through
ServiceClient: meta -> cases (top-N) -> extract (decimated) -> plots (png). Skipped when the
binary is absent. The browser login flow (app_server) is verified manually; this covers the
service + client half of the E2E on loopback.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.store import JobStore
from service.worker import Worker
from service.api import create_app
from service.client import ServiceClient
from tests._project import copy_example

TOKEN = "e2e-token"


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


def _small_mc_project(projects_dir, dst: Path) -> Path:
    proj = copy_example(projects_dir, dst)
    mc_path = proj / "config_montecarlo.json"
    mc = json.loads(mc_path.read_text())
    mc["MonteCarlo Case Count"] = 6
    mc["Output All Case Logs"] = True
    mc_path.write_text(json.dumps(mc, indent=4))
    return proj


def test_result_api_end_to_end(binary_path, store, tmp_path, projects_dir):
    repo = Path(__file__).resolve().parent.parent
    proj = _small_mc_project(projects_dir, tmp_path / "example")
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(repo / "runner.py"), post_py=str(repo / "post.py"), poll=0.05)
    sc = ServiceClient("", TOKEN, session=TestClient(create_app(store, w, TOKEN)))
    w.start()
    try:
        jid = sc.submit(proj, "montecarlo")["id"]
        deadline = time.time() + 300
        while time.time() < deadline:
            if sc.status(jid)["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        assert sc.status(jid)["status"] == "completed"

        meta = sc.result_meta(jid)
        assert meta["case_count"] >= 1
        assert "flight" in meta["kinds"]

        # nominal resolves to case 0, then extract its stage1 log decimated
        cases = sc.result_cases(jid, "nominal")
        assert cases and cases[0]["case"] == 0
        phase = meta["phases"][0]
        ex = sc.extract(jid, "id:0", phase=phase, max_points=200)
        assert ex["logs"], "expected a flight log for case 0"
        assert ex["logs"][0]["n_points"] <= 200

        # a metric-ranked selection and a document image
        metric = "downrange_impact"
        if metric in meta.get("metrics_columns", []):
            top = sc.result_cases(jid, f"top:3:{metric}:{phase}")
            assert 1 <= len(top) <= 3
        png = sc.plot(jid, "dispersion", table=_dispersion_table(meta), axes="ne")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        w.stop()


def test_project_submit_end_to_end(binary_path, store, tmp_path, projects_dir):
    """UI-refresh main path E2E: upload a project to the store, submit a run by reference (no
    upload at submit), wait for completion, and read its result meta. Skipped without binary."""
    import os
    import zipfile as _zf
    repo = Path(__file__).resolve().parent.parent
    w = Worker(store, tmp_path / "data", python=sys.executable,
               runner_py=str(repo / "runner.py"), post_py=str(repo / "post.py"), poll=0.05)
    sc = ServiceClient("", TOKEN, session=TestClient(create_app(store, w, TOKEN)))
    # zip the example project
    buf = io.BytesIO()
    ex = projects_dir / "example"
    with _zf.ZipFile(buf, "w") as zf:
        for root, _d, files in os.walk(ex):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, ex)
                if rel.split(os.sep)[0].startswith("work_"):
                    continue
                zf.write(full, arcname=rel)
    sc.upload_project("ex", buf.getvalue())
    w.start()
    try:
        jid = sc.submit_project("ex", "trajectory")["id"]
        deadline = time.time() + 180
        while time.time() < deadline:
            if sc.status(jid)["status"] in ("completed", "failed"):
                break
            time.sleep(0.3)
        assert sc.status(jid)["status"] == "completed"
        assert sc.status(jid)["project"] == "ex"
        assert sc.result_meta(jid)["mode"] == "trajectory"
    finally:
        w.stop()


def _dispersion_table(meta) -> str:
    tables = meta.get("tables", [])
    for name in ("ballistic_result_table", "decent_result_table", "result_table"):
        if name in tables:
            return name
    return "result_table"
