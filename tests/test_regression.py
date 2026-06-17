"""
Regression tests: same input → same output (within tolerance).

Usage:
  # First run: generate golden files
  pytest tests/test_regression.py --update-golden

  # Subsequent runs: compare against golden
  pytest tests/test_regression.py
"""
import json
from typing import Dict
import pytest
from pathlib import Path

from tests.sim_runner import run_sim, extract_metrics

# Per-metric absolute tolerances.
# These cover floating-point non-determinism and minor platform differences,
# but will catch any meaningful change in simulation results.
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

CASES = [
    ("example", "example"),
]


@pytest.mark.parametrize("case_id,project_name", CASES)
def test_trajectory_regression(
    case_id, project_name, binary_path, projects_dir, golden_dir, update_golden
):
    df = run_sim(projects_dir / project_name, "config_solver.json", binary_path)
    actual = extract_metrics(df)

    golden_path = golden_dir / f"{case_id}.json"

    if update_golden:
        golden_path.write_text(json.dumps(actual, indent=2))
        pytest.skip(f"Golden updated: {golden_path.name}")

    if not golden_path.exists():
        pytest.skip(
            f"No golden file for '{case_id}'. Run: pytest --update-golden"
        )

    golden = json.loads(golden_path.read_text())

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
            f"Regression mismatch [{case_id}]:\n" + "\n".join(failures)
        )
