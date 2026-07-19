"""Typed project-editor forms (web.service_ui.config_forms).

Two layers, matching the repo convention (pure logic unit-tested; NiceGUI bodies otherwise manual):
  1. Pure helpers — parsing, case-count estimates, sensitivity validation — tested directly.
  2. collect() round-trips — the forms build headlessly (NiceGUI widgets can be created and read
     without a browser), so we lock the property that matters for save: the form is idempotent on
     its own output (save → reopen → save must not drift or drop keys). Idempotency (not equality
     with the source) is the right invariant because the first pass legitimately migrates a few
     legacy keys (e.g. it synthesises "C.G. Offset").
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from web.service_ui import config_forms as cf

EXAMPLE = Path(__file__).resolve().parent.parent / "projects" / "example"


# ── pure helpers ────────────────────────────────────────────────────────────────

def test_parse_num_list_keeps_int_and_float():
    assert cf.parse_num_list("-10, -5, 5, 10") == [-10, -5, 5, 10]
    assert cf.parse_num_list("1.5; 2.0, 3") == [1.5, 2.0, 3]
    assert cf.parse_num_list("1e-3, x, 4") == [1e-3, 4]
    assert cf.parse_num_list("") == []


def test_opts_with_prepends_missing_value():
    assert cf.opts_with("Thrust", ["CA", "CNa"]) == ["Thrust", "CA", "CNa"]
    assert cf.opts_with("CA", ["CA", "CNa"]) == ["CA", "CNa"]
    assert cf.opts_with(None, ["CA"]) == ["CA"]


def test_area_case_count():
    # 2..10 step 2 -> 5 speeds; 0..350 step 10 -> 36 dirs
    assert cf.area_case_count(2, 10, 2, 0, 350, 10) == 5 * 36


def test_sensitivity_case_count():
    params = [{"Variations": [-10, -5, 5, 10]}, {"Variations": [-5, 5]}]
    assert cf.sensitivity_case_count(params) == 1 + 6


def test_validate_sensitivity_flags_problems():
    params = [
        {"Name": "Thrust", "Variation Unit": "%", "Variations": [-5, 5]},          # ok
        {"Name": "CA", "Variation Unit": "N", "Variations": [1]},                   # too few + file-mode
        {"Name": "Bogus", "Variation Unit": "%", "Variations": [-1, 1]},           # unknown name
        {"Name": "Coupled", "Variation Unit": "%", "Variations": [-1, 1], "Effects": []},  # no effects
    ]
    msgs = cf.validate_sensitivity(params, thrust_fm=False, ca_fm=True, poi_fm=False)
    joined = " | ".join(msgs)
    assert "needs at least 2 Variations" in joined
    assert "file mode" in joined and "CA" in joined
    assert "unknown parameter" in joined
    assert "has no Effects" in joined


def test_validate_sensitivity_clean():
    params = [{"Name": "Thrust", "Variation Unit": "%", "Variations": [-5, 5]}]
    assert cf.validate_sensitivity(params) == []


# ── collect() round-trips (headless NiceGUI) ────────────────────────────────────

def _load(fname):
    return json.loads((EXAMPLE / fname).read_text())


@pytest.fixture
def ui_column():
    """A NiceGUI container to build a form inside (created outside a browser)."""
    from nicegui import ui
    return ui.column()


FORM_FILES = [
    "config_solver.json",
    "param_list_stage1.json",
    "param_rocket.json",
    "param_engine.json",
    "sequence_of_event.json",
    "config_area.json",
    "config_montecarlo.json",
    "config_sensitivity.json",
]


@pytest.mark.parametrize("fname", FORM_FILES)
def test_form_collect_is_idempotent(fname):
    """Build the form from the example config, collect once, then build again from that output and
    collect again — the two collected configs must be identical (no key drift, no lost fields)."""
    from nicegui import ui
    data = _load(fname)
    siblings = {f: _load(f) for f in FORM_FILES if (EXAMPLE / f).exists()}

    c1 = cf.build_form(fname, data, ui.column(), siblings=siblings)()
    c2 = cf.build_form(fname, c1, ui.column(), siblings={**siblings, fname: c1})()
    assert c1 == c2, f"{fname}: form is not idempotent on its own output"


def test_solver_form_preserves_unknown_keys():
    from nicegui import ui
    data = _load("config_solver.json")
    data["_custom_marker"] = {"keep": 1}
    out = cf.build_form("config_solver.json", data, ui.column())()
    assert out.get("_custom_marker") == {"keep": 1}


def test_montecarlo_form_preserves_error_parameters():
    from nicegui import ui
    data = _load("config_montecarlo.json")
    out = cf.build_form("config_montecarlo.json", data, ui.column())()
    # every registry parameter is present with an Enable flag, and the case count survives
    assert out["MonteCarlo Case Count"] == data["MonteCarlo Case Count"]
    for key, _unit, _wind in cf._MC_ERROR_PARAMS_DEF:
        assert key in out["Error Parameters"]
        assert "Enable" in out["Error Parameters"][key]


def test_sensitivity_form_preserves_params():
    from nicegui import ui
    data = _load("config_sensitivity.json")
    siblings = {f: _load(f) for f in FORM_FILES if (EXAMPLE / f).exists()}
    out = cf.build_form("config_sensitivity.json", data, ui.column(), siblings=siblings)()
    src_names = {p.get("Name") for p in data.get("Sensitivity Parameters", [])}
    out_names = {p.get("Name") for p in out.get("Sensitivity Parameters", [])}
    assert src_names <= out_names or not src_names
    assert out["Sensitivity Calculation"]["Method"] in cf._SENS_METHODS
