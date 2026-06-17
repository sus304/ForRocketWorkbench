"""
Behavioral tests: intentional parameter changes → expected directional changes in output.

These tests do NOT use golden files. Each test runs two simulations (base + modified)
and asserts that a metric changed in the expected direction.

Useful for verifying that:
- A code change that intentionally alters behavior produces the right effect
- The simulation physics pipeline is correctly wired end-to-end
"""
import pytest

from tests.sim_runner import run_sim, extract_metrics

_BASE_SOLVER = "config_solver.json"


@pytest.fixture(scope="session")
def example_base(binary_path, config_dir):
    """Base metrics for the sample project, computed once per test session."""
    return extract_metrics(run_sim(config_dir, _BASE_SOLVER, binary_path))


# ---------------------------------------------------------------------------
# Launch condition tests
# ---------------------------------------------------------------------------

def _set_elevation(deg):
    def mod(cfgs):
        cfgs["solver"]["Launch Condition"]["Elevation [deg]"] = deg
    return mod


def test_higher_elevation_raises_apogee(binary_path, config_dir):
    """Steeper launch angle → higher apogee altitude.

    Compares two clearly sub-vertical elevations (70° vs 80°) rather than perturbing the
    sample's near-vertical 85° base: above ~85° the apogee gain from added verticality is
    tiny and can be reversed by wind/drag asymmetry, which is a numerical artefact of the
    operating point, not the physics this test means to assert."""
    high = extract_metrics(run_sim(config_dir, _BASE_SOLVER, binary_path, modify_configs=_set_elevation(80.0)))
    low  = extract_metrics(run_sim(config_dir, _BASE_SOLVER, binary_path, modify_configs=_set_elevation(70.0)))
    assert high["apogee_altitude_m"] > low["apogee_altitude_m"], (
        f"apogee: 80deg={high['apogee_altitude_m']:.1f} <= 70deg={low['apogee_altitude_m']:.1f}"
    )


def test_lower_elevation_increases_downrange(binary_path, config_dir, example_base):
    """Shallower launch angle → larger horizontal range at landing."""
    def mod(cfgs):
        cfgs["solver"]["Launch Condition"]["Elevation [deg]"] -= 5.0

    result = extract_metrics(run_sim(config_dir, _BASE_SOLVER, binary_path, modify_configs=mod))
    assert result["landing_downrange_m"] > example_base["landing_downrange_m"], (
        f"downrange: {result['landing_downrange_m']:.1f} <= base {example_base['landing_downrange_m']:.1f}"
    )


# ---------------------------------------------------------------------------
# Mass / propellant tests
# ---------------------------------------------------------------------------

def test_lighter_inert_mass_raises_apogee(binary_path, config_dir, example_base):
    """Lighter inert mass (-10%) → higher apogee (same thrust, less mass)."""
    def mod(cfgs):
        cfgs["rocket1"]["Mass"]["Inert [kg]"] *= 0.90

    result = extract_metrics(run_sim(config_dir, _BASE_SOLVER, binary_path, modify_configs=mod))
    assert result["apogee_altitude_m"] > example_base["apogee_altitude_m"], (
        f"apogee: {result['apogee_altitude_m']:.1f} <= base {example_base['apogee_altitude_m']:.1f}"
    )


# ---------------------------------------------------------------------------
# Aerodynamics tests
# ---------------------------------------------------------------------------

def test_higher_CA_reduces_max_mach(binary_path, config_dir):
    """Higher axial drag coefficient → lower max Mach number."""
    def high_ca(cfgs):
        cfgs["rocket1"]["Enable CA File"] = False
        cfgs["rocket1"]["Constant CA"]["Constant CA [-]"] = 0.80
        cfgs["rocket1"]["Constant CA"]["Constant BurnOut CA [-]"] = 0.80

    def low_ca(cfgs):
        cfgs["rocket1"]["Enable CA File"] = False
        cfgs["rocket1"]["Constant CA"]["Constant CA [-]"] = 0.30
        cfgs["rocket1"]["Constant CA"]["Constant BurnOut CA [-]"] = 0.30

    high = extract_metrics(run_sim(config_dir, _BASE_SOLVER, binary_path, modify_configs=high_ca))
    low  = extract_metrics(run_sim(config_dir, _BASE_SOLVER, binary_path, modify_configs=low_ca))

    assert low["max_mach"] > high["max_mach"], (
        f"max_mach: low_CA={low['max_mach']:.3f}  high_CA={high['max_mach']:.3f}"
    )


# ---------------------------------------------------------------------------
# Thrust tests
# ---------------------------------------------------------------------------

def _ascent_max_dynamic_pressure_kPa(df):
    """Peak dynamic pressure during powered ascent (launch → apogee).

    Note: for a balloon-launched (Rockoon) trajectory the *global* maxQ occurs
    during high-speed re-entry on descent. That descent maxQ is governed by
    re-entry ballistics (apogee altitude, ballistic coefficient, descent mass)
    and is NOT monotonic in thrust. The load that scales with thrust is the
    ascent-phase maxQ, so the directional test below restricts to that window.
    """
    idx_apogee = int(df["Altitude [m]"].idxmax())
    return float(df["DynamicPressure [kPa]"].iloc[:idx_apogee + 1].max())


def test_higher_thrust_raises_ascent_max_dynamic_pressure(binary_path, config_dir):
    """Higher vacuum thrust → higher max dynamic pressure during ascent."""
    def high_thrust(cfgs):
        cfgs["engine1"]["Enable Thrust File"] = False
        cfgs["engine1"]["Constant Thrust"]["Thrust at vacuum [N]"]            = 80000.0
        cfgs["engine1"]["Constant Thrust"]["Propellant Mass Flow Rate [kg/s]"] = 15.0
        cfgs["engine1"]["Constant Thrust"]["Burn Duration [sec]"]             = 30.0

    def low_thrust(cfgs):
        cfgs["engine1"]["Enable Thrust File"] = False
        cfgs["engine1"]["Constant Thrust"]["Thrust at vacuum [N]"]            = 40000.0
        cfgs["engine1"]["Constant Thrust"]["Propellant Mass Flow Rate [kg/s]"] = 8.0
        cfgs["engine1"]["Constant Thrust"]["Burn Duration [sec]"]             = 30.0

    high = _ascent_max_dynamic_pressure_kPa(run_sim(config_dir, _BASE_SOLVER, binary_path, modify_configs=high_thrust))
    low  = _ascent_max_dynamic_pressure_kPa(run_sim(config_dir, _BASE_SOLVER, binary_path, modify_configs=low_thrust))

    assert high > low, f"ascent maxQ: high={high:.3f}  low={low:.3f}"
