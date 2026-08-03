"""Monte Carlo dispersion of Mach-dependent aero tables, and the unit of an absolute error.

Two bugs of the same family, both of which ran to completion and produced results that looked
like a successful dispersion study while holding the parameter fixed:

  1. CNa / Cld / Clp / Cmq / Cnr / X-C.P. were sampled into the *constant* config field only.
     rocket_factory.cpp is an if/else: with "Enable * File" on, the solver interpolates the table
     and never reads that field, so every case flew identical aerodynamics. Nothing warned, and
     the per-case configs looked plausible because the constant field did vary.
  2. An "Error Unit": "m" magnitude was written straight into the "... [mm]" field it targets,
     making the realised dispersion 1000x too small. X-C.P. and X-C.G. both store millimetres in
     their constant field while their table files hold metres, so the conversion depends on which
     of the two the sample lands in.

These tests run case generation only: _execute_montecarlo_cases is monkeypatched away, so no
ForRocket binary is needed and the assertions read the generated cases/ tree directly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from path_define import chdir
from runner_tool import runner_montecarlo
from runner_tool.runner_montecarlo import _unit_scale, run_montecarlo
from tests._project import copy_example
from tests._selfcontained import assert_cases_self_contained

# Deterministic sampling: the runner draws from the numpy global RandomState, so seeding makes
# the recovered 3-sigma assertions reproducible instead of occasionally flaky.
_SEED = 20260803

# Mach axis and per-parameter base tables. Values vary with Mach on purpose: a scale error and an
# offset error are indistinguishable on a flat table, and X-C.P. is the one parameter where
# telling them apart is the whole point.
_MACH = np.array([0.0, 0.4, 0.8, 1.2, 2.0, 3.0])
_BASE_TABLES = {
    'CNa': np.array([8.0, 8.4, 9.6, 12.0, 10.4, 9.2]),
    'Cld': np.array([0.10, 0.11, 0.13, 0.16, 0.14, 0.12]),
    'Clp': np.array([-0.020, -0.021, -0.024, -0.030, -0.026, -0.023]),
    'Cmq': np.array([-3.0, -3.2, -3.6, -4.5, -3.9, -3.4]),
    'Cnr': np.array([-3.0, -3.2, -3.6, -4.5, -3.9, -3.4]),
    # metres from body tail; the CP moves aft through the transonic region
    'XCP': np.array([1.00, 1.02, 1.09, 1.26, 1.18, 1.12]),
}
# ('Enable * File' flag, block, path key) per error-parameter name, as the rocket config spells it
_FILE_KEYS = {
    'CNa': ('Enable CNa File', 'CNa File', 'CNa File Path'),
    'Cld': ('Enable Cld File', 'Cld File', 'Cld File Path'),
    'Clp': ('Enable Clp File', 'Clp File', 'Clp File Path'),
    'Cmq': ('Enable Cmq File', 'Cmq File', 'Cmq File Path'),
    'Cnr': ('Enable Cnr File', 'Cnr File', 'Cnr File Path'),
    'XCP': ('Enable X-C.P. File', 'X-C.P. File', 'X-C.P. File Path'),
}
_CONSTANT_KEYS = {
    'CNa': ('Constant CNa', 'Constant CNa [1/rad]'),
    'XCP': ('Constant X-C.P.', 'Constant X-C.P. from BodyTail [mm]'),
}


def _write_table(project: Path, name: str) -> str:
    """Write the base table for `name` into the project and return its basename."""
    fname = f'base_{name}.csv'
    np.savetxt(project / fname, np.c_[_MACH, _BASE_TABLES[name]],
               delimiter=',', fmt='%0.9f', header=f'mach,{name}', comments='')
    return fname


def _enable_file_mode(project: Path, names) -> None:
    """Point the rocket config at a real base table for each name and turn its file mode on."""
    stage = json.loads((project / 'param_list_stage1.json').read_text())
    rocket_path = project / stage['Rocket Configuration File Path']
    rocket = json.loads(rocket_path.read_text())
    for name in names:
        enable_key, block_key, path_key = _FILE_KEYS[name]
        rocket[enable_key] = True
        rocket.setdefault(block_key, {})[path_key] = _write_table(project, name)
    rocket_path.write_text(json.dumps(rocket, indent=4))


def _set_errors(project: Path, case_count: int, errors: dict) -> None:
    """Set MonteCarlo Case Count and the given {name: (unit, 3sigma)} error parameters.

    Every other error parameter is disabled, so a test's assertions are about the parameters it
    configured and nothing else (the sample project ships with CA dispersion on).
    """
    mc_path = project / 'config_montecarlo.json'
    mc = json.loads(mc_path.read_text())
    mc['MonteCarlo Case Count'] = case_count
    for name, ep in mc['Error Parameters'].items():
        if name != 'Wind':
            ep['Enable'] = False
    for name, (unit, sigma3) in errors.items():
        mc['Error Parameters'][name] = {
            'Enable': True, 'Error Unit': unit,
            'Error 3sigma Low': sigma3, 'Error 3sigma High': sigma3,
        }
    mc_path.write_text(json.dumps(mc, indent=4))


def _run(project: Path, monkeypatch) -> Path:
    """Generate the cases (no solver) and return the work dir."""
    monkeypatch.setattr(runner_montecarlo, '_execute_montecarlo_cases', lambda *a, **k: None)
    np.random.seed(_SEED)
    with chdir(str(project)):
        run_montecarlo('config_solver.json', 'config_montecarlo.json')
    return next(project.glob('work_montecarlo*'))


def _case_rocket(work_dir: Path, case_num: int) -> dict:
    cases = work_dir / 'cases'
    stage = json.loads((cases / f'{case_num}_stage_config.json').read_text())
    return json.loads((cases / stage['Rocket Configuration File Path']).read_text())


def _case_table(work_dir: Path, case_num: int, name: str) -> tuple:
    """(mach axis, values) of the table case `case_num` actually points at for `name`."""
    _, block_key, path_key = _FILE_KEYS[name]
    path = _case_rocket(work_dir, case_num)[block_key][path_key]
    assert not Path(path).is_absolute(), f'case {case_num} {name} path is absolute: {path}'
    arr = np.loadtxt(work_dir / 'cases' / path, delimiter=',', skiprows=1)
    return arr[:, 0], arr[:, 1]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _realised_3sigma(values) -> float:
    """3-sigma of the realised population, matching how the config states the error."""
    return 3.0 * float(np.std(values, ddof=1))


# ── File-mode dispersion actually reaches the solver's input ─────────────────────

def test_file_mode_tables_are_per_case_and_distinct(tmp_path, projects_dir, monkeypatch):
    """Every file-mode parameter with an error gets its own table per case.

    The bug: the per-case config kept pointing at the single shared base table (byte-identical
    across cases) while the dispersion went into the ignored constant field.
    """
    project = copy_example(projects_dir, tmp_path / 'example')
    names = list(_FILE_KEYS)
    _enable_file_mode(project, names)
    _set_errors(project, 6, {n: ('m' if n == 'XCP' else '%', 0.02 if n == 'XCP' else 10.0)
                             for n in names})
    work_dir = _run(project, monkeypatch)

    for name in names:
        _, block_key, path_key = _FILE_KEYS[name]
        paths = [_case_rocket(work_dir, c)[block_key][path_key] for c in range(6)]
        assert len(set(paths)) == 6, f'{name} cases share a table: {paths}'
        digests = {_md5(work_dir / 'cases' / p) for p in paths}
        assert len(digests) == 6, f'{name} per-case tables are not distinct'
        base = f'base_{name}.csv'
        assert base not in paths, f'{name} still references the shared base table'


def test_case0_table_equals_the_nominal_table(tmp_path, projects_dir, monkeypatch):
    """Case 0 is the nominal case for tables too, exactly as it is for scalar parameters."""
    project = copy_example(projects_dir, tmp_path / 'example')
    _enable_file_mode(project, ['CNa', 'XCP'])
    _set_errors(project, 5, {'CNa': ('%', 10.0), 'XCP': ('m', 0.02)})
    work_dir = _run(project, monkeypatch)

    for name in ('CNa', 'XCP'):
        mach, vals = _case_table(work_dir, 0, name)
        assert mach == pytest.approx(_MACH)
        assert vals == pytest.approx(_BASE_TABLES[name]), f'case 0 {name} is not the nominal table'


def test_scale_params_apply_one_multiplier_across_mach(tmp_path, projects_dir, monkeypatch):
    """A "%" error on a coefficient table scales the whole table by a single factor, and the
    realised 3-sigma of that factor matches the configured percentage."""
    project = copy_example(projects_dir, tmp_path / 'example')
    names = ['CNa', 'Cld', 'Clp', 'Cmq', 'Cnr']
    case_count = 300
    _enable_file_mode(project, names)
    _set_errors(project, case_count, {n: ('%', 10.0) for n in names})
    work_dir = _run(project, monkeypatch)

    for name in names:
        base = _BASE_TABLES[name]
        multipliers = []
        for case_num in range(1, case_count):
            mach, vals = _case_table(work_dir, case_num, name)
            assert mach == pytest.approx(_MACH), f'{name} case {case_num} lost the mach axis'
            ratio = vals / base
            # one multiplier for the whole table: no Mach-dependent distortion
            assert ratio == pytest.approx(ratio[0], rel=1e-5), \
                f'{name} case {case_num} is not a uniform scaling: {ratio}'
            multipliers.append(ratio[0])
        # 10% 3-sigma on a multiplier centred at 1.0
        assert _realised_3sigma(multipliers) == pytest.approx(0.10, rel=0.25)
        assert np.mean(multipliers) == pytest.approx(1.0, abs=0.02)


def test_xcp_is_an_additive_offset_in_metres(tmp_path, projects_dir, monkeypatch):
    """X-C.P. must shift the whole CP table by one absolute distance, not scale it.

    Scaling would move the CP by an amount proportional to its distance from the tail, so the
    realised shift would differ Mach by Mach — not what a CP uncertainty of +-x m means. The
    magnitude is also the unit regression: 0.02 m must land as 0.02 m, not 0.02 mm.
    """
    project = copy_example(projects_dir, tmp_path / 'example')
    case_count = 300
    sigma3_m = 0.02
    _enable_file_mode(project, ['XCP'])
    _set_errors(project, case_count, {'XCP': ('m', sigma3_m)})
    work_dir = _run(project, monkeypatch)

    base = _BASE_TABLES['XCP']
    offsets = []
    for case_num in range(1, case_count):
        mach, vals = _case_table(work_dir, case_num, 'XCP')
        assert mach == pytest.approx(_MACH)
        offset = vals - base
        assert offset == pytest.approx(offset[0], abs=1e-9), \
            f'XCP case {case_num} is not a uniform offset (scaled instead?): {offset}'
        offsets.append(offset[0])

    assert _realised_3sigma(offsets) == pytest.approx(sigma3_m, rel=0.25)
    assert np.mean(offsets) == pytest.approx(0.0, abs=0.004)
    # An m-vs-mm mix-up is a factor of 1000, far outside the tolerance above, but assert the
    # order of magnitude directly so the failure message says what went wrong.
    assert 0.002 < np.max(np.abs(offsets)) < 0.2, 'realised XCP offset is not of metre order'


def test_file_mode_leaves_the_ignored_constant_field_alone(tmp_path, projects_dir, monkeypatch):
    """With the table dispersed, the constant field must not also be sampled.

    It would be dead weight the solver never reads, and a per-case config showing two different
    dispersed values for one parameter is actively misleading when reading a run back.
    """
    project = copy_example(projects_dir, tmp_path / 'example')
    _enable_file_mode(project, ['CNa', 'XCP'])
    _set_errors(project, 8, {'CNa': ('%', 10.0), 'XCP': ('m', 0.02)})
    stage = json.loads((project / 'param_list_stage1.json').read_text())
    base_rocket = json.loads((project / stage['Rocket Configuration File Path']).read_text())
    work_dir = _run(project, monkeypatch)

    for name, (block_key, field_key) in _CONSTANT_KEYS.items():
        nominal = base_rocket[block_key][field_key]
        for case_num in range(8):
            got = _case_rocket(work_dir, case_num)[block_key][field_key]
            assert got == nominal, f'{name} constant field was dispersed in file mode (case {case_num})'


def test_file_mode_cases_are_self_contained(tmp_path, projects_dir, monkeypatch):
    """Per-case configs must reference only files inside cases/ — including the tables that are
    in file mode but have no error configured (they keep the staged copy's basename)."""
    project = copy_example(projects_dir, tmp_path / 'example')
    _enable_file_mode(project, list(_FILE_KEYS))
    # CNa and XCP dispersed; Cld/Clp/Cmq/Cnr in file mode with no error at all
    _set_errors(project, 4, {'CNa': ('%', 10.0), 'XCP': ('m', 0.02)})
    work_dir = _run(project, monkeypatch)

    assert_cases_self_contained(work_dir / 'cases')

    # The undispersed tables resolve to the single staged copy, shared by every case.
    for name in ('Cld', 'Clp', 'Cmq', 'Cnr'):
        _, block_key, path_key = _FILE_KEYS[name]
        paths = {_case_rocket(work_dir, c)[block_key][path_key] for c in range(4)}
        assert paths == {f'base_{name}.csv'}, f'{name} should share the staged base table: {paths}'


# ── The guard: a dispersion that cannot take effect must not run ─────────────────

def test_guard_rejects_percent_on_an_offset_table(tmp_path, projects_dir, monkeypatch):
    """"%" on X-C.P. in file mode is a percentage of a zero nominal, i.e. no dispersion at all."""
    project = copy_example(projects_dir, tmp_path / 'example')
    _enable_file_mode(project, ['XCP'])
    _set_errors(project, 4, {'XCP': ('%', 5.0)})
    monkeypatch.setattr(runner_montecarlo, '_execute_montecarlo_cases', lambda *a, **k: None)
    with chdir(str(project)):
        with pytest.raises(ValueError, match='XCP'):
            run_montecarlo('config_solver.json', 'config_montecarlo.json')


def test_guard_rejects_absolute_unit_on_a_scaled_table(tmp_path, projects_dir, monkeypatch):
    """An absolute magnitude cannot be a multiplier for a dimensionless coefficient table."""
    project = copy_example(projects_dir, tmp_path / 'example')
    _enable_file_mode(project, ['CNa'])
    _set_errors(project, 4, {'CNa': ('m', 0.02)})
    monkeypatch.setattr(runner_montecarlo, '_execute_montecarlo_cases', lambda *a, **k: None)
    with chdir(str(project)):
        with pytest.raises(ValueError, match='CNa'):
            run_montecarlo('config_solver.json', 'config_montecarlo.json')


def test_guard_reports_every_offender_at_once(tmp_path, projects_dir, monkeypatch):
    """One run reports the whole config, so a bad config is fixed in one pass."""
    project = copy_example(projects_dir, tmp_path / 'example')
    _enable_file_mode(project, ['CNa', 'Cld', 'XCP'])
    _set_errors(project, 4, {'CNa': ('m', 0.02), 'Cld': ('kg', 1.0), 'XCP': ('%', 5.0)})
    monkeypatch.setattr(runner_montecarlo, '_execute_montecarlo_cases', lambda *a, **k: None)
    with chdir(str(project)):
        with pytest.raises(ValueError) as excinfo:
            run_montecarlo('config_solver.json', 'config_montecarlo.json')
    message = str(excinfo.value)
    for name in ('CNa', 'Cld', 'XCP'):
        assert name in message, f'{name} missing from the report:\n{message}'


def test_guard_rejects_percent_on_xcg_in_file_mode(tmp_path, projects_dir, monkeypatch):
    """X-C.G. in file mode is an offset too, and "%" silently gave it zero dispersion."""
    project = copy_example(projects_dir, tmp_path / 'example')
    stage = json.loads((project / 'param_list_stage1.json').read_text())
    rocket_path = project / stage['Rocket Configuration File Path']
    rocket = json.loads(rocket_path.read_text())
    np.savetxt(project / 'base_xcg.csv', np.c_[[0.0, 10.0], [1.4, 1.5]],
               delimiter=',', fmt='%0.9f', header='Time,Xcg_fromTail', comments='')
    rocket['Enable X-C.G. File'] = True
    rocket.setdefault('X-C.G. File', {})['X-C.G. File Path'] = 'base_xcg.csv'
    rocket_path.write_text(json.dumps(rocket, indent=4))
    _set_errors(project, 4, {'XCG': ('%', 5.0)})

    monkeypatch.setattr(runner_montecarlo, '_execute_montecarlo_cases', lambda *a, **k: None)
    with chdir(str(project)):
        with pytest.raises(ValueError, match='XCG'):
            run_montecarlo('config_solver.json', 'config_montecarlo.json')


def test_guard_rejects_a_file_mode_param_with_no_file_mode_support(tmp_path, projects_dir,
                                                                  monkeypatch):
    """The forward-looking half of the guard.

    Every parameter with a file mode is dispersed through its file today, so this cannot be
    triggered by a real config — which is why the test removes CNa from the handled set to stand
    in for a parameter added to the registry later without file-mode support. That combination
    used to run to completion with the parameter held fixed; it must now refuse to start.
    """
    project = copy_example(projects_dir, tmp_path / 'example')
    _enable_file_mode(project, ['CNa'])
    _set_errors(project, 4, {'CNa': ('%', 10.0)})

    handled = dict(runner_montecarlo._FILE_MODE_DISPERSION)
    handled.pop('CNa')
    monkeypatch.setattr(runner_montecarlo, '_FILE_MODE_DISPERSION', handled)
    monkeypatch.setattr(runner_montecarlo, '_FILE_MODE_HANDLED', frozenset(handled))
    monkeypatch.setattr(runner_montecarlo, '_execute_montecarlo_cases', lambda *a, **k: None)
    with chdir(str(project)):
        with pytest.raises(ValueError, match='CNa'):
            run_montecarlo('config_solver.json', 'config_montecarlo.json')


def test_valid_file_mode_config_passes_the_guard(tmp_path, projects_dir, monkeypatch):
    """The guard must not reject the configurations it is meant to allow."""
    project = copy_example(projects_dir, tmp_path / 'example')
    _enable_file_mode(project, list(_FILE_KEYS))
    _set_errors(project, 3, {'CNa': ('%', 10.0), 'Cld': ('%', 5.0), 'XCP': ('mm', 20.0)})
    work_dir = _run(project, monkeypatch)
    assert (work_dir / 'cases' / '1_XCP.csv').is_file()


# ── Absolute error units land in the field's own unit ────────────────────────────

@pytest.mark.parametrize('unit, sigma3, expect_mm', [
    ('m', 0.02, 20.0),    # the regression: 0.02 m is 20 mm, not 0.02 mm
    ('mm', 20.0, 20.0),   # already in the field's unit: unchanged behaviour
    ('cm', 2.0, 20.0),
])
def test_scalar_xcp_absolute_error_converts_to_the_field_unit(tmp_path, projects_dir, monkeypatch,
                                                              unit, sigma3, expect_mm):
    """The constant X-C.P. field is millimetres, so an absolute error has to be converted.

    Without the conversion an "m" magnitude produced a dispersion 1000x too small — and because
    it still varied, the output looked like a working dispersion study.
    """
    project = copy_example(projects_dir, tmp_path / 'example')  # X-C.P. file mode stays off
    case_count = 300
    _set_errors(project, case_count, {'XCP': (unit, sigma3)})
    work_dir = _run(project, monkeypatch)

    values = [_case_rocket(work_dir, c)['Constant X-C.P.']['Constant X-C.P. from BodyTail [mm]']
              for c in range(1, case_count)]
    assert _realised_3sigma(values) == pytest.approx(expect_mm, rel=0.25)


def test_scalar_xcg_metre_error_converts_to_millimetres(tmp_path, projects_dir, monkeypatch):
    """X-C.G. shares the bug: metres in the config, millimetres in the constant field."""
    project = copy_example(projects_dir, tmp_path / 'example')
    case_count = 300
    _set_errors(project, case_count, {'XCG': ('m', 0.01)})
    work_dir = _run(project, monkeypatch)

    values = [_case_rocket(work_dir, c)['Constant X-C.G.']['Constant X-C.G. from BodyTail [mm]']
              for c in range(1, case_count)]
    assert _realised_3sigma(values) == pytest.approx(10.0, rel=0.25)


def test_percent_error_on_a_millimetre_field_is_unchanged(tmp_path, projects_dir, monkeypatch):
    """A "%" error is relative to the field's own value, so it needs no conversion and must
    behave exactly as before."""
    project = copy_example(projects_dir, tmp_path / 'example')
    case_count = 300
    _set_errors(project, case_count, {'XCP': ('%', 5.0)})
    stage = json.loads((project / 'param_list_stage1.json').read_text())
    nominal = json.loads((project / stage['Rocket Configuration File Path']).read_text())
    nominal_mm = nominal['Constant X-C.P.']['Constant X-C.P. from BodyTail [mm]']
    work_dir = _run(project, monkeypatch)

    values = [_case_rocket(work_dir, c)['Constant X-C.P.']['Constant X-C.P. from BodyTail [mm]']
              for c in range(1, case_count)]
    assert _realised_3sigma(values) == pytest.approx(abs(nominal_mm) * 0.05, rel=0.25)


# ── _unit_scale unit tests ───────────────────────────────────────────────────────

def test_unit_scale_converts_between_length_units():
    assert _unit_scale('m', 'mm') == pytest.approx(1000.0)
    assert _unit_scale('mm', 'mm') == pytest.approx(1.0)
    assert _unit_scale('cm', 'mm') == pytest.approx(10.0)
    assert _unit_scale('mm', 'm') == pytest.approx(0.001)
    assert _unit_scale('m', 'm') == pytest.approx(1.0)


def test_unit_scale_is_case_and_space_insensitive():
    assert _unit_scale(' M ', 'mm') == pytest.approx(1000.0)


def test_unit_scale_without_a_length_target_is_identity():
    """Angles, times, masses and dimensionless coefficients have nothing to convert."""
    assert _unit_scale('deg', None) == pytest.approx(1.0)
    assert _unit_scale('kg', None) == pytest.approx(1.0)


def test_unit_scale_warns_on_an_unknown_unit_for_a_length_target():
    """"Error Unit" has always been free-form, so an unknown unit still passes through as the
    field's own unit — but on a length target it is indistinguishable from a typo, so it warns."""
    with pytest.warns(UserWarning, match='not a known length unit'):
        assert _unit_scale('metres', 'mm', 'XCP') == pytest.approx(1.0)
