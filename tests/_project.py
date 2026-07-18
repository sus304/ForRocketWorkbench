"""Helpers to build example-project copies for runner tests.

The tracked sample project (projects/example) ships with every aerodynamic coefficient in
*constant* mode and only Thrust + Wind in file mode. That is exactly the gap that let the
"file mode x non-varied input" bugs through (the X-C.P./CNa path was never exercised), so
file-mode coverage must be constructed programmatically rather than assumed from a project's
defaults. enable_all_file_inputs() flips every "Enable * File" flag on a copied example and
drops a dummy CSV for each, giving the self-containment guard a fully-populated config tree to
walk regardless of what the sample project happens to enable.
"""
import json
import shutil
from pathlib import Path

from runner_tool.json_api import ROCKET_FILE_INPUT_SPECS, ENGINE_FILE_INPUT_SPECS

_DUMMY_CSV = "a,b,c,d\n0,1,1,1\n10,1,1,1\n"


def copy_example(projects_dir, dst: Path) -> Path:
    """Copy projects/example into dst (a non-existent path) and return it.

    Excludes work_* output dirs: those are gitignored run outputs, and a projects/example
    polluted by a prior manual run would otherwise carry a stray work_trajectory into the copy,
    making make_unique_work_dir pick work_trajectory_01 and break the work-dir tests."""
    shutil.copytree(Path(projects_dir) / "example", dst,
                    ignore=shutil.ignore_patterns("work_*"))
    return dst


def _enable(cfg: dict, specs, project_dir: Path):
    """For each (enable_key, block_key, path_key) spec, set Enable=True, point the path at a
    per-key dummy CSV basename, and write that CSV into project_dir. Returns the cfg."""
    for enable_key, block_key, path_key in specs:
        cfg[enable_key] = True
        block = cfg.setdefault(block_key, {})
        fname = path_key.replace(" ", "_").replace(".", "").lower() + ".csv"
        block[path_key] = fname
        (project_dir / fname).write_text(_DUMMY_CSV)
    return cfg


def disable_parachute(project_dir: Path):
    """Turn off parachute opening in the example copy's sequence-of-event config.

    The sample project descends under a parachute, so each case produces both a ballistic and
    a 'decent' flight log and post_montecarlo writes ballistic_/decent_result_table.csv rather
    than a single result_table.csv. Tests that only exercise the stats-only discard/rebuild
    pipeline (not parachute logic) disable it to get the simpler one-log-per-case shape."""
    project_dir = Path(project_dir)
    stage = json.loads((project_dir / "param_list_stage1.json").read_text())
    soe_path = project_dir / stage["Sequence of Event File Path"]
    soe = json.loads(soe_path.read_text())
    soe["Enable Parachute Open"] = False
    soe["Enable Secondary Parachute Open"] = False
    soe_path.write_text(json.dumps(soe, indent=4))


def enable_all_file_inputs(project_dir: Path):
    """Enable every rocket/engine file input on the example copy at project_dir, writing a
    dummy CSV for each. Content is irrelevant: the self-containment guard only checks that
    references resolve inside the work dir, and runners only parse a file when its variation/
    error is active (which these tests leave off)."""
    project_dir = Path(project_dir)
    stage = json.loads((project_dir / "param_list_stage1.json").read_text())

    rocket_path = project_dir / stage["Rocket Configuration File Path"]
    rocket = json.loads(rocket_path.read_text())
    _enable(rocket, ROCKET_FILE_INPUT_SPECS, project_dir)
    rocket_path.write_text(json.dumps(rocket, indent=4))

    engine_path = project_dir / stage["Engine Configuration File Path"]
    engine = json.loads(engine_path.read_text())
    _enable(engine, ENGINE_FILE_INPUT_SPECS, project_dir)
    engine_path.write_text(json.dumps(engine, indent=4))
