"""Cross-mode self-containment guard for all four runners.

A work_**** directory must be reproducible without projects/**: every input the solver reads
has to be copied into the work dir and referenced by a relative path resolving inside it.
sensitivity originally broke this (file-mode X-C.P./CNa left as project-relative paths -> every
case failed with "Nominal case flight log not found"); montecarlo leaked os.path.abspath into
non-varied inputs. These tests pin the invariant for trajectory, area, montecarlo AND
sensitivity at once.

Crucially, every rocket/engine file input is enabled programmatically (enable_all_file_inputs):
the sample project ships those coefficients in constant mode, so without this the "file mode x
non-varied input" path — the exact blind spot behind both bugs — would still go untested.

Binary-independent: run_solver (and trajectory's binary staging) are stubbed; only the
copy/staging logic runs, which is what determines self-containment.
"""
import json
from pathlib import Path

import pytest

from path_define import chdir
from tests._project import copy_example, enable_all_file_inputs, disable_parachute
from tests._selfcontained import assert_cases_self_contained, assert_config_self_contained


@pytest.fixture
def full_file_mode_project(tmp_path, projects_dir) -> Path:
    """Sample-project copy with every rocket/engine file input enabled (dummy CSVs)."""
    proj = copy_example(projects_dir, tmp_path / "example")
    enable_all_file_inputs(proj)
    return proj


@pytest.fixture(autouse=True)
def _stub_solver(monkeypatch):
    """No-op solver + no-op binary staging, so the runners exercise copy/staging without a
    ForRocket build (and without parsing the dummy CSVs as a real flight)."""
    monkeypatch.setattr("runner_tool.runner_single.run_solver", lambda *a, **k: None)
    monkeypatch.setattr("runner_tool.runner_trajectory.copy_solver_binary", lambda *a, **k: "ForRocket")
    monkeypatch.setattr("runner_tool.runner_trajectory.clean_solver_binary", lambda *a, **k: None)


def _new_work_dir(project_dir: Path, glob: str) -> Path:
    dirs = list(project_dir.glob(glob))
    assert len(dirs) == 1, f"expected exactly one {glob} dir, got {dirs}"
    return dirs[0]


def test_trajectory_workdir_is_self_contained(full_file_mode_project):
    """trajectory writes a single work dir (no cases/). The verbatim-copied solver config and
    every input it transitively references must resolve inside that dir by relative path."""
    from runner_tool.runner_trajectory import run_trajectory

    disable_parachute(full_file_mode_project)  # avoid run_single's ballistic-config side-run
    with chdir(str(full_file_mode_project)):
        run_trajectory("config_solver.json")

    work_dir = _new_work_dir(full_file_mode_project, "work_trajectory*")
    assert_config_self_contained(work_dir, "config_solver.json")


def test_area_cases_are_self_contained(full_file_mode_project):
    """area writes one solver config per wind case directly into the work dir, plus generated
    wind files. Every case config tree must be self-contained."""
    from runner_tool.runner_area import run_area

    area_cfg = {
        "Law Wind": {
            "Wind Characteristic Coefficient": 0.143,
            "Reference Height [m]": 20000.0,
            "Reference Wind Speed Lower Limit [m/s]": 1.0,
            "Reference Wind Speed Upper Limit [m/s]": 2.0,
            "Reference Wind Speed Step [m/s]": 1.0,
            "Wind Direction Lower Limit [deg]": 0.0,
            "Wind Direction Upper Limit [deg]": 0.0,
            "Wind Direction Step [deg]": 10.0,
        }
    }
    (full_file_mode_project / "config_area.json").write_text(json.dumps(area_cfg))

    with chdir(str(full_file_mode_project)):
        run_area("config_solver.json", "config_area.json")

    work_dir = _new_work_dir(full_file_mode_project, "work_area*")
    case_cfgs = sorted(work_dir.glob("config_solver_*.json"))
    assert case_cfgs, f"no per-case solver configs in {work_dir}"
    for sc in case_cfgs:
        assert_config_self_contained(work_dir, sc.name)


def test_montecarlo_cases_self_contained_all_file_inputs(full_file_mode_project):
    """montecarlo cases/ must be self-contained with every file input enabled and no errors
    (the non-varied copy path that previously leaked absolute projects/** references)."""
    from runner_tool.runner_montecarlo import run_montecarlo

    cfg = json.loads((full_file_mode_project / "config_montecarlo.json").read_text())
    cfg["MonteCarlo Case Count"] = 2
    cfg["Output All Case Logs"] = True
    for ep in cfg.get("Error Parameters", {}).values():
        if isinstance(ep, dict) and "Enable" in ep:
            ep["Enable"] = False
    (full_file_mode_project / "config_montecarlo.json").write_text(json.dumps(cfg))

    with chdir(str(full_file_mode_project)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")

    work_dir = _new_work_dir(full_file_mode_project, "work_montecarlo*")
    assert_cases_self_contained(work_dir / "cases")


def test_sensitivity_cases_self_contained_all_file_inputs(full_file_mode_project):
    """sensitivity cases/ must be self-contained with every file input enabled, varying one
    scalar (the original regression: non-varied file-mode coefficients left unresolved)."""
    from runner_tool.runner_sensitivity import run_sensitivity

    sens_cfg = {
        "Sensitivity Parameters": [
            {"Name": "Mass Inert", "Variation Unit": "%", "Variations": [-5.0, 5.0]},
        ],
        "Sensitivity Calculation": {"Method": "two_point"},
    }
    (full_file_mode_project / "config_sensitivity.json").write_text(json.dumps(sens_cfg))

    with chdir(str(full_file_mode_project)):
        work_dir = run_sensitivity("config_solver.json", "config_sensitivity.json")

    assert_cases_self_contained(full_file_mode_project / Path(work_dir).name / "cases")
