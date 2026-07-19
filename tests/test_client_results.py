"""ServiceClient result-API methods (design §4-5). Drives the client against an in-process app
via the injected TestClient session, reusing the fabricated MC job from test_results_api.
"""
from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from service.api import create_app
from service.client import ServiceClient
from tests.test_results_api import (  # noqa: F401 — fixtures + helper reuse
    TOKEN, store, worker, _fabricate_mc,
)


def _client(store, worker) -> ServiceClient:
    return ServiceClient("", TOKEN, session=TestClient(create_app(store, worker, TOKEN)))


def test_meta_summary_table(store, worker):
    jid = _fabricate_mc(store, worker)
    sc = _client(store, worker)
    meta = sc.result_meta(jid)
    assert meta["case_count"] == 4
    tbl = sc.result_table(jid, "ballistic_result_table")
    assert "downrange_impact" in tbl["columns"]
    assert isinstance(sc.result_summary(jid), list)


def test_cases_and_extract_json(store, worker):
    jid = _fabricate_mc(store, worker)
    sc = _client(store, worker)
    cases = sc.result_cases(jid, "top:2:downrange_impact:stage1")
    assert [c["case"] for c in cases] == [3, 2]
    ex = sc.extract(jid, "id:0", phase="stage1", columns=["Altitude [m]"])
    assert ex["logs"][0]["columns"] == ["Time [s]", "Altitude [m]"]


def test_set_memo_roundtrip(store, worker):
    jid = _fabricate_mc(store, worker)
    sc = _client(store, worker)
    sc.set_memo(jid, "resonance ok")
    assert sc.status(jid)["memo"] == "resonance ok"


def test_extract_file_zip_and_plot_bytes(store, worker):
    jid = _fabricate_mc(store, worker)
    sc = _client(store, worker)
    blob = sc.extract_file(jid, "id:0,1", fmt="zip", phase="stage1")
    assert len(zipfile.ZipFile(io.BytesIO(blob)).namelist()) == 2
    png = sc.plot(jid, "dispersion", table="ballistic_result_table", axes="ne")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
