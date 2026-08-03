"""
Sensitivity analysis tests.

Unit tests  (no binary): calculation math, config parsing, output structure.
Integration tests (binary required): end-to-end run on the sample project config,
    verifying physical sign of sensitivities.
"""
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from runner_tool.runner_sensitivity import _compute_param_value, _get_nominal, run_sensitivity
from post_tool.post_sensitivity import post_sensitivity
from tests._selfcontained import assert_cases_self_contained
from tests._project import copy_example

_REPO_ROOT = Path(__file__).parent.parent
_SOLVER_CFG = "config_solver.json"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for mock work_dir (no binary needed)
# ──────────────────────────────────────────────────────────────────────────────

def _write_sensitivity_config(work_dir: Path, sens_params: list, method: str = "two_point"):
    cfg = {
        "Sensitivity Parameters": sens_params,
        "Sensitivity Calculation": {"Method": method},
    }
    (work_dir / "sensitivity_config.json").write_text(json.dumps(cfg))


def _write_case_list(work_dir: Path, rows: list):
    """rows: list of (case_num, param_name, variation, unit, nominal, param_value[, effects_detail])."""
    header = "case,param_name,variation,variation_unit,nominal_value,param_value,effects_detail"
    def _row_str(r):
        if len(r) == 6:
            return ",".join(str(x) for x in r) + ","
        return ",".join(str(x) for x in r)
    lines = [header] + [_row_str(r) for r in rows]
    (work_dir / "sensitivity_case_list.csv").write_text("\n".join(lines) + "\n")


def _write_mock_flight_log(cases_dir: Path, case_num: int, apogee_m: float):
    fname = cases_dir / f"{case_num}_mock_stage1_flight_log.csv"
    pd.DataFrame({"Altitude [m]": [0.0, apogee_m * 0.5, apogee_m, apogee_m * 0.5, 0.0]}).to_csv(
        fname, index=False
    )


def _setup_mock_workdir(tmp_path: Path, nominal_mass: float, nominal_alt: float,
                        variations: list, unit: str, alt_per_pct: float,
                        method: str = "two_point", ref_vars: list = None) -> Path:
    """
    Build a self-contained mock work_dir for a single 'Mass Inert' sensitivity test.

    alt_per_pct: altitude change per 1% of nominal_mass.
    """
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    # sensitivity_config.json
    sp = {"Name": "Mass Inert", "Variation Unit": unit, "Variations": variations}
    if ref_vars is not None:
        sp["Reference Variations"] = ref_vars
    _write_sensitivity_config(tmp_path, [sp], method)

    # sensitivity_case_list.csv
    rows = [(0, "nominal", 0.0, "%", "", "")]
    for i, var in enumerate(variations, start=1):
        new_val = _compute_param_value(nominal_mass, var, unit)
        rows.append((i, "Mass Inert", var, unit, nominal_mass, new_val))
    _write_case_list(tmp_path, rows)

    # mock flight logs: compute altitude for each case
    _write_mock_flight_log(cases_dir, 0, nominal_alt)
    for i, var in enumerate(variations, start=1):
        pct = var if unit == "%" else (var / nominal_mass * 100.0)
        _write_mock_flight_log(cases_dir, i, nominal_alt + pct * alt_per_pct)

    return tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests: _compute_param_value
# ──────────────────────────────────────────────────────────────────────────────

def test_compute_percent_positive():
    assert _compute_param_value(100.0, 5.0, "%") == pytest.approx(105.0)

def test_compute_percent_negative():
    assert _compute_param_value(100.0, -5.0, "%") == pytest.approx(95.0)

def test_compute_percent_zero():
    assert _compute_param_value(100.0, 0.0, "%") == pytest.approx(100.0)

def test_compute_absolute_positive():
    assert _compute_param_value(150.0, 10.0, "kg") == pytest.approx(160.0)

def test_compute_absolute_negative():
    assert _compute_param_value(150.0, -10.0, "kg") == pytest.approx(140.0)

def test_compute_absolute_deg():
    assert _compute_param_value(85.0, -3.0, "deg") == pytest.approx(82.0)

def test_compute_scale_negative_absolute():
    """scale=-1 inverts the variation direction (residual propellant pattern)."""
    assert _compute_param_value(10.5, 2.0, "kg", scale=-1.0) == pytest.approx(8.5)

def test_compute_scale_half_percent():
    """scale=0.5 halves the percentage effect."""
    assert _compute_param_value(100.0, 10.0, "%", scale=0.5) == pytest.approx(105.0)

def test_compute_scale_default_unchanged():
    """Default scale=1.0 must reproduce original behaviour."""
    assert _compute_param_value(100.0, 5.0, "%") == pytest.approx(
        _compute_param_value(100.0, 5.0, "%", scale=1.0))


def _setup_coupled_workdir(tmp_path: Path, nominal_prop: float, nominal_inert: float,
                           nominal_alt: float, variations: list) -> Path:
    """
    Mock work_dir for 'Residual Propellant' coupled sensitivity.
    variation=+ΔM → PropMass -ΔM, Inert +ΔM (total wet mass conserved).
    Altitude response: alt = nominal - 50*ΔM.
    """
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    sp = {
        "Name": "Residual Propellant",
        "Variation Unit": "kg",
        "Variations": variations,
        "Effects": [
            {"Parameter": "Propellant Mass", "Scale": -1.0},
            {"Parameter": "Mass Inert",      "Scale":  1.0},
        ],
    }
    _write_sensitivity_config(tmp_path, [sp])

    rows = [(0, "nominal", 0.0, "%", "", "")]
    for i, var in enumerate(variations, start=1):
        prop_new  = nominal_prop  - var
        inert_new = nominal_inert + var
        detail = (f"Propellant Mass: {nominal_prop:.4g}→{prop_new:.4g}; "
                  f"Mass Inert: {nominal_inert:.4g}→{inert_new:.4g}")
        rows.append((i, "Residual Propellant", var, "kg", 0.0, var, detail))
    _write_case_list(tmp_path, rows)

    _write_mock_flight_log(cases_dir, 0, nominal_alt)
    for i, var in enumerate(variations, start=1):
        _write_mock_flight_log(cases_dir, i, nominal_alt - 50.0 * var)

    return tmp_path


def test_coupled_sensitivity_m_per_unit(tmp_path):
    """Residual propellant: sensitivity [m/unit] must be -50 m per kg of residual."""
    work_dir = _setup_coupled_workdir(tmp_path, 10.5, 3.2, 10_000.0, [-2.0, -1.0, 1.0, 2.0])
    post_sensitivity(str(work_dir))
    row = pd.read_csv(work_dir / "sensitivity_results.csv").iloc[0]
    assert row["sensitivity [m/unit]"] == pytest.approx(-50.0, rel=1e-4)


def test_coupled_sensitivity_m_per_pct_is_nan(tmp_path):
    """Coupled absolute param has nominal_value=0, so sensitivity [m/%] must be NaN."""
    work_dir = _setup_coupled_workdir(tmp_path, 10.5, 3.2, 10_000.0, [-2.0, 2.0])
    post_sensitivity(str(work_dir))
    row = pd.read_csv(work_dir / "sensitivity_results.csv").iloc[0]
    assert pd.isna(row["sensitivity [m/%]"])


def test_coupled_case_list_has_effects_detail(tmp_path):
    """Case list CSV must contain non-empty effects_detail for coupled variation cases."""
    work_dir = _setup_coupled_workdir(tmp_path, 10.5, 3.2, 10_000.0, [-1.0, 1.0])
    cases_df = pd.read_csv(work_dir / "sensitivity_case_list.csv")
    coupled_rows = cases_df[cases_df["param_name"] == "Residual Propellant"]
    assert len(coupled_rows) == 2
    assert coupled_rows["effects_detail"].notna().all()
    assert (coupled_rows["effects_detail"].str.len() > 0).all()


def test_coupled_case_list_nominal_is_zero(tmp_path):
    """Coupled param rows must have nominal_value=0 (input-axis convention)."""
    work_dir = _setup_coupled_workdir(tmp_path, 10.5, 3.2, 10_000.0, [-1.0, 1.0])
    cases_df = pd.read_csv(work_dir / "sensitivity_case_list.csv")
    coupled_rows = cases_df[cases_df["param_name"] == "Residual Propellant"]
    assert (coupled_rows["nominal_value"] == 0.0).all()


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests: post_sensitivity math
# ──────────────────────────────────────────────────────────────────────────────

def test_two_point_sensitivity_math(tmp_path):
    """two_point uses outermost cases; slope must be exact for linear response."""
    nominal_mass = 150.0   # kg
    nominal_alt  = 35_000.0  # m
    # linear response: +1% mass → -200 m altitude
    work_dir = _setup_mock_workdir(
        tmp_path, nominal_mass, nominal_alt,
        variations=[-5.0, -2.0, 2.0, 5.0], unit="%", alt_per_pct=-200.0,
    )
    post_sensitivity(str(work_dir))

    row = pd.read_csv(work_dir / "sensitivity_results.csv").iloc[0]

    # two_point uses ±5% cases: delta_alt = -200*5 - (-200*-5) = -1000-1000 = -2000
    # over delta_pct = 10%  → sensitivity = -200 m/%
    assert row["sensitivity [m/%]"] == pytest.approx(-200.0, abs=0.01)

    # input unit is '%', so "1 unit" == "1 %": [m/unit] reports the per-percent value too
    assert row["sensitivity [m/unit]"] == pytest.approx(-200.0, abs=0.01)


def test_two_point_nominal_reference(tmp_path):
    """A reference variation of 0 falls back to the nominal case (case 0), enabling a
    one-sided reference like nominal→+5%. The nominal point is not a perturbed case, so
    post must synthesize it from nominal_altitude/value."""
    nominal_mass = 150.0   # kg
    nominal_alt  = 35_000.0  # m
    work_dir = _setup_mock_workdir(
        tmp_path, nominal_mass, nominal_alt,
        variations=[-5.0, -2.0, 2.0, 5.0], unit="%", alt_per_pct=-200.0,
        ref_vars=[0.0, 5.0],
    )
    post_sensitivity(str(work_dir))

    row = pd.read_csv(work_dir / "sensitivity_results.csv").iloc[0]

    # one-sided nominal→+5%: delta_alt = (35000-200*5) - 35000 = -1000 over delta_pct = 5%
    assert row["sensitivity [m/%]"] == pytest.approx(-200.0, abs=0.01)
    # low endpoint is the nominal altitude/value itself
    assert row["altitude_low [m]"] == pytest.approx(nominal_alt, abs=0.01)
    assert row["variation_low"] == pytest.approx(0.0, abs=1e-9)
    # input unit is '%', so [m/unit] == [m/%]
    assert row["sensitivity [m/unit]"] == pytest.approx(-200.0, abs=0.01)


def test_linear_fit_matches_two_point_on_linear_data(tmp_path):
    """For perfectly linear altitude response, linear_fit and two_point must agree."""
    nominal_mass = 150.0
    nominal_alt  = 35_000.0

    work_two = tmp_path / "two_point"
    work_two.mkdir()
    _setup_mock_workdir(work_two, nominal_mass, nominal_alt,
                        [-5.0, -2.0, 2.0, 5.0], "%", -200.0, method="two_point")
    post_sensitivity(str(work_two))

    work_lin = tmp_path / "linear_fit"
    work_lin.mkdir()
    _setup_mock_workdir(work_lin, nominal_mass, nominal_alt,
                        [-5.0, -2.0, 2.0, 5.0], "%", -200.0, method="linear_fit")
    post_sensitivity(str(work_lin))

    r_two = pd.read_csv(work_two / "sensitivity_results.csv").iloc[0]
    r_lin = pd.read_csv(work_lin / "sensitivity_results.csv").iloc[0]

    assert r_two["sensitivity [m/%]"] == pytest.approx(r_lin["sensitivity [m/%]"], rel=1e-4)
    assert r_two["sensitivity [m/unit]"] == pytest.approx(r_lin["sensitivity [m/unit]"], rel=1e-4)


def test_absolute_unit_sensitivity(tmp_path):
    """Variation in physical unit [kg]: sensitivity [m/unit] must be exact."""
    nominal_mass = 150.0  # kg
    nominal_alt  = 35_000.0  # m
    # +1 kg mass → -20 m altitude
    work_dir = _setup_mock_workdir(
        tmp_path, nominal_mass, nominal_alt,
        variations=[-10.0, -4.0, 4.0, 10.0], unit="kg", alt_per_pct=-20.0,
        # alt_per_pct is used as alt_per_pct_of_nominal here (helper converts kg→%)
    )
    post_sensitivity(str(work_dir))

    row = pd.read_csv(work_dir / "sensitivity_results.csv").iloc[0]
    # delta_alt = -20 * (-10/150*100) - (-20 * (10/150*100)) = ... use simpler:
    # alt(+10 kg) = nominal + (10/150*100)*(-20) = 35000 - 13.33 m
    # alt(-10 kg) = nominal + (-10/150*100)*(-20) = 35000 + 13.33 m
    # delta_param = 160-140 = 20 kg; delta_alt = -26.67 m
    # sensitivity [m/kg] = -26.67 / 20 = -1.333... but per kg that's -1.333
    # Actually simpler: alt_per_pct_of_nominal = -20 (as m per 1% of nominal)
    # pct(+10kg) = 10/150*100 = 6.667%, alt = 35000 + 6.667*(-20) = 34866.67
    # pct(-10kg) = -6.667%,              alt = 35000 + (-6.667)*(-20) = 35133.33
    # sens [m/kg] = (34866.67 - 35133.33) / (160 - 140) = -266.67/20 = -13.333 m/kg
    # sens [m/%]  = (34866.67 - 35133.33) / (6.667 - (-6.667)) = -266.67/13.333 = -20.0 m/%
    assert row["sensitivity [m/%]"] == pytest.approx(-20.0, rel=1e-3)


def test_reference_variations_selects_inner_cases(tmp_path):
    """Reference Variations picks specific two-point cases instead of min/max."""
    nominal_mass = 150.0
    nominal_alt  = 35_000.0
    variations   = [-5.0, -2.0, 2.0, 5.0]
    # Non-linear: inner cases have different slope than outer
    # ±5%  → ±1000 m (outer slope: -200 m/%)
    # ±2%  → ± 600 m (inner slope: -300 m/%)
    altitudes = {0: nominal_alt, 1: 36000.0, 2: 35600.0, 3: 34400.0, 4: 34000.0}

    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    sp = {"Name": "Mass Inert", "Variation Unit": "%",
          "Variations": variations, "Reference Variations": [-2.0, 2.0]}
    _write_sensitivity_config(tmp_path, [sp])

    rows = [(0, "nominal", 0.0, "%", "", "")]
    for i, var in enumerate(variations, start=1):
        rows.append((i, "Mass Inert", var, "%", nominal_mass,
                     _compute_param_value(nominal_mass, var, "%")))
    _write_case_list(tmp_path, rows)

    for cn, alt in altitudes.items():
        _write_mock_flight_log(cases_dir, cn, alt)

    post_sensitivity(str(tmp_path))

    row = pd.read_csv(tmp_path / "sensitivity_results.csv").iloc[0]
    # Uses ±2% cases: delta_alt = 34400-35600 = -1200 m, delta_pct = 4%  → -300 m/%
    assert row["sensitivity [m/%]"] == pytest.approx(-300.0, abs=0.01)


def test_output_files_created(tmp_path):
    """All three output files must exist after a successful post_sensitivity run."""
    work_dir = _setup_mock_workdir(
        tmp_path, 150.0, 35_000.0, [-5.0, 5.0], "%", -200.0
    )
    post_sensitivity(str(work_dir))

    assert (tmp_path / "sensitivity_cases.csv").exists()
    assert (tmp_path / "sensitivity_results.csv").exists()
    assert (tmp_path / "sensitivity_tornado.png").exists()


def test_sensitivity_cases_csv_has_altitude_for_all_cases(tmp_path):
    """sensitivity_cases.csv must have a non-NaN altitude for every case."""
    work_dir = _setup_mock_workdir(
        tmp_path, 150.0, 35_000.0, [-5.0, 5.0], "%", -200.0
    )
    post_sensitivity(str(work_dir))

    df = pd.read_csv(tmp_path / "sensitivity_cases.csv")
    assert df["altitude_apogee [m]"].isna().sum() == 0


def test_sensitivity_unit_consistency(tmp_path):
    """For %-variation params "1 unit" IS "1 %", so [m/unit] must equal [m/%]."""
    work_dir = _setup_mock_workdir(
        tmp_path, 150.0, 35_000.0, [-5.0, -2.0, 2.0, 5.0], "%", -200.0
    )
    post_sensitivity(str(work_dir))

    results = pd.read_csv(tmp_path / "sensitivity_results.csv")

    for _, row in results.iterrows():
        if row["variation_unit"] != "%":
            continue
        assert row["sensitivity [m/unit]"] == pytest.approx(row["sensitivity [m/%]"], rel=1e-3), (
            f"{row['param_name']}: [m/unit] {row['sensitivity [m/unit]']:.4f} "
            f"≠ [m/%] {row['sensitivity [m/%]']:.4f}"
        )


def test_get_nominal_poi_file_mode_rejects_non_percent():
    """POI in file mode is a multiplier, so only Variation Unit '%' is meaningful."""
    rp = {"Enable Product of Inertia File": True}
    with pytest.raises(ValueError, match='only supports Variation Unit "%"'):
        _get_nominal("POI Ixy", {}, rp, {}, "kg-m2")
    assert _get_nominal("POI Ixy", {}, rp, {}, "%") == pytest.approx(1.0)


def test_sensitivity_poi_file_mode_writes_scaled_per_case_files(monkeypatch, tmp_path, projects_dir):
    """POI sensitivity in file mode: each varied case gets a per-case POI file holding the
    base curve scaled by (1 + variation/100), with the case rocket_param pointing at it.
    The nominal case keeps the original file (by basename, no per-case file). Components
    that are not varied are referenced by basename — resolving against the copy placed in
    cases/ — so the work directory is self-contained, and get no per-case file.

    Binary-independent: per-case files are written before the solver runs, so a no-op
    run_solver exercises all of the staging logic.
    """
    import numpy as np
    from path_define import chdir

    proj = copy_example(projects_dir, tmp_path / "example")

    rp_path = proj / "param_rocket.json"
    rp = json.loads(rp_path.read_text())
    rp["Enable Product of Inertia"] = False
    rp["Enable Product of Inertia File"] = True
    rp.setdefault("Product of Inertia File", {})
    rp["Product of Inertia File"]["Ixy File Path"] = "poi_ixy.csv"
    rp["Product of Inertia File"]["Ixz File Path"] = "poi_ixz.csv"
    rp["Product of Inertia File"]["Iyz File Path"] = "poi_iyz.csv"
    rp_path.write_text(json.dumps(rp))

    base = np.array([[0.0, 2.0], [1.0, 4.0], [2.0, 6.0]])
    base_vals = base[:, 1]
    for comp in ("ixy", "ixz", "iyz"):
        np.savetxt(proj / f"poi_{comp}.csv", base, delimiter=",",
                   header=f"Time,{comp.capitalize()}", comments="")

    sens_cfg = {
        "Sensitivity Parameters": [
            {"Name": "POI Ixy", "Variation Unit": "%", "Variations": [-10.0, 10.0]},
        ],
        "Sensitivity Calculation": {"Method": "two_point"},
    }
    (proj / "config_sensitivity.json").write_text(json.dumps(sens_cfg))

    monkeypatch.setattr("runner_tool.runner_single.run_solver", lambda *a, **k: None)

    with chdir(str(proj)):
        work_dir = run_sensitivity("config_solver.json", "config_sensitivity.json")

    # work_dir is './work_sensitivity...' relative to proj (the chdir target).
    cases_dir = proj / Path(work_dir).name / "cases"

    # case 1 = -10% -> x0.9, case 2 = +10% -> x1.1
    for cn, mult in {1: 0.9, 2: 1.1}.items():
        pf = cases_dir / f"{cn}_poi_Ixy.csv"
        assert pf.exists(), f"missing per-case POI file for case {cn}"
        scaled = np.loadtxt(pf, delimiter=",", skiprows=1)[:, 1]
        assert np.allclose(scaled, base_vals * mult)
        rp_case = json.loads((cases_dir / f"{cn}_rocket_param.json").read_text())
        assert rp_case["Product of Inertia File"]["Ixy File Path"] == f"{cn}_poi_Ixy.csv"
        # Non-varied components reference the copied file by basename (self-contained,
        # resolving against cases/), with no per-case file.
        ixz_path = rp_case["Product of Inertia File"]["Ixz File Path"]
        assert not Path(ixz_path).is_absolute()
        assert Path(ixz_path).name == "poi_ixz.csv"
        assert (cases_dir / ixz_path).exists()

    # nominal case: original file by basename, no scaling
    assert not (cases_dir / "0_poi_Ixy.csv").exists()
    rp0 = json.loads((cases_dir / "0_rocket_param.json").read_text())
    ixy0 = rp0["Product of Inertia File"]["Ixy File Path"]
    assert not Path(ixy0).is_absolute()
    assert Path(ixy0).name == "poi_ixy.csv"
    assert (cases_dir / ixy0).exists()

    assert not list(cases_dir.glob("*_poi_Ixz.csv"))
    assert not list(cases_dir.glob("*_poi_Iyz.csv"))


def test_sensitivity_aero_files_are_self_contained(monkeypatch, tmp_path, projects_dir):
    """File-mode aerodynamic coefficients that sensitivity never varies (X-C.P., CNa, ...)
    must be copied into cases/ and referenced by basename in every case rocket_param, so the
    work directory is self-contained (reproducible without projects/**). Before unification
    these paths were left untouched/relative and ForRocket — running from cases/ — could not
    resolve them, so every case failed to produce a flight log (regression: "Nominal case
    (case 0) flight log not found"). Binary-independent: run_solver is a no-op.
    """
    from path_define import chdir

    proj = copy_example(projects_dir, tmp_path / "example")

    # Enable X-C.P. and CNa file modes with basename paths to files in the project dir.
    rp_path = proj / "param_rocket.json"
    rp = json.loads(rp_path.read_text())
    rp["Enable X-C.P. File"] = True
    rp["X-C.P. File"]["X-C.P. File Path"] = "xcp.csv"
    rp["Enable CNa File"] = True
    rp["CNa File"]["CNa File Path"] = "cna.csv"
    rp_path.write_text(json.dumps(rp))
    # X-C.P. table values are metres: the solver interpolates them as-is, and only the
    # "Constant X-C.P. from BodyTail [mm]" field is divided by 1e3 (rocket_factory.cpp).
    (proj / "xcp.csv").write_text("mach,xcp\n0,1.0\n2,1.1\n")
    (proj / "cna.csv").write_text("mach,cna\n0,10\n2,12\n")

    sens_cfg = {
        "Sensitivity Parameters": [
            {"Name": "Mass Inert", "Variation Unit": "%", "Variations": [-5.0, 5.0]},
        ],
        "Sensitivity Calculation": {"Method": "two_point"},
    }
    (proj / "config_sensitivity.json").write_text(json.dumps(sens_cfg))

    monkeypatch.setattr("runner_tool.runner_single.run_solver", lambda *a, **k: None)

    with chdir(str(proj)):
        work_dir = run_sensitivity("config_solver.json", "config_sensitivity.json")

    cases_dir = proj / Path(work_dir).name / "cases"

    # Shared cross-mode guard: every enabled file reference in every per-case config resolves
    # inside cases/ with no absolute path into projects/**.
    assert_cases_self_contained(cases_dir)

    # And specifically the X-C.P./CNa references (the exact coefficients in the regression).
    rp_files = sorted(cases_dir.glob("*_rocket_param.json"))
    assert rp_files, "no case rocket_param files generated"
    for rp_file in rp_files:
        rp_case = json.loads(rp_file.read_text())
        xcp = rp_case["X-C.P. File"]["X-C.P. File Path"]
        cna = rp_case["CNa File"]["CNa File Path"]
        assert not Path(xcp).is_absolute(), f"{rp_file.name}: {xcp}"
        assert not Path(cna).is_absolute(), f"{rp_file.name}: {cna}"
        assert (cases_dir / xcp).exists(), f"{rp_file.name}: {xcp} not in cases/"
        assert (cases_dir / cna).exists(), f"{rp_file.name}: {cna} not in cases/"


def test_get_nominal_aero_file_mode_rejects_the_wrong_unit_kind():
    """File-mode aero tables are varied as a whole, so the unit says which operation applies:
    a multiplier for the coefficient tables, an absolute offset for X-C.P.

    Both wrong combinations used to be accepted and produce a run with no variation at all —
    the coefficient case because the variation went into the constant field the solver ignores,
    and X-C.P. with '%' because a percentage of its zero nominal is zero.
    """
    rp_cna = {"Enable CNa File": True}
    with pytest.raises(ValueError, match='only supports Variation Unit "%"'):
        _get_nominal("CNa", {}, rp_cna, {}, "m")
    assert _get_nominal("CNa", {}, rp_cna, {}, "%") == pytest.approx(1.0)

    rp_xcp = {"Enable X-C.P. File": True}
    with pytest.raises(ValueError, match="absolute offset"):
        _get_nominal("XCP", {}, rp_xcp, {}, "%")
    assert _get_nominal("XCP", {}, rp_xcp, {}, "m") == pytest.approx(0.0)


def test_compute_absolute_converts_into_the_target_unit():
    """An absolute variation is stated in Variation Unit but written into a field with its own
    unit. The constant X-C.P./X-C.G. fields are millimetres, so 0.02 m must land as 20 mm."""
    from runner_tool.runner_sensitivity import _target_unit

    assert _compute_param_value(1500.0, 0.02, "m", target_unit="mm") == pytest.approx(1520.0)
    assert _compute_param_value(1500.0, 20.0, "mm", target_unit="mm") == pytest.approx(1520.0)
    # The X-C.P. table is metres, so the same 0.02 m offset stays 0.02 there.
    assert _compute_param_value(0.0, 0.02, "m", target_unit="m") == pytest.approx(0.02)
    # Which target applies is decided by whether the solver reads the file or the field.
    assert _target_unit("XCP", {"Enable X-C.P. File": True}) == "m"
    assert _target_unit("XCP", {"Enable X-C.P. File": False}) == "mm"
    assert _target_unit("Mass Inert", {}) is None


def test_sensitivity_aero_file_mode_writes_per_case_tables(monkeypatch, tmp_path, projects_dir):
    """Varying a file-mode aero coefficient must rewrite the table, not the ignored field.

    CNa is scaled by (1 + variation/100); X-C.P. is shifted by an absolute offset that is the
    same at every Mach (scaling it would move the CP by a Mach-dependent amount). Before this,
    both variations were written to the constant field the solver skips in file mode, so every
    case flew identical aerodynamics and the sensitivity came out as zero.
    """
    import numpy as np
    from path_define import chdir

    proj = copy_example(projects_dir, tmp_path / "example")

    mach = np.array([0.0, 1.0, 2.0])
    cna_base = np.array([8.0, 12.0, 10.0])
    xcp_base = np.array([1.00, 1.26, 1.18])   # metres from body tail
    np.savetxt(proj / "cna.csv", np.c_[mach, cna_base], delimiter=",",
               header="mach,CNa", comments="")
    np.savetxt(proj / "xcp.csv", np.c_[mach, xcp_base], delimiter=",",
               header="mach,Xcp", comments="")

    rp_path = proj / "param_rocket.json"
    rp = json.loads(rp_path.read_text())
    rp["Enable CNa File"] = True
    rp["CNa File"]["CNa File Path"] = "cna.csv"
    rp["Enable X-C.P. File"] = True
    rp["X-C.P. File"]["X-C.P. File Path"] = "xcp.csv"
    rp_path.write_text(json.dumps(rp))

    sens_cfg = {
        "Sensitivity Parameters": [
            {"Name": "CNa", "Variation Unit": "%", "Variations": [-10.0, 10.0]},
            {"Name": "XCP", "Variation Unit": "m", "Variations": [-0.02, 0.02]},
        ],
        "Sensitivity Calculation": {"Method": "two_point"},
    }
    (proj / "config_sensitivity.json").write_text(json.dumps(sens_cfg))

    monkeypatch.setattr("runner_tool.runner_single.run_solver", lambda *a, **k: None)
    with chdir(str(proj)):
        work_dir = run_sensitivity("config_solver.json", "config_sensitivity.json")
    cases_dir = proj / Path(work_dir).name / "cases"

    assert_cases_self_contained(cases_dir)

    # cases 1,2 = CNa -10%/+10%; cases 3,4 = XCP -0.02/+0.02 m
    for cn, mult in {1: 0.9, 2: 1.1}.items():
        table = np.loadtxt(cases_dir / f"{cn}_CNa.csv", delimiter=",", skiprows=1)
        assert np.allclose(table[:, 0], mach)
        assert np.allclose(table[:, 1], cna_base * mult)
        rp_case = json.loads((cases_dir / f"{cn}_rocket_param.json").read_text())
        assert rp_case["CNa File"]["CNa File Path"] == f"{cn}_CNa.csv"

    for cn, offset in {3: -0.02, 4: 0.02}.items():
        table = np.loadtxt(cases_dir / f"{cn}_XCP.csv", delimiter=",", skiprows=1)
        assert np.allclose(table[:, 0], mach)
        assert np.allclose(table[:, 1], xcp_base + offset), "XCP must be offset, not scaled"
        rp_case = json.loads((cases_dir / f"{cn}_rocket_param.json").read_text())
        assert rp_case["X-C.P. File"]["X-C.P. File Path"] == f"{cn}_XCP.csv"

    # The nominal case and the cases varying the *other* parameter keep the shared base table.
    for cn in (0, 3, 4):
        rp_case = json.loads((cases_dir / f"{cn}_rocket_param.json").read_text())
        assert rp_case["CNa File"]["CNa File Path"] == "cna.csv"
    assert not (cases_dir / "0_CNa.csv").exists()
    assert not (cases_dir / "0_XCP.csv").exists()


# ──────────────────────────────────────────────────────────────────────────────
# Integration tests (binary required)
# ──────────────────────────────────────────────────────────────────────────────

_INTEGRATION_SENSITIVITY_CFG = {
    "Sensitivity Parameters": [
        {"Name": "Mass Inert",      "Variation Unit": "%", "Variations": [-5.0, 5.0]},
        {"Name": "Propellant Mass", "Variation Unit": "%", "Variations": [-5.0, 5.0]},
        {"Name": "Thrust",          "Variation Unit": "%", "Variations": [-5.0, 5.0]},
    ],
    "Sensitivity Calculation": {"Method": "two_point"},
}


@pytest.fixture(scope="module")
def example_sensitivity_results(binary_path, tmp_path_factory, projects_dir):
    """
    Run a full sensitivity analysis on a copy of the sample project in a temp directory.
    Returns (work_dir, results_df, cases_df) reused by all integration tests.
    """
    import os
    from path_define import chdir

    src = projects_dir / "example"
    run_root = tmp_path_factory.mktemp("example_sensitivity")

    # Copy input files (files only, skip existing work_* dirs)
    for item in src.iterdir():
        if item.is_file():
            shutil.copy2(item, run_root / item.name)

    sens_cfg_file = run_root / "test_sensitivity_config.json"
    sens_cfg_file.write_text(json.dumps(_INTEGRATION_SENSITIVITY_CFG))

    with chdir(run_root):
        work_dir = run_sensitivity(
            _SOLVER_CFG,
            sens_cfg_file.name,
            max_thread_run=False,
        )
        post_sensitivity(work_dir)

    work_path = run_root / Path(work_dir).name
    return (
        work_path,
        pd.read_csv(work_path / "sensitivity_results.csv"),
        pd.read_csv(work_path / "sensitivity_cases.csv"),
    )


def test_integration_output_files_exist(example_sensitivity_results):
    work_dir, _, _ = example_sensitivity_results
    assert (work_dir / "sensitivity_cases.csv").exists()
    assert (work_dir / "sensitivity_results.csv").exists()
    assert (work_dir / "sensitivity_tornado.png").exists()
    assert (work_dir / "sensitivity_case_list.csv").exists()


def test_integration_case_count(example_sensitivity_results):
    """Total cases = 3 params × 2 variations + 1 nominal = 7."""
    _, _, cases_df = example_sensitivity_results
    assert len(cases_df) == 7


def test_integration_no_missing_altitudes(example_sensitivity_results):
    """Every case must produce a valid apogee altitude."""
    _, _, cases_df = example_sensitivity_results
    assert cases_df["altitude_apogee [m]"].isna().sum() == 0


def test_integration_heavier_mass_reduces_apogee(example_sensitivity_results):
    """More inert mass → lower apogee → sensitivity [m/%] must be negative."""
    _, results, _ = example_sensitivity_results
    row = results[results["param_name"] == "Mass Inert"].iloc[0]
    assert row["sensitivity [m/%]"] < 0, (
        f"Mass Inert sensitivity must be negative, got {row['sensitivity [m/%]']:.2f} m/%"
    )


def test_integration_more_propellant_raises_apogee(example_sensitivity_results):
    """More propellant → more delta-V → higher apogee → sensitivity [m/%] must be positive."""
    _, results, _ = example_sensitivity_results
    row = results[results["param_name"] == "Propellant Mass"].iloc[0]
    assert row["sensitivity [m/%]"] > 0, (
        f"Propellant Mass sensitivity must be positive, got {row['sensitivity [m/%]']:.2f} m/%"
    )


def test_integration_higher_thrust_raises_apogee(example_sensitivity_results):
    """Higher thrust → higher apogee → sensitivity [m/%] must be positive."""
    _, results, _ = example_sensitivity_results
    row = results[results["param_name"] == "Thrust"].iloc[0]
    assert row["sensitivity [m/%]"] > 0, (
        f"Thrust sensitivity must be positive, got {row['sensitivity [m/%]']:.2f} m/%"
    )


def test_integration_unit_consistency(example_sensitivity_results):
    """For %-variation params "1 unit" IS "1 %", so [m/unit] must equal [m/%]."""
    _, results, _ = example_sensitivity_results
    for _, row in results.iterrows():
        if row["variation_unit"] != "%":
            continue
        assert row["sensitivity [m/unit]"] == pytest.approx(row["sensitivity [m/%]"], rel=1e-3), (
            f"{row['param_name']}: [m/unit] {row['sensitivity [m/unit]']:.4f} "
            f"≠ [m/%] {row['sensitivity [m/%]']:.4f}"
        )
