"""R2 (result-retrieval design §4.1 / compute_server_design §13-4): the Monte Carlo nominal
case (case 0) must use the nominal wind, not a dispersion sample.

runner_montecarlo pins case 0 to the nominal value for every error parameter (CA, thrust, xcg,
moi, poi, scalars). Wind was the exception: when wind dispersion is enabled the wind file list is
shuffled and case 0 got wind_files[0] like any other case, so `select=nominal` would surface a
random-wind trajectory as "the nominal" in reports, maps and 3D. This test locks case 0 to the
nominal wind (solver_config's Wind File Path) while other cases keep drawing dispersion samples.

Binary-free: the case-config generation runs, but the solver execution
(_execute_montecarlo_cases) is monkeypatched to a no-op, so we only inspect the generated
per-case configs and staged files in cases/.
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


def _setup_wind_dispersion_project(project: Path, case_count: int) -> list[str]:
    """Build a winds.zip of distinct dispersion files and enable wind dispersion in the MC
    config. Returns the dispersion wind basenames. The nominal wind (wind.csv) stays as the
    solver config's Wind File Path and is deliberately NOT one of the dispersion files."""
    nominal = (project / "wind.csv").read_text()
    dispersion_names = [f"wind_{i}.csv" for i in range(case_count)]
    winds_dir = project / "winds_src"
    winds_dir.mkdir()
    for i, name in enumerate(dispersion_names):
        # distinct content per file so a mix-up would be detectable; format mirrors wind.csv
        (winds_dir / name).write_text(nominal)
    zip_path = project / "winds.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in dispersion_names:
            zf.write(winds_dir / name, arcname=f"winds/{name}")

    mc_path = project / "config_montecarlo.json"
    mc = json.loads(mc_path.read_text())
    mc["MonteCarlo Case Count"] = case_count
    mc["Output All Case Logs"] = True
    mc["Error Parameters"]["Wind"]["Enable"] = True
    mc["Error Parameters"]["Wind"]["Wind Files Zip Path"] = str(zip_path)
    mc_path.write_text(json.dumps(mc, indent=4))
    return dispersion_names


def _case_wind(work_dir: Path, case_num: int) -> str:
    cfg = json.loads((work_dir / "cases" / f"{case_num}_solver_config.json").read_text())
    return cfg["Wind Condition"]["Wind File Path"]


def test_case0_uses_nominal_wind_others_use_dispersion(tmp_path, projects_dir, monkeypatch):
    project = copy_example(projects_dir, tmp_path / "example")
    case_count = 4
    dispersion_names = _setup_wind_dispersion_project(project, case_count)

    # Generate case configs only; skip the solver execution (no ForRocket binary needed).
    monkeypatch.setattr(runner_montecarlo, "_execute_montecarlo_cases",
                        lambda *a, **k: None)
    with chdir(str(project)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")

    work_dir = next(project.glob("work_montecarlo*"))

    # Case 0 references the nominal wind by basename, and that file is staged into cases/.
    assert _case_wind(work_dir, 0) == "wind.csv"
    assert (work_dir / "cases" / "wind.csv").is_file()

    # Every other case draws a dispersion sample from the zip, never the nominal wind.
    for case_num in range(1, case_count):
        w = _case_wind(work_dir, case_num)
        assert w in dispersion_names, f"case {case_num} wind {w!r} not a dispersion file"
        assert w != "wind.csv"


def test_case0_falls_back_to_dispersion_when_no_nominal_wind(tmp_path, projects_dir, monkeypatch):
    """A wind-dispersion setup with no valid nominal wind (empty Wind File Path) must keep
    working: case 0 falls back to a dispersion sample rather than crashing."""
    project = copy_example(projects_dir, tmp_path / "example")
    case_count = 3
    dispersion_names = _setup_wind_dispersion_project(project, case_count)

    sc_path = project / "config_solver.json"
    sc = json.loads(sc_path.read_text())
    sc["Wind Condition"]["Wind File Path"] = ""  # no nominal wind available
    sc_path.write_text(json.dumps(sc, indent=4))

    monkeypatch.setattr(runner_montecarlo, "_execute_montecarlo_cases",
                        lambda *a, **k: None)
    with chdir(str(project)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")

    work_dir = next(project.glob("work_montecarlo*"))
    assert _case_wind(work_dir, 0) in dispersion_names
