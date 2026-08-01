"""Generic read-only FS result gateway (web.service_ui.results_api + config.result_roots).

Product-neutral: the gateway carries no directory/tool names — these tests use neutral fixtures.
The scan-synthesis, static-index.json override, and path containment are the security-relevant
pure pieces; the routes/auth are verified in the browser."""
from __future__ import annotations

import json
import os

import pytest
from fastapi import HTTPException

from web.service_ui import config
from web.service_ui.results_api import fs_scan_manifest, _safe_target


def test_result_roots_parsing(monkeypatch, tmp_path):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    monkeypatch.setenv("WB_RESULT_ROOTS", f"one={a}; two = {b} ,bad")
    roots = config.result_roots()
    assert set(roots) == {"one", "two"}
    assert roots["one"] == a.resolve()
    monkeypatch.delenv("WB_RESULT_ROOTS")
    assert config.result_roots() == {}


def test_fs_scan_manifest_classifies_by_extension(tmp_path):
    d = tmp_path / "someset"
    d.mkdir()
    (d / "envelope.kml").write_text("<kml/>")
    (d / "points.csv").write_text("lat,lon\n0,0\n")
    (d / "tool_specific.json").write_text("{}")   # .json is served but not a viewer item here
    (d / "footprint.png").write_bytes(b"\x89PNG")  # ignored (not a viewer format)

    m = fs_scan_manifest(d, "frs", "someset", generated="t")
    assert m["schema"] == "result-manifest/1"
    assert m["source"] == {"kind": "fs", "root": "frs", "rel": "someset"}
    by_id = {it["id"]: it for it in m["items"]}
    assert set(by_id) == {"envelope.kml", "points.csv"}       # png ignored; json not itemised
    assert by_id["envelope.kml"]["kind"] == "kml" and by_id["envelope.kml"]["role"] == "nominal"
    assert by_id["points.csv"]["kind"] == "csv" and by_id["points.csv"]["role"] == "track"
    assert by_id["envelope.kml"]["path"] == "envelope.kml"     # opaque relative to <base>
    assert by_id["points.csv"]["bytes"] > 0


def test_fs_scan_manifest_static_index_json_wins(tmp_path):
    d = tmp_path / "set"
    d.mkdir()
    (d / "a.kml").write_text("<kml/>")
    owner_manifest = {"schema": "result-manifest/1", "title": "owner",
                      "items": [{"id": "x", "kind": "kml", "path": "a.kml", "role": "envelope"}]}
    (d / "index.json").write_text(json.dumps(owner_manifest))
    m = fs_scan_manifest(d, "r", "set")
    assert m == owner_manifest      # served verbatim; roles/labels are the owner's, not synthesised


def test_fs_scan_manifest_ignores_non_manifest_index_json(tmp_path):
    """A dir may hold an unrelated index.json (not a viewer manifest); it must be ignored and the
    manifest synthesised instead (review: RocketEarth feedback #3)."""
    d = tmp_path / "set"
    d.mkdir()
    (d / "a.kml").write_text("<kml/>")
    (d / "index.json").write_text(json.dumps({"some": "tool config", "not": "a manifest"}))
    m = fs_scan_manifest(d, "r", "set")
    assert m["schema"] == "result-manifest/1"                 # synthesised, not the stray file
    assert [it["id"] for it in m["items"]] == ["a.kml"]


def test_fs_scan_manifest_ignores_symlinked_files(tmp_path):
    d = tmp_path / "set"; d.mkdir()
    (d / "real.kml").write_text("<kml/>")
    outside = tmp_path / "secret.kml"; outside.write_text("<kml/>")
    try:
        os.symlink(outside, d / "link.kml")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    ids = {it["id"] for it in fs_scan_manifest(d, "r", "set")["items"]}
    assert ids == {"real.kml"}      # symlinked file excluded


def test_safe_target_rejects_traversal_and_cases(tmp_path):
    root = tmp_path / "root"; (root / "ok").mkdir(parents=True)
    assert _safe_target(root, "ok") == root / "ok"
    assert _safe_target(root, "") == root
    for bad in ["../etc", "a/../../etc", "cases/0", "sub/cases/x", "~/secret"]:
        with pytest.raises(HTTPException):
            _safe_target(root, bad)
