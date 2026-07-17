"""Engine work_dir ownership (design §4.1/§4.2).

The compute service must know a run's work_dir at start, not at completion, so it can
persist it and later resume MC deterministically. The minimal engine hook: run_* accepts a
pre-created work_dir and uses it verbatim (default None keeps the legacy self-creating
behaviour). These run the real ForRocket binary and skip without it.
"""
import json
from pathlib import Path

import pytest

from path_define import (
    chdir, make_unique_work_dir,
    runner_trajectory_directory, runner_montecarlo_directory,
)
from runner_tool.runner_trajectory import run_trajectory
from runner_tool.runner_montecarlo import run_montecarlo
from runner_tool.run_manifest import RunManifest
from tests._project import copy_example


@pytest.fixture
def project_copy(tmp_path, projects_dir) -> Path:
    return copy_example(projects_dir, tmp_path / "example")


def _disable_all_mc_errors(mc_cfg_path: Path, case_count: int):
    cfg = json.loads(mc_cfg_path.read_text())
    cfg["MonteCarlo Case Count"] = case_count
    cfg["Output All Case Logs"] = True
    for ep in cfg.get("Error Parameters", {}).values():
        if isinstance(ep, dict) and "Enable" in ep:
            ep["Enable"] = False
    mc_cfg_path.write_text(json.dumps(cfg))


def test_trajectory_uses_provided_work_dir(binary_path, project_copy):
    with chdir(str(project_copy)):
        wd = make_unique_work_dir(runner_trajectory_directory)  # service pre-creates it
        run_trajectory("config_solver.json", work_dir=wd)
    dirs = list(project_copy.glob("work_trajectory*"))
    assert len(dirs) == 1, "must reuse the provided dir, not create a second one"
    assert dirs[0].name == "work_trajectory"
    assert any(dirs[0].iterdir()), "outputs must land in the provided work_dir"


def test_trajectory_default_still_self_creates(binary_path, project_copy):
    with chdir(str(project_copy)):
        run_trajectory("config_solver.json")  # work_dir omitted -> legacy behaviour
    assert len(list(project_copy.glob("work_trajectory*"))) == 1


def test_montecarlo_uses_provided_work_dir(binary_path, project_copy):
    _disable_all_mc_errors(project_copy / "config_montecarlo.json", case_count=1)
    with chdir(str(project_copy)):
        wd = make_unique_work_dir(runner_montecarlo_directory)
        run_montecarlo("config_solver.json", "config_montecarlo.json", work_dir=wd)
    dirs = list(project_copy.glob("work_montecarlo*"))
    assert len(dirs) == 1, "must reuse the provided dir"
    assert (dirs[0] / "cases").is_dir()
    assert (dirs[0] / RunManifest.FILENAME).exists(), "resume manifest anchored in provided dir"
