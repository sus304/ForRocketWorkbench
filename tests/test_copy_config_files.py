"""
Unit tests for runner_tool.json_api.copy_config_files.

Verifies that:
  - stage/rocket/engine/soe config JSONs are always copied,
  - data files (CSVs etc.) referenced via "Enable * File" flags are copied iff enabled,
  - the wind file (which lives in solver_config, not stage config) is NOT copied,
  - a non-existent destination raises FileNotFoundError.

These tests don't require the ForRocket binary.
"""
import json
from pathlib import Path

import pytest

from runner_tool.json_api import copy_config_files


_DATA_FILES = [
    "attitude.csv", "xcg.csv", "moi.csv", "xcp.csv",
    "ca.csv", "ca_burnout.csv",
    "cna.csv", "cld.csv", "clp.csv", "cmq.csv", "cnr.csv",
    "poi_ixy.csv", "poi_ixz.csv", "poi_iyz.csv",
    "thrust.csv", "wind.csv",
]


def _write_json(path: Path, obj):
    path.write_text(json.dumps(obj))


def _build_project(
    root: Path,
    *,
    ca=True, moi=True, xcg=True, thrust=True, prog_attitude=True,
    xcp=True, cna=True, cld=True, clp=True, cmq=True, cnr=True, poi=True,
) -> dict:
    """Write a minimal but realistic config tree into `root`. Returns the solver dict."""
    solver = {
        "Model ID": "TEST",
        "Number of Stage": 1,
        "Stage1 Config File List": "stage1.json",
        "Wind Condition": {"Enable Wind": True, "Wind File Path": "wind.csv"},
    }
    stage = {
        "Rocket Configuration File Path": "rocket.json",
        "Engine Configuration File Path": "engine.json",
        "Sequence of Event File Path": "soe.json",
    }
    rocket = {
        "Enable Program Attitude": prog_attitude,
        "Program Attitude": {"File Path": "attitude.csv"},
        "Enable X-C.G. File": xcg,
        "X-C.G. File": {"X-C.G. File Path": "xcg.csv"},
        "Enable M.I. File": moi,
        "M.I. File": {"M.I. File Path": "moi.csv"},
        "Enable X-C.P. File": xcp,
        "X-C.P. File": {"X-C.P. File Path": "xcp.csv"},
        "Enable CA File": ca,
        "CA File": {"CA File Path": "ca.csv", "BurnOut CA File Path": "ca_burnout.csv"},
        "Enable CNa File": cna,
        "CNa File": {"CNa File Path": "cna.csv"},
        "Enable Cld File": cld,
        "Cld File": {"Cld File Path": "cld.csv"},
        "Enable Clp File": clp,
        "Clp File": {"Clp File Path": "clp.csv"},
        "Enable Cmq File": cmq,
        "Cmq File": {"Cmq File Path": "cmq.csv"},
        "Enable Cnr File": cnr,
        "Cnr File": {"Cnr File Path": "cnr.csv"},
        "Enable Product of Inertia File": poi,
        "Product of Inertia File": {
            "Ixy File Path": "poi_ixy.csv",
            "Ixz File Path": "poi_ixz.csv",
            "Iyz File Path": "poi_iyz.csv",
        },
    }
    engine = {
        "Enable Thrust File": thrust,
        "Thrust File": {"Thrust at vacuum File Path": "thrust.csv"},
    }
    soe = {}

    _write_json(root / "config_solver.json", solver)
    _write_json(root / "stage1.json", stage)
    _write_json(root / "rocket.json", rocket)
    _write_json(root / "engine.json", engine)
    _write_json(root / "soe.json", soe)

    for f in _DATA_FILES:
        (root / f).write_text("dummy\n0,0\n")

    return solver


@pytest.fixture
def project_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_always_copies_stage_rocket_engine_soe(project_dir):
    solver = _build_project(project_dir)
    dst = project_dir / "cases"
    dst.mkdir()

    copy_config_files(solver, str(dst))

    for f in ("stage1.json", "rocket.json", "engine.json", "soe.json"):
        assert (dst / f).is_file(), f"missing: {f}"


def test_copies_all_enabled_data_files(project_dir):
    solver = _build_project(project_dir)  # all enabled
    dst = project_dir / "cases"
    dst.mkdir()

    copy_config_files(solver, str(dst))

    expected = [
        "attitude.csv", "xcg.csv", "moi.csv", "xcp.csv",
        "ca.csv", "ca_burnout.csv",
        "cna.csv", "cld.csv", "clp.csv", "cmq.csv", "cnr.csv",
        "poi_ixy.csv", "poi_ixz.csv", "poi_iyz.csv",
        "thrust.csv",
    ]
    for f in expected:
        assert (dst / f).is_file(), f"missing: {f}"


def test_skips_disabled_data_files(project_dir):
    solver = _build_project(
        project_dir,
        ca=False, moi=False, xcg=False, thrust=False,
        prog_attitude=False, xcp=False, cna=False, cld=False, clp=False,
        cmq=False, cnr=False, poi=False,
    )
    dst = project_dir / "cases"
    dst.mkdir()

    copy_config_files(solver, str(dst))

    skipped = [f for f in _DATA_FILES if f != "wind.csv"]
    for f in skipped:
        assert not (dst / f).exists(), f"should not have been copied: {f}"


def test_does_not_copy_wind_file(project_dir):
    """Wind file is referenced from solver_config; copy_config_files only walks stage configs."""
    solver = _build_project(project_dir)
    dst = project_dir / "cases"
    dst.mkdir()

    copy_config_files(solver, str(dst))

    assert not (dst / "wind.csv").exists()


def test_missing_destination_raises(project_dir):
    solver = _build_project(project_dir)

    with pytest.raises(FileNotFoundError):
        copy_config_files(solver, str(project_dir / "does_not_exist"))


# (block_key, path_key) pairs copy_config_files reads from a rocket_param. Kept in lockstep
# with json_api.copy_config_files; the schema-consistency test below pins each path_key to the
# key actually present in the real example/param_rocket.json, so a typo here (or there) fails
# loudly instead of silently skipping the copy. Regression for the 'CldFile Path' bug, where
# both copy_config_files AND this file's fixture carried the same typo and masked each other.
_ROCKET_FILE_BLOCK_KEYS = [
    ("Program Attitude", "File Path"),
    ("X-C.G. File", "X-C.G. File Path"),
    ("M.I. File", "M.I. File Path"),
    ("X-C.P. File", "X-C.P. File Path"),
    ("CA File", "CA File Path"),
    ("CA File", "BurnOut CA File Path"),
    ("CNa File", "CNa File Path"),
    ("Cld File", "Cld File Path"),
    ("Clp File", "Clp File Path"),
    ("Cmq File", "Cmq File Path"),
    ("Cnr File", "Cnr File Path"),
    ("Product of Inertia File", "Ixy File Path"),
    ("Product of Inertia File", "Ixz File Path"),
    ("Product of Inertia File", "Iyz File Path"),
]

_EXAMPLE_ROCKET = Path(__file__).parent.parent / "projects" / "example" / "param_rocket.json"


@pytest.mark.skipif(not _EXAMPLE_ROCKET.is_file(), reason="example/param_rocket.json not present")
def test_copy_keys_match_real_example_schema():
    """Every (block, path) key copy_config_files reads must exist in the real example
    param_rocket.json. This catches the class of bug where a hand-written test fixture and
    copy_config_files share a typo'd key (e.g. 'CldFile Path') and validate each other while
    the real GUI-written config uses the correct key, so the copy silently feeds None to
    shutil.copy2 and crashes only in production."""
    rocket = json.loads(_EXAMPLE_ROCKET.read_text())
    missing = [
        (block, key)
        for block, key in _ROCKET_FILE_BLOCK_KEYS
        if block in rocket and key not in rocket[block]
    ]
    assert not missing, (
        "copy_config_files reads keys absent from the real example schema "
        f"(typo / schema drift): {missing}"
    )


def test_cld_file_mode_copies_with_real_world_key(project_dir):
    """Direct regression for the 'CldFile Path' bug: with Cld File mode enabled and the
    real-world key, the Cld file must actually be copied (previously crashed with
    TypeError because .get('CldFile Path') returned None)."""
    solver = _build_project(
        project_dir,
        ca=False, moi=False, xcg=False, thrust=False, prog_attitude=False,
        xcp=False, cna=False, cld=True, clp=False, cmq=False, cnr=False, poi=False,
    )
    dst = project_dir / "cases"
    dst.mkdir()

    copy_config_files(solver, str(dst))

    assert (dst / "cld.csv").is_file(), "Cld file mode enabled but cld.csv was not copied"
