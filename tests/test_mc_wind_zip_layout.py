"""Monte Carlo wind files zip: the run must not depend on how the zip was packed.

The runner used to derive the unpacked directory from the zip's own basename
(`winds_dir = splitext(basename(zip))[0]`), so a wind.zip holding its CSVs at the top level --
what you get by selecting the files and compressing them -- died on
"FileNotFoundError: <work_dir>/wind" before the first case ran. The same mismatch hit every
zip service.uploads bundles into a job closure, because that path renames it to a fixed
winds_input.zip while the folder inside keeps its original name.

These tests run case generation only: _execute_montecarlo_cases is monkeypatched away, so no
ForRocket binary is needed and the assertions read the generated cases/ tree directly.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from path_define import chdir
from runner_tool import runner_montecarlo
from runner_tool.runner_montecarlo import run_montecarlo
from tests._project import copy_example

_WIND_CSV = "altitude,speed,direction\n0,5,90\n1000,10,90\n"


def _write_zip(path: Path, arcnames: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for arc in arcnames:
            zf.writestr(arc, _WIND_CSV)


def _enable_wind_dispersion(project: Path, zip_name: str, case_count: int) -> None:
    mc_path = project / "config_montecarlo.json"
    mc = json.loads(mc_path.read_text())
    mc["MonteCarlo Case Count"] = case_count
    mc["Error Parameters"]["Wind"]["Enable"] = True
    mc["Error Parameters"]["Wind"]["Wind Files Zip Path"] = zip_name
    mc_path.write_text(json.dumps(mc, indent=4))


def _run(project: Path, monkeypatch) -> Path:
    monkeypatch.setattr(runner_montecarlo, "_execute_montecarlo_cases", lambda *a, **k: None)
    with chdir(str(project)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")
    return next(project.glob("work_montecarlo*"))


def _case_wind(work_dir: Path, case_num: int) -> str:
    cfg = json.loads((work_dir / "cases" / f"{case_num}_solver_config.json").read_text())
    return cfg["Wind Condition"]["Wind File Path"]


# (zip filename, entries inside it) -- every layout must produce the same run.
_LAYOUTS = [
    # CSVs at the top level, zip name unrelated to any folder: the reported failure.
    ("wind.zip", ["wind_0.csv", "wind_1.csv", "wind_2.csv"]),
    # One wrapper folder whose name differs from the zip's.
    ("wind.zip", ["gpv_2026/wind_0.csv", "gpv_2026/wind_1.csv", "gpv_2026/wind_2.csv"]),
    # The layout that happened to match the old basename rule, kept as a regression guard.
    ("winds.zip", ["winds/wind_0.csv", "winds/wind_1.csv", "winds/wind_2.csv"]),
    # Nested deeper than one level.
    ("wind.zip", ["a/b/wind_0.csv", "a/b/wind_1.csv", "a/b/wind_2.csv"]),
    # The fixed name service.uploads bundles an external zip under, folder name unchanged.
    ("winds_input.zip", ["winds/wind_0.csv", "winds/wind_1.csv", "winds/wind_2.csv"]),
]


@pytest.mark.parametrize("zip_name,arcnames", _LAYOUTS,
                         ids=["flat", "wrapper-dir", "dir-matches-zip", "nested", "bundled-name"])
def test_every_zip_layout_stages_its_wind_files(tmp_path, projects_dir, monkeypatch,
                                                zip_name, arcnames):
    project = copy_example(projects_dir, tmp_path / "example")
    _write_zip(project / zip_name, arcnames)
    case_count = 4  # > the 3 wind files, so the extra_* top-up path runs too
    _enable_wind_dispersion(project, zip_name, case_count)

    work_dir = _run(project, monkeypatch)

    staged = {f.name for f in (work_dir / "winds").iterdir()}
    assert {Path(a).name for a in arcnames} <= staged
    # Case 0 takes the nominal wind; the rest draw from the zip and are staged into cases/.
    assert _case_wind(work_dir, 0) == "wind.csv"
    for case_num in range(1, case_count):
        w = _case_wind(work_dir, case_num)
        assert w in staged, f"case {case_num} wind {w!r} was not staged from the zip"
        assert (work_dir / "cases" / w).is_file()


def test_junk_and_non_csv_members_are_not_used_as_wind_files(tmp_path, projects_dir, monkeypatch):
    """A memo next to the CSVs (or macOS/Windows metadata) must not be handed to the solver as a
    wind profile -- os.listdir used to return them all indiscriminately."""
    project = copy_example(projects_dir, tmp_path / "example")
    with zipfile.ZipFile(project / "wind.zip", "w") as zf:
        for name in ["wind_0.csv", "wind_1.csv", "wind_2.csv"]:
            zf.writestr(name, _WIND_CSV)
        zf.writestr("readme.txt", "GPV 2026-08 \n")
        zf.writestr("__MACOSX/._wind_0.csv", "\0")
        zf.writestr(".DS_Store", "\0")
    case_count = 3
    _enable_wind_dispersion(project, "wind.zip", case_count)

    work_dir = _run(project, monkeypatch)

    used = {_case_wind(work_dir, c) for c in range(1, case_count)}
    assert used <= {"wind_0.csv", "wind_1.csv", "wind_2.csv"}
    assert not (work_dir / "winds" / "readme.txt").exists()
    assert not (work_dir / "winds" / ".DS_Store").exists()


def test_repeated_basenames_across_subfolders_do_not_collide(tmp_path, projects_dir, monkeypatch):
    """Cases are staged by basename, so a zip holding the same filename in two folders must get
    distinct staged names instead of overwriting one with the other."""
    project = copy_example(projects_dir, tmp_path / "example")
    _write_zip(project / "wind.zip", ["day1/wind.csv", "day2/wind.csv", "day3/wind.csv"])
    case_count = 4
    _enable_wind_dispersion(project, "wind.zip", case_count)

    work_dir = _run(project, monkeypatch)

    staged = sorted(f.name for f in (work_dir / "winds").iterdir())
    assert len([n for n in staged if not n.startswith("extra_")]) == 3
    assert len(set(staged)) == len(staged)


def test_empty_zip_fails_with_a_message_naming_the_zip(tmp_path, projects_dir, monkeypatch):
    project = copy_example(projects_dir, tmp_path / "example")
    with zipfile.ZipFile(project / "wind.zip", "w"):
        pass
    _enable_wind_dispersion(project, "wind.zip", 3)

    with pytest.raises(FileNotFoundError, match="no wind files found in wind.zip"):
        _run(project, monkeypatch)
