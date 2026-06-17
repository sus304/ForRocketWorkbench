"""Shared self-containment guard for runner work directories.

A work_**** directory must be reproducible without projects/**: every input the solver
reads has to be copied into the work dir and referenced by a relative path that resolves
*inside* that dir. Two failure modes break this and both broke a real run:

  - an absolute path into projects/** (works on the author's machine, not reproducible), and
  - an enabled file reference that was never copied into the work dir (the X-C.P./CNa class
    of bug that made every sensitivity case fail with "Nominal case flight log not found").

The walker imports the file-input key specs from runner_tool.json_api (the SAME lists
copy_config_files uses), so the guard and the product code can't drift on key names.

Two entry points cover all four runners:
  - assert_config_self_contained(base_dir, solver_config_name): one config tree
    (trajectory writes a single work dir; area writes one solver config per case).
  - assert_cases_self_contained(cases_dir): every *_solver_config.json under cases/
    (montecarlo, sensitivity).
"""
import json
import os
from pathlib import Path

from runner_tool.json_api import ROCKET_FILE_INPUT_SPECS, ENGINE_FILE_INPUT_SPECS


def _check(base_dir: Path, path, origin, offenders):
    """Record an offender if `path` is absolute or does not resolve inside base_dir.
    Returns True when the path is usable (relative and present) so the caller can recurse."""
    if not path:
        return False
    if os.path.isabs(path):
        offenders.append((origin, path, "absolute path into projects/** (not reproducible)"))
        return False
    if not (base_dir / path).exists():
        offenders.append((origin, path, "enabled reference not copied into work dir"))
        return False
    return True


def _walk(base_dir: Path, solver_config_name: str, offenders, checked):
    solver = json.loads((base_dir / solver_config_name).read_text())

    wc = solver.get("Wind Condition", {})
    if wc.get("Enable Wind") and wc.get("Wind File Path"):
        checked.append(wc["Wind File Path"])
        _check(base_dir, wc["Wind File Path"], solver_config_name, offenders)

    for i in range(1, solver.get("Number of Stage", 1) + 1):
        stage_name = solver.get(f"Stage{i} Config File List")
        if not stage_name:
            continue
        checked.append(stage_name)
        if not _check(base_dir, stage_name, solver_config_name, offenders):
            continue
        stage = json.loads((base_dir / stage_name).read_text())

        rocket_name = stage.get("Rocket Configuration File Path")
        engine_name = stage.get("Engine Configuration File Path")
        soe_name = stage.get("Sequence of Event File Path")
        for nm in (rocket_name, engine_name, soe_name):
            if nm:
                checked.append(nm)
                _check(base_dir, nm, stage_name, offenders)

        if rocket_name and _check(base_dir, rocket_name, stage_name, offenders):
            rocket = json.loads((base_dir / rocket_name).read_text())
            for enable_key, block_key, path_key in ROCKET_FILE_INPUT_SPECS:
                if rocket.get(enable_key):
                    p = rocket.get(block_key, {}).get(path_key)
                    checked.append((rocket_name, path_key, p))
                    _check(base_dir, p, rocket_name, offenders)

        if engine_name and _check(base_dir, engine_name, stage_name, offenders):
            engine = json.loads((base_dir / engine_name).read_text())
            for enable_key, block_key, path_key in ENGINE_FILE_INPUT_SPECS:
                if engine.get(enable_key):
                    p = engine.get(block_key, {}).get(path_key)
                    checked.append((engine_name, path_key, p))
                    _check(base_dir, p, engine_name, offenders)


def assert_config_self_contained(base_dir, solver_config_name: str):
    """Assert one solver-config tree under base_dir references only inputs present inside it."""
    base_dir = Path(base_dir)
    offenders, checked = [], []
    _walk(base_dir, solver_config_name, offenders, checked)
    assert checked, (
        f"no references found walking {solver_config_name} in {base_dir} (test setup problem?)"
    )
    assert not offenders, "non-self-contained references:\n" + "\n".join(map(str, offenders))


def assert_cases_self_contained(cases_dir):
    """Assert every per-case solver config under cases_dir is self-contained."""
    cases_dir = Path(cases_dir)
    solver_cfgs = sorted(cases_dir.glob("*_solver_config.json"))
    assert solver_cfgs, f"no per-case *_solver_config.json found in {cases_dir}"
    for sc in solver_cfgs:
        assert_config_self_contained(cases_dir, sc.name)
