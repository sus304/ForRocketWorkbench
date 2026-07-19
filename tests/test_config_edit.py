"""Pure config-editor helpers (web.service_ui.config_edit) — flatten and type-preserving apply."""
from __future__ import annotations

from web.service_ui.config_edit import flatten_config, apply_edits


def test_flatten_nested_and_list():
    cfg = {"Wind Condition": {"Enable Wind": True, "Wind File Path": "wind.csv"},
           "Stages": [{"n": 1}, {"n": 2}], "Count": 100}
    flat = flatten_config(cfg)
    assert flat["Wind Condition.Enable Wind"] is True
    assert flat["Wind Condition.Wind File Path"] == "wind.csv"
    assert flat["Stages[0].n"] == 1 and flat["Stages[1].n"] == 2
    assert flat["Count"] == 100


def test_apply_preserves_types():
    cfg = {"Count": 100, "Ratio": 1.5, "Enable": False, "Name": "a",
           "Stages": [{"n": 1}]}
    edited = apply_edits(cfg, {
        "Count": "250", "Ratio": "2.0", "Enable": "true", "Name": "b", "Stages[0].n": "9",
    })
    assert edited["Count"] == 250 and isinstance(edited["Count"], int)
    assert edited["Ratio"] == 2.0 and isinstance(edited["Ratio"], float)
    assert edited["Enable"] is True
    assert edited["Name"] == "b"
    assert edited["Stages"][0]["n"] == 9
    # original unchanged
    assert cfg["Count"] == 100


def test_apply_ignores_unknown_paths():
    cfg = {"a": 1}
    assert apply_edits(cfg, {"b.c": 5, "a": "2"}) == {"a": 2}
