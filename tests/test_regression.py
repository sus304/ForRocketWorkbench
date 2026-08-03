"""
Regression tests: same solver + same input → same output (within tolerance).

The golden file records the **solver version** it was generated with. A golden is
only compared against a binary reporting that same version: ForRocket physics-model
changes legitimately move the trajectory (e.g. jet damping, added in the v4.4.2
cycle, shifts the projects/example landing point by ~39 m), so comparing across
solver versions produces a permanent, meaningless failure. On a version mismatch
the test skips and tells you to regenerate — see `.claude/commands/solver-bump.md`.

Usage:
  # Generate / refresh golden files for the detected binary
  pytest tests/test_regression.py --update-golden

  # Compare against golden
  pytest tests/test_regression.py
"""
import json
from typing import Dict
import pytest
from pathlib import Path

from tests.sim_runner import UNKNOWN_VERSION, binary_version, run_sim, extract_metrics

# Per-metric absolute tolerances.
# These cover floating-point non-determinism and minor platform differences,
# but will catch any meaningful change in simulation results.
#
# Note: apogee_time / apogee_downrange are read off the altitude-argmax row. Near a
# flat apogee with adaptive output sampling that row is ambiguous by seconds, so these
# two are brittle against solver-tolerance changes and are NOT evidence of trajectory
# accuracy — judge that by apogee_altitude and the landing point.
TOLERANCES: Dict[str, float] = {
    "apogee_altitude_m":        1.0,    # [m]
    "apogee_time_s":            0.1,    # [s]
    "apogee_downrange_m":       10.0,   # [m]
    "max_dynamic_pressure_kPa": 0.01,   # [kPa]
    "max_mach":                 0.001,
    "max_acc_body_G":           0.01,   # [G]
    "landing_downrange_m":      10.0,   # [m]
    "landing_lat_deg":          1e-5,   # [deg]
    "landing_lon_deg":          1e-5,   # [deg]
    "flight_duration_s":        0.1,    # [s]
}

# Key holding the generating solver version inside the golden JSON. Not a metric,
# so it is ignored by the tolerance loop below.
SOLVER_VERSION_KEY = "solver_version"

CASES = [
    ("example", "example"),
]


@pytest.mark.parametrize("case_id,project_name", CASES)
def test_trajectory_regression(
    case_id, project_name, binary_path, projects_dir, golden_dir, update_golden
):
    version = binary_version(binary_path)
    golden_path = golden_dir / f"{case_id}.json"

    if update_golden:
        df = run_sim(projects_dir / project_name, "config_solver.json", binary_path)
        actual = dict(extract_metrics(df))
        actual[SOLVER_VERSION_KEY] = version
        golden_path.write_text(json.dumps(actual, indent=2))
        pytest.skip(f"Golden updated for solver {version}: {golden_path.name}")

    if not golden_path.exists():
        pytest.skip(
            f"No golden file for '{case_id}'. Run: pytest --update-golden"
        )

    golden = json.loads(golden_path.read_text())
    golden_version = golden.get(SOLVER_VERSION_KEY)

    if golden_version != version:
        pytest.skip(
            f"Solver version mismatch [{case_id}]: golden was generated with "
            f"{golden_version or 'an unrecorded version'}, binary reports {version}. "
            f"If the new solver's output change is intended, regenerate: "
            f"pytest tests/test_regression.py --update-golden"
        )

    if version == UNKNOWN_VERSION:
        pytest.skip(
            f"Binary does not report a version ({binary_path}); cannot confirm it "
            f"matches the golden's provenance."
        )

    df = run_sim(projects_dir / project_name, "config_solver.json", binary_path)
    actual = extract_metrics(df)

    failures = []
    for key, tol in TOLERANCES.items():
        if key not in golden:
            continue
        diff = abs(actual.get(key, float("nan")) - golden[key])
        if diff > tol:
            failures.append(
                f"  {key}:\n"
                f"    actual={actual[key]:.6g}  golden={golden[key]:.6g}"
                f"  diff={diff:.4g}  tol={tol}"
            )

    if failures:
        raise AssertionError(
            f"Regression mismatch [{case_id}] on solver {version}:\n"
            + "\n".join(failures)
        )
