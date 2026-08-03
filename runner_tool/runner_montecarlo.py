import os
import json
import shutil
import warnings
from copy import deepcopy
from typing import Any, NamedTuple, Optional
import numpy as np
from scipy.stats import truncnorm
from concurrent import futures

from runner_tool.json_api import copy_config_files, copy_wind_file
from runner_tool.json_api import get_stage_config, get_stage_config_file_name, set_constant_burnoutCA
from runner_tool.json_api import get_rocket_param, get_rocket_param_file_name
from runner_tool.json_api import get_engine_param, get_engine_param_file_name
from runner_tool.json_api import get_soe, get_soe_file_name

from runner_tool.json_api import get_elevation, set_elevation, get_azimuth, set_azimuth
from runner_tool.json_api import CA_file_is_enable
from runner_tool.json_api import get_CA_file_name, set_CA_file_name
from runner_tool.json_api import get_constant_CA, set_constant_CA
from runner_tool.json_api import get_burnoutCA_file_name, set_burnoutCA_file_name
from runner_tool.json_api import thrust_file_is_enable
from runner_tool.json_api import get_thrust_file_name, set_thrust_file_name
from runner_tool.json_api import get_constant_thrust, set_constant_thrust
from runner_tool.json_api import get_mass_inert, set_mass_inert
from runner_tool.json_api import get_mass_prop, set_mass_prop
from runner_tool.json_api import get_parachute_drag_factor, set_parachute_drag_factor
from runner_tool.json_api import get_parachute_open_time, set_parachute_open_time
from runner_tool.json_api import get_secondary_parachute_drag_factor, set_secondary_parachute_drag_factor
from runner_tool.json_api import get_secondary_parachute_open_time, set_secondary_parachute_open_time
from runner_tool.json_api import xcg_file_is_enable, get_xcg_file_name, set_xcg_file_name
from runner_tool.json_api import get_constant_xcg, set_constant_xcg
from runner_tool.json_api import moi_file_is_enable, get_moi_file_name, set_moi_file_name
from runner_tool.json_api import get_constant_moi_yaw, set_constant_moi_yaw
from runner_tool.json_api import get_constant_moi_pitch, set_constant_moi_pitch
from runner_tool.json_api import get_constant_moi_roll, set_constant_moi_roll
from runner_tool.json_api import get_constant_CNa, set_constant_CNa
from runner_tool.json_api import get_constant_xcp, set_constant_xcp
from runner_tool.json_api import get_constant_Cld, set_constant_Cld
from runner_tool.json_api import get_constant_Clp, set_constant_Clp
from runner_tool.json_api import get_constant_Cmq, set_constant_Cmq
from runner_tool.json_api import get_constant_Cnr, set_constant_Cnr
from runner_tool.json_api import xcp_file_is_enable, get_xcp_file_name, set_xcp_file_name
from runner_tool.json_api import CNa_file_is_enable, get_CNa_file_name, set_CNa_file_name
from runner_tool.json_api import Cld_file_is_enable, get_Cld_file_name, set_Cld_file_name
from runner_tool.json_api import Clp_file_is_enable, get_Clp_file_name, set_Clp_file_name
from runner_tool.json_api import Cmq_file_is_enable, get_Cmq_file_name, set_Cmq_file_name
from runner_tool.json_api import Cnr_file_is_enable, get_Cnr_file_name, set_Cnr_file_name
from runner_tool.json_api import get_cant_angle, set_cant_angle
from runner_tool.json_api import get_engine_miss_alignment_y, set_engine_miss_alignment_y
from runner_tool.json_api import get_engine_miss_alignment_z, set_engine_miss_alignment_z
from runner_tool.json_api import get_gas_jet_moment, set_gas_jet_moment
from runner_tool.json_api import get_gas_jet_duration, set_gas_jet_duration
from runner_tool.json_api import get_cg_offset_y, set_cg_offset_y
from runner_tool.json_api import get_cg_offset_z, set_cg_offset_z
from runner_tool.json_api import get_thrust_point_offset_y, set_thrust_point_offset_y
from runner_tool.json_api import get_thrust_point_offset_z, set_thrust_point_offset_z
from runner_tool.json_api import get_constant_poi_ixy, set_constant_poi_ixy
from runner_tool.json_api import get_constant_poi_ixz, set_constant_poi_ixz
from runner_tool.json_api import get_constant_poi_iyz, set_constant_poi_iyz
from runner_tool.json_api import poi_file_is_enable
from runner_tool.json_api import get_poi_file_ixy, set_poi_file_ixy
from runner_tool.json_api import get_poi_file_ixz, set_poi_file_ixz
from runner_tool.json_api import get_poi_file_iyz, set_poi_file_iyz

from runner_tool.runner_multi import run_multi, _make_output_validator
from runner_tool.run_manifest import RunManifest

from path_define import runner_montecarlo_directory, make_unique_work_dir


def _sample_errors(mean, std_low, std_high, size):
    """
    Split normal distribution truncated at ±3σ on each side.
    std_low/std_high are 1σ values for the below-mean and above-mean halves.
    Mixing ratio: p(below mean) = std_low / (std_low + std_high).
    """
    if std_low <= 0 and std_high <= 0:
        return np.full(size, float(mean))
    if std_low <= 0:
        return truncnorm.rvs(0, 3, loc=mean, scale=std_high, size=size)
    if std_high <= 0:
        return truncnorm.rvs(-3, 0, loc=mean, scale=std_low, size=size)
    p_low = std_low / (std_low + std_high)
    mask = np.random.random(size) < p_low
    n_low = int(mask.sum())
    samples = np.empty(size)
    if n_low > 0:
        samples[mask] = truncnorm.rvs(-3, 0, loc=mean, scale=std_low, size=n_low)
    if n_low < size:
        samples[~mask] = truncnorm.rvs(0, 3, loc=mean, scale=std_high, size=size - n_low)
    return samples


# Length units an absolute ("Error Unit" != "%") magnitude may be written in, in metres.
# A config field's unit and the error's unit are two different things: the scalar X-C.P. and
# X-C.G. fields hold millimetres (the solver divides them by 1e3) while the corresponding table
# files hold metres (used as-is). Writing a magnitude given in "m" straight into a millimetre
# field is what this table exists to prevent — it shrank the dispersion by 1000x in silence.
_LENGTH_UNITS_IN_M = {'m': 1.0, 'cm': 1e-2, 'mm': 1e-3}


def _unit_scale(error_unit, target_unit, param_name=''):
    """Factor converting an absolute error magnitude from error_unit into target_unit.

    target_unit None means the write target carries no length unit to convert against (angles,
    times, masses, dimensionless coefficients), so the magnitude is used as given. An
    unrecognised error unit also passes through unscaled: "Error Unit" has always been
    free-form documentation, so rejecting it would break configs that predate this conversion —
    but it warns, because on a length target an unknown unit and a typo look the same.
    """
    if target_unit is None:
        return 1.0
    src = _LENGTH_UNITS_IN_M.get(str(error_unit).strip().lower())
    if src is None:
        warnings.warn(
            f'{param_name or "parameter"}: Error Unit "{error_unit}" is not a known length unit '
            f'({", ".join(_LENGTH_UNITS_IN_M)}); the magnitude is taken to be in "{target_unit}" '
            f'as stored. Set Error Unit to a length unit to state the intent.')
        return 1.0
    return src / _LENGTH_UNITS_IN_M[target_unit]


def _sample_from_config(ep, mean, size, target_unit=None, param_name=''):
    """
    Sample errors using the error parameter config dict.
      "Error Unit": "%"       → std = |mean| * value/100/3  (percentage of nominal)
      "Error Unit": <length>  → std = value/3, converted into target_unit (see _unit_scale)
      "Error Unit": <other>   → std = value/3               (absolute, in the target's own unit)
    target_unit is the unit of `mean` and of the returned samples, i.e. the unit of whatever
    field or table column the caller is about to write them into.
    """
    unit = ep.get('Error Unit', '%')
    if unit == '%':
        std_low  = abs(mean) * ep['Error 3sigma Low']  / 100.0 / 3
        std_high = abs(mean) * ep['Error 3sigma High'] / 100.0 / 3
    else:
        k = _unit_scale(unit, target_unit, param_name)
        std_low  = ep['Error 3sigma Low']  * k / 3
        std_high = ep['Error 3sigma High'] * k / 3
    return _sample_errors(mean, std_low, std_high, size)


class ScalarParam(NamedTuple):
    """One dispersible scalar config field.

    cfg_key ('rocket_param' | 'engine_param' | 'soe' | 'solver_config') plus getter/setter
    locate the field; the error unit and magnitude come from the montecarlo config at runtime.

    field_unit is the unit the field itself stores, so an absolute magnitude given in another
    unit converts into it (None: nothing to convert — see _unit_scale).

    file_check, when set, reports whether the solver ignores this field entirely because the
    matching "Enable * File" is on: rocket_factory.cpp is an if/else, so in file mode the scalar
    field is dead and a dispersion written to it disappears without a trace. Every parameter
    that has one is dispersed through its file by a dedicated block below; _validate_error_params
    refuses to run any that is not, so a parameter added here later fails loudly instead.
    """
    cfg_key: str
    getter: Any
    setter: Any
    field_unit: Optional[str] = None
    file_check: Optional[Any] = None


_P = ScalarParam  # keeps the table below readable at one entry per line

_SCALAR_PARAM_REGISTRY = {
    'Launcher Azimuth':         _P('solver_config', get_azimuth,                 set_azimuth                ),
    'Launcher Elevation':       _P('solver_config', get_elevation,               set_elevation              ),
    'Propellant Mass':          _P('rocket_param',  get_mass_prop,               set_mass_prop              ),
    'Mass Inert':               _P('rocket_param',  get_mass_inert,              set_mass_inert             ),
    'CNa':                      _P('rocket_param',  get_constant_CNa,            set_constant_CNa,           file_check=CNa_file_is_enable),
    'XCP':                      _P('rocket_param',  get_constant_xcp,            set_constant_xcp,     'mm', file_check=xcp_file_is_enable),
    'Cld':                      _P('rocket_param',  get_constant_Cld,            set_constant_Cld,           file_check=Cld_file_is_enable),
    'Clp':                      _P('rocket_param',  get_constant_Clp,            set_constant_Clp,           file_check=Clp_file_is_enable),
    'Cmq':                      _P('rocket_param',  get_constant_Cmq,            set_constant_Cmq,           file_check=Cmq_file_is_enable),
    'Cnr':                      _P('rocket_param',  get_constant_Cnr,            set_constant_Cnr,           file_check=Cnr_file_is_enable),
    'Fin Cant Angle':           _P('rocket_param',  get_cant_angle,              set_cant_angle             ),
    'Engine Miss-Alignment Y':  _P('engine_param',  get_engine_miss_alignment_y, set_engine_miss_alignment_y),
    'Engine Miss-Alignment Z':  _P('engine_param',  get_engine_miss_alignment_z, set_engine_miss_alignment_z),
    'Gas Jet Moment':           _P('rocket_param',  get_gas_jet_moment,          set_gas_jet_moment         ),
    'Gas Jet Duration':         _P('rocket_param',  get_gas_jet_duration,        set_gas_jet_duration       ),
    'CG Offset Y':              _P('rocket_param',  get_cg_offset_y,             set_cg_offset_y,       'mm'),
    'CG Offset Z':              _P('rocket_param',  get_cg_offset_z,             set_cg_offset_z,       'mm'),
    'Thrust Point Offset Y':    _P('rocket_param',  get_thrust_point_offset_y,   set_thrust_point_offset_y, 'mm'),
    'Thrust Point Offset Z':    _P('rocket_param',  get_thrust_point_offset_z,   set_thrust_point_offset_z, 'mm'),
    'POI Ixy':                  _P('rocket_param',  get_constant_poi_ixy,        set_constant_poi_ixy, file_check=poi_file_is_enable),
    'POI Ixz':                  _P('rocket_param',  get_constant_poi_ixz,        set_constant_poi_ixz, file_check=poi_file_is_enable),
    'POI Iyz':                  _P('rocket_param',  get_constant_poi_iyz,        set_constant_poi_iyz, file_check=poi_file_is_enable),
    'Primary Parachute Drag':        _P('soe', get_parachute_drag_factor,           set_parachute_drag_factor          ),
    'Primary Parachute Open Time':   _P('soe', get_parachute_open_time,             set_parachute_open_time            ),
    'Secondary Parachute Drag':      _P('soe', get_secondary_parachute_drag_factor, set_secondary_parachute_drag_factor),
    'Secondary Parachute Open Time': _P('soe', get_secondary_parachute_open_time,   set_secondary_parachute_open_time  ),
}

# POI (Product of Inertia) components for file mode. Each component has its own input file
# and its own error config. In file mode a per-component multiplier (Error Unit "%") is applied
# to the file values; in constant mode POI is sampled via _SCALAR_PARAM_REGISTRY above.
#   (config key, file-path getter, file-path setter, column label)
_POI_COMPONENTS = (
    ('POI Ixy', get_poi_file_ixy, set_poi_file_ixy, 'Ixy'),
    ('POI Ixz', get_poi_file_ixz, set_poi_file_ixz, 'Ixz'),
    ('POI Iyz', get_poi_file_iyz, set_poi_file_iyz, 'Iyz'),
)
_POI_PARAM_NAMES = frozenset(c[0] for c in _POI_COMPONENTS)


class AeroFileParam(NamedTuple):
    """One aero table the solver interpolates against Mach when its "Enable * File" is on.

    In that mode the scalar field is dead (see ScalarParam.file_check), so the dispersion has to
    be applied to the table itself: write a per-case CSV and point the case config at it, the
    same shape as the CA / X-C.G. / M.I. / POI blocks in run_montecarlo.

    mode 'scale'  — the sampled multiplier scales every row; needs "Error Unit": "%".
    mode 'offset' — the sampled value is added to every row; needs an absolute length unit.

    X-C.P. is the only 'offset' entry, deliberately: its error is a physical distance, so
    scaling the table would shift the CP by an amount proportional to its distance from the
    tail and therefore differ Mach by Mach — not what a CP uncertainty of ±x m states. Its file
    values are metres (the solver interpolates them as-is, unlike the millimetre scalar field),
    hence file_unit 'm'.
    """
    name: str
    file_check: Any
    get_path: Any
    set_path: Any
    mode: str
    file_unit: Optional[str]
    header: str


# Roll/pitch/yaw damping coefficients are of order 1e-2, so the 6 decimals the CA block writes
# would leave them only four significant figures — enough quantisation to be visible when a
# realised multiplier is recovered from the table. 9 decimals covers every coefficient here.
_AERO_FMT = '%0.9f'

_AERO_FILE_PARAMS = (
    AeroFileParam('CNa', CNa_file_is_enable, get_CNa_file_name, set_CNa_file_name, 'scale',  None, 'mach,CNa'),
    AeroFileParam('Cld', Cld_file_is_enable, get_Cld_file_name, set_Cld_file_name, 'scale',  None, 'mach,Cld'),
    AeroFileParam('Clp', Clp_file_is_enable, get_Clp_file_name, set_Clp_file_name, 'scale',  None, 'mach,Clp'),
    AeroFileParam('Cmq', Cmq_file_is_enable, get_Cmq_file_name, set_Cmq_file_name, 'scale',  None, 'mach,Cmq'),
    AeroFileParam('Cnr', Cnr_file_is_enable, get_Cnr_file_name, set_Cnr_file_name, 'scale',  None, 'mach,Cnr'),
    AeroFileParam('XCP', xcp_file_is_enable, get_xcp_file_name, set_xcp_file_name, 'offset', 'm',  'mach,Xcp'),
)
_AERO_FILE_BY_NAME = {s.name: s for s in _AERO_FILE_PARAMS}

# How every file-mode dispersion applies, for validation only — the sampling itself lives in
# run_montecarlo. Keyed by error-parameter name: (mode, config the file switch is read from,
# file switch). 'scale' entries need "Error Unit": "%"; 'offset' entries need an absolute unit,
# because their nominal is zero (they perturb a whole table, so there is no single nominal
# value) and a percentage of zero is a dispersion of exactly zero — a full run that completes
# with the parameter held fixed, the same class of failure as writing a field the solver ignores.
_FILE_MODE_DISPERSION = {
    'CA':      ('scale',  'rocket_param', CA_file_is_enable),
    'MOI':     ('scale',  'rocket_param', moi_file_is_enable),
    'XCG':     ('offset', 'rocket_param', xcg_file_is_enable),
    'Thrust':  ('scale',  'engine_param', thrust_file_is_enable),
    'POI Ixy': ('scale',  'rocket_param', poi_file_is_enable),
    'POI Ixz': ('scale',  'rocket_param', poi_file_is_enable),
    'POI Iyz': ('scale',  'rocket_param', poi_file_is_enable),
}
# Derived, not hand-listed, so the aero table above stays the single source of truth.
_FILE_MODE_DISPERSION.update(
    {s.name: (s.mode, 'rocket_param', s.file_check) for s in _AERO_FILE_PARAMS})
_FILE_MODE_HANDLED = frozenset(_FILE_MODE_DISPERSION)


def _validate_error_params(error_params, rocket_param, engine_param):
    """Reject a montecarlo config whose dispersion the run would silently discard.

    Both failure modes below used to complete a full run and produce results in which the
    parameter simply did not vary — the worst kind of bug, since nothing distinguishes the
    output from a correct run:

      - the parameter's "Enable * File" is on, so the solver reads a table and never looks at
        the scalar field the sampler writes. Everything with a file mode is dispersed through
        its file now, so this only fires for a parameter added to _SCALAR_PARAM_REGISTRY later,
        which is the point: new entries are guarded by default.
      - the "Error Unit" does not fit how the dispersion applies to a table (see
        _FILE_MODE_DISPERSION): "%" on an 'offset' target yields identically zero dispersion,
        and an absolute magnitude on a 'scale' target is a meaningless multiplier.

    Collects every problem before raising, so one run reports the whole config rather than
    making the user fix offenders one at a time.
    """
    cfgs = {'rocket_param': rocket_param, 'engine_param': engine_param}
    problems = []

    for name, (mode, cfg_key, file_check) in sorted(_FILE_MODE_DISPERSION.items()):
        ep = error_params.get(name)
        if not (ep and ep.get('Enable', False) and file_check(cfgs[cfg_key])):
            continue
        unit = ep.get('Error Unit', '%')
        if mode == 'scale' and unit != '%':
            problems.append(
                f'"{name}" is in file mode, where its error scales the whole table, so '
                f'"Error Unit" must be "%" (got "{unit}").')
        elif mode == 'offset' and unit == '%':
            problems.append(
                f'"{name}" is in file mode, where its error is added to the whole table as an '
                f'absolute offset; "Error Unit": "%" would be a percentage of a zero nominal, '
                f'i.e. no dispersion at all. Give an absolute unit '
                f'({", ".join(_LENGTH_UNITS_IN_M)}).')

    for name, p in sorted(_SCALAR_PARAM_REGISTRY.items()):
        if p.file_check is None or name in _FILE_MODE_HANDLED:
            continue
        ep = error_params.get(name)
        if ep and ep.get('Enable', False) and p.file_check(rocket_param):
            problems.append(
                f'"{name}" has an error configured but its file mode is enabled, and the '
                f'montecarlo runner cannot disperse it in file mode — the solver would read the '
                f'table and ignore the sampled value, giving a run with no dispersion in '
                f'"{name}". Disable the file mode to use the constant field, or add file-mode '
                f'support for "{name}".')

    if problems:
        raise ValueError(
            'montecarlo error parameters would have no effect as configured:\n  - '
            + '\n  - '.join(problems))


class MontecarloCaseConfig:
    def __init__(self, case_number, case_solver_config_file_name):
        self.case_num = case_number
        self.solver_config_file_name = case_solver_config_file_name


def run_montecarlo(solver_config_json_file_name, montecarlo_config_json_file_name, max_thread_run=False,
                   stop_event=None, work_dir=None):
    # work_dir may be pre-created by the compute service so it knows (and persists) the run's
    # directory at start-up, the anchor for automatic resume; default None self-creates.
    if work_dir is None:
        work_dir = make_unique_work_dir(runner_montecarlo_directory)

    with open(solver_config_json_file_name) as f:
        solver_config = json.load(f)
    stage_config = get_stage_config(solver_config, 1)  # 1段のみ対応
    rocket_param = get_rocket_param(stage_config)
    engine_param = get_engine_param(stage_config)
    soe = get_soe(stage_config)

    with open(montecarlo_config_json_file_name) as f:
        montecarlo_config = json.load(f)
    case_count = montecarlo_config.get('MonteCarlo Case Count')
    error_params = montecarlo_config.get('Error Parameters')

    # Before anything is written: refuse a config whose dispersion the run would throw away.
    _validate_error_params(error_params or {}, rocket_param, engine_param)

    # 計算ディレクトリを作成
    calc_dir = 'cases'
    os.mkdir(work_dir+'/'+calc_dir)

    # ケースJSON内が相対パスで参照する設定/データファイルを cases ディレクトリへコピー
    copy_config_files(solver_config, work_dir+'/'+calc_dir)

    # ---- Wind -------------------------------------------------------
    wind_files = []
    winds_dir = ''
    if error_params.get('Wind').get('Enable'):
        zipfile_path = error_params.get('Wind').get('Wind Files Zip Path')
        if zipfile_path == '':
            raise ValueError('Wind Files Zip Path is empty')
        if not os.path.exists(zipfile_path):
            raise FileNotFoundError(zipfile_path)
        shutil.unpack_archive(zipfile_path, work_dir+'/')
        winds_dir = os.path.splitext(os.path.basename(zipfile_path))[0]
        wind_files = os.listdir(work_dir+'/'+winds_dir)
        if case_count > len(wind_files):
            extra_files = []
            for i in range(case_count - len(wind_files)):
                src = wind_files[np.random.randint(0, len(wind_files))]
                new_name = f'extra_{i}_wind.csv'
                shutil.copy(os.path.join(work_dir, winds_dir, src),
                            os.path.join(work_dir, winds_dir, new_name))
                extra_files.append(new_name)
            wind_files = wind_files + extra_files
        np.random.shuffle(wind_files)
    else:
        # Wind error disabled: every case uses the nominal wind file. Copy it into cases/ once
        # and rewrite solver_config's path to its basename so cases stay self-contained.
        copy_wind_file(solver_config, work_dir+'/'+calc_dir)

    # ---- CA ---------------------------------------------------------
    # file mode: CA_list[i] = scaled array; ca_mach_array = shared mach axis
    # constant mode: CA_list[i] = scalar
    CA_list = []
    ca_mach_array = np.array([])
    ep_ca = error_params.get('CA', {})
    if ep_ca.get('Enable'):
        if CA_file_is_enable(rocket_param):
            load_array = np.loadtxt(get_CA_file_name(rocket_param), delimiter=',', skiprows=1)
            ca_mach_array = load_array[:, 0]
            ca_base_array = load_array[:, 1]
            ca_multiplier_list = _sample_from_config(ep_ca, 1.0, case_count)
            ca_multiplier_list[0] = 1.0
            CA_list = [ca_base_array * m for m in ca_multiplier_list]
        else:
            mean = get_constant_CA(rocket_param)
            CA_list = _sample_from_config(ep_ca, mean, case_count)
            CA_list[0] = mean

    # ---- Thrust -----------------------------------------------------
    # file mode: multiplier around 1.0 applied to vacuum thrust column
    # constant mode: samples actual thrust value
    thrust_time_array = np.array([])
    thrust_mdot_array = np.array([])
    thrust_list = []
    thrust_constant_samples = None
    ep_thrust = error_params.get('Thrust', {})
    if ep_thrust.get('Enable'):
        if thrust_file_is_enable(engine_param):
            load_array = np.loadtxt(get_thrust_file_name(engine_param), delimiter=',', skiprows=1)
            thrust_time_array = load_array[:, 0]
            thrust_vac_array  = load_array[:, 1]
            thrust_mdot_array = load_array[:, 2]
            thrust_multiplier_list = _sample_from_config(ep_thrust, 1.0, case_count)
            thrust_multiplier_list[0] = 1.0
            thrust_list = [thrust_vac_array * m for m in thrust_multiplier_list]
        else:
            mean = get_constant_thrust(engine_param)
            thrust_constant_samples = _sample_from_config(ep_thrust, mean, case_count)
            thrust_constant_samples[0] = mean

    # ---- XCG --------------------------------------------------------
    # file mode: samples absolute offset (Error Unit should be file unit, e.g. "m")
    # constant mode: samples actual value (Error Unit "%", or absolute)
    xcg_samples = None
    xcg_time_array = np.array([])
    xcg_base_array = np.array([])
    ep_xcg = error_params.get('XCG', {})
    if ep_xcg.get('Enable'):
        if xcg_file_is_enable(rocket_param):
            xcg_load = np.loadtxt(get_xcg_file_name(rocket_param), delimiter=',', skiprows=1)
            xcg_time_array = xcg_load[:, 0]
            xcg_base_array = xcg_load[:, 1]
            # File values are metres; the offset is added to them directly.
            xcg_samples = _sample_from_config(ep_xcg, 0.0, case_count,
                                             target_unit='m', param_name='XCG')
            xcg_samples[0] = 0.0
        else:
            # The constant field is millimetres, so an "m" magnitude has to be converted.
            mean = get_constant_xcg(rocket_param)
            xcg_samples = _sample_from_config(ep_xcg, mean, case_count,
                                             target_unit='mm', param_name='XCG')
            xcg_samples[0] = mean

    # ---- MOI --------------------------------------------------------
    # file mode: samples multiplier applied to all axes (Error Unit "%")
    # constant mode: same multiplier applied to yaw/pitch/roll constants
    moi_samples = None
    moi_time_array = np.array([])
    moi_yaw_base   = np.array([])
    moi_pitch_base = np.array([])
    moi_roll_base  = np.array([])
    ep_moi = error_params.get('MOI', {})
    if ep_moi.get('Enable'):
        if moi_file_is_enable(rocket_param):
            moi_load = np.loadtxt(get_moi_file_name(rocket_param), delimiter=',', skiprows=1)
            moi_time_array = moi_load[:, 0]
            moi_yaw_base   = moi_load[:, 1]
            moi_pitch_base = moi_load[:, 2]
            moi_roll_base  = moi_load[:, 3]
        moi_samples = _sample_from_config(ep_moi, 1.0, case_count)  # multiplier
        moi_samples[0] = 1.0

    # ---- POI (Product of Inertia), file mode ------------------------
    # file mode: per-component multiplier around 1.0 applied to each POI file.
    # constant mode is handled by the scalar registry below (file mode is skipped there).
    # poi_jobs maps config key -> (multiplier array, time array, base value array, file setter, label)
    poi_file_mode = poi_file_is_enable(rocket_param)
    poi_jobs = {}
    if poi_file_mode:
        for _name, _file_getter, _file_setter, _comp in _POI_COMPONENTS:
            ep_poi = error_params.get(_name)
            if ep_poi is None or not ep_poi.get('Enable', False):
                continue
            poi_load = np.loadtxt(_file_getter(rocket_param), delimiter=',', skiprows=1)
            poi_mult = _sample_from_config(ep_poi, 1.0, case_count)  # multiplier
            poi_mult[0] = 1.0
            poi_jobs[_name] = (poi_mult, poi_load[:, 0], poi_load[:, 1], _file_setter, _comp)

    # ---- Aero tables in file mode (CNa/Cld/Clp/Cmq/Cnr, X-C.P.) -----
    # Mach-dependent tables the solver reads instead of the scalar field, so the dispersion has
    # to go into the table (see AeroFileParam). aero_jobs maps the error-parameter name to
    # (spec, per-case sample array, mach axis, base value array).
    aero_jobs = {}
    for _spec in _AERO_FILE_PARAMS:
        _ep_aero = error_params.get(_spec.name)
        if not (_ep_aero and _ep_aero.get('Enable', False) and _spec.file_check(rocket_param)):
            continue
        _aero_load = np.loadtxt(_spec.get_path(rocket_param), delimiter=',', skiprows=1)
        _nominal = 1.0 if _spec.mode == 'scale' else 0.0
        _aero_samples = _sample_from_config(_ep_aero, _nominal, case_count,
                                            target_unit=_spec.file_unit, param_name=_spec.name)
        _aero_samples[0] = _nominal
        aero_jobs[_spec.name] = (_spec, _aero_samples, _aero_load[:, 0], _aero_load[:, 1])

    # ---- Generic scalar parameters ----------------------------------
    scalar_samples = {}
    _base_configs = {
        'rocket_param': rocket_param,
        'engine_param': engine_param,
        'soe': soe,
        'solver_config': solver_config,
    }
    for name, p in _SCALAR_PARAM_REGISTRY.items():
        if p.file_check is not None and p.file_check(rocket_param):
            # The solver ignores this field in file mode; a dedicated block above disperses the
            # file instead (_validate_error_params already rejected anything that has neither).
            continue
        ep = error_params.get(name)
        if ep is None or not ep.get('Enable', False):
            continue
        mean = p.getter(_base_configs[p.cfg_key])
        samples = _sample_from_config(ep, mean, case_count,
                                      target_unit=p.field_unit, param_name=name)
        samples[0] = mean
        scalar_samples[name] = (samples, p.cfg_key, p.setter)

    montecarlo_case_list = [None] * case_count

    def __run(case_num):
        solver_config_case = deepcopy(solver_config)
        stage_config_case  = deepcopy(stage_config)
        rocket_param_case  = deepcopy(rocket_param)
        engine_param_case  = deepcopy(engine_param)
        soe_case           = deepcopy(soe)

        # CA
        if CA_file_is_enable(rocket_param):
            if ep_ca.get('Enable'):
                CA_file_name = str(case_num) + '_CA.csv'
                np.savetxt(work_dir+'/'+calc_dir+'/'+CA_file_name,
                           np.c_[ca_mach_array, CA_list[case_num]],
                           delimiter=',', fmt='%0.6f', header='mach,CA', comments='')
                rocket_param_case = set_CA_file_name(rocket_param_case, CA_file_name)
                rocket_param_case = set_burnoutCA_file_name(rocket_param_case, CA_file_name)
            else:
                # Not perturbed: reference the copy placed in cases/ by basename (self-contained).
                ca_base = os.path.basename(get_CA_file_name(rocket_param))
                rocket_param_case = set_CA_file_name(rocket_param_case, ca_base)
                rocket_param_case = set_burnoutCA_file_name(rocket_param_case, ca_base)
        else:
            if ep_ca.get('Enable'):
                rocket_param_case = set_constant_CA(rocket_param_case, CA_list[case_num])
                rocket_param_case = set_constant_burnoutCA(rocket_param_case, CA_list[case_num])

        # XCG
        if xcg_file_is_enable(rocket_param):
            if xcg_samples is not None:
                xcg_file_name = str(case_num) + '_xcg.csv'
                np.savetxt(work_dir+'/'+calc_dir+'/'+xcg_file_name,
                           np.c_[xcg_time_array, xcg_base_array + xcg_samples[case_num]],
                           delimiter=',', fmt='%0.9f', header='Time,Xcg_fromTail', comments='')
                rocket_param_case = set_xcg_file_name(rocket_param_case, xcg_file_name)
            else:
                rocket_param_case = set_xcg_file_name(rocket_param_case,
                                                       os.path.basename(get_xcg_file_name(rocket_param)))
        elif xcg_samples is not None:
            rocket_param_case = set_constant_xcg(rocket_param_case, xcg_samples[case_num])

        # MOI
        if moi_file_is_enable(rocket_param):
            if moi_samples is not None:
                moi_file_name = str(case_num) + '_moi.csv'
                mult = moi_samples[case_num]
                np.savetxt(work_dir+'/'+calc_dir+'/'+moi_file_name,
                           np.c_[moi_time_array,
                                 moi_yaw_base   * mult,
                                 moi_pitch_base * mult,
                                 moi_roll_base  * mult],
                           delimiter=',', fmt='%0.9f',
                           header='Time,MOI_yaw,MOI_pitch,MOI_roll', comments='')
                rocket_param_case = set_moi_file_name(rocket_param_case, moi_file_name)
            else:
                rocket_param_case = set_moi_file_name(rocket_param_case,
                                                       os.path.basename(get_moi_file_name(rocket_param)))
        elif moi_samples is not None:
            mult = moi_samples[case_num]
            rocket_param_case = set_constant_moi_yaw(rocket_param_case,
                                                      get_constant_moi_yaw(rocket_param) * mult)
            rocket_param_case = set_constant_moi_pitch(rocket_param_case,
                                                        get_constant_moi_pitch(rocket_param) * mult)
            rocket_param_case = set_constant_moi_roll(rocket_param_case,
                                                       get_constant_moi_roll(rocket_param) * mult)

        # Aero tables in file mode: write this case's table and point the case config at it.
        for _spec, _aero_samples, _mach_arr, _base_arr in aero_jobs.values():
            if _spec.mode == 'scale':
                _vals = _base_arr * _aero_samples[case_num]
            else:
                _vals = _base_arr + _aero_samples[case_num]
            _aero_file_name = str(case_num) + '_' + _spec.name + '.csv'
            np.savetxt(work_dir+'/'+calc_dir+'/'+_aero_file_name,
                       np.c_[_mach_arr, _vals],
                       delimiter=',', fmt=_AERO_FMT, header=_spec.header, comments='')
            _spec.set_path(rocket_param_case, _aero_file_name)

        # Aero tables in file mode without an enabled error: reference the copy that
        # copy_config_files() staged in cases/ by basename, so a config written with an absolute
        # path still yields a self-contained case (same treatment as the CA block above).
        for _spec in _AERO_FILE_PARAMS:
            if _spec.name in aero_jobs or not _spec.file_check(rocket_param):
                continue
            _spec.set_path(rocket_param_case, os.path.basename(_spec.get_path(rocket_param)))

        # POI (Product of Inertia), file mode: write a per-case scaled file for each
        # component whose error is enabled. Components without an enabled error keep the
        # file already copied into the cases directory by copy_config_files().
        for _poi_mult, _poi_t, _poi_v, _poi_setter, _poi_comp in poi_jobs.values():
            poi_file_name = str(case_num) + '_poi_' + _poi_comp + '.csv'
            np.savetxt(work_dir+'/'+calc_dir+'/'+poi_file_name,
                       np.c_[_poi_t, _poi_v * _poi_mult[case_num]],
                       delimiter=',', fmt='%0.9f',
                       header='Time,' + _poi_comp, comments='')
            _poi_setter(rocket_param_case, poi_file_name)

        # Thrust
        if thrust_file_is_enable(engine_param):
            if ep_thrust.get('Enable'):
                thrust_csv_file_name = str(case_num) + '_thrust.csv'
                np.savetxt(work_dir+'/'+calc_dir+'/'+thrust_csv_file_name,
                           np.c_[thrust_time_array, thrust_list[case_num], thrust_mdot_array],
                           delimiter=',', fmt='%0.5f', header='t,f,mdot', comments='')
                engine_param_case = set_thrust_file_name(engine_param_case, thrust_csv_file_name)
            else:
                engine_param_case = set_thrust_file_name(engine_param_case,
                                                          os.path.basename(get_thrust_file_name(engine_param)))
        elif thrust_constant_samples is not None:
            engine_param_case = set_constant_thrust(engine_param_case, thrust_constant_samples[case_num])

        # Wind
        if error_params.get('Wind').get('Enable'):
            nominal_wind = solver_config.get('Wind Condition', {}).get('Wind File Path', '')
            if case_num == 0 and nominal_wind and os.path.exists(nominal_wind):
                # Case 0 is the nominal case, so it uses the nominal wind (from solver_config)
                # rather than a dispersion sample, matching how every other error parameter pins
                # case 0 to its nominal value. copy_wind_file stages the nominal wind into cases/
                # by basename and rewrites this case's path; wind_files[0] is left unused.
                # (No nominal wind configured / file missing: fall through to a dispersion sample
                # so a wind-only dispersion setup keeps working.)
                copy_wind_file(solver_config_case, work_dir+'/'+calc_dir)
            else:
                wind_file_name = wind_files[case_num]
                shutil.copy(work_dir+'/'+winds_dir+'/'+wind_file_name,
                            work_dir+'/'+calc_dir+'/'+wind_file_name)
                solver_config_case['Wind Condition']['Wind File Path'] = wind_file_name
        # else: the nominal wind was copied into cases/ and rewritten to its basename before
        # the pool (copy_wind_file); the deepcopy carries that basename, so nothing to do here.
        solver_config_case['Wind Condition']['Enable Wind'] = True

        # Generic scalar parameters (azimuth, elevation, masses, aero coeffs, parachute, etc.)
        _case_configs = {
            'rocket_param': rocket_param_case,
            'engine_param': engine_param_case,
            'soe':          soe_case,
            'solver_config': solver_config_case,
        }
        for _n, (_s, _ck, _setter) in scalar_samples.items():
            _setter(_case_configs[_ck], _s[case_num])

        # JSON書き出し
        rocket_param_file_name  = str(case_num) + '_rocket_param.json'
        engine_param_file_name  = str(case_num) + '_engine_param.json'
        soe_file_name           = str(case_num) + '_soe.json'
        stage_config_file_name  = str(case_num) + '_stage_config.json'
        solver_config_file_name = str(case_num) + '_solver_config.json'

        with open(work_dir+'/'+calc_dir+'/'+rocket_param_file_name, 'w') as f:
            json.dump(rocket_param_case, f, indent=4)
        stage_config_case['Rocket Configuration File Path'] = rocket_param_file_name

        with open(work_dir+'/'+calc_dir+'/'+engine_param_file_name, 'w') as f:
            json.dump(engine_param_case, f, indent=4)
        stage_config_case['Engine Configuration File Path'] = engine_param_file_name

        with open(work_dir+'/'+calc_dir+'/'+soe_file_name, 'w') as f:
            json.dump(soe_case, f, indent=4)
        stage_config_case['Sequence of Event File Path'] = soe_file_name

        with open(work_dir+'/'+calc_dir+'/'+stage_config_file_name, 'w') as f:
            json.dump(stage_config_case, f, indent=4)
        solver_config_case['Stage1 Config File List'] = stage_config_file_name

        solver_config_case['Model ID'] = str(case_num) + '_' + solver_config.get('Model ID')
        with open(work_dir+'/'+calc_dir+'/'+solver_config_file_name, 'w') as f:
            json.dump(solver_config_case, f, indent=4)

        montecarlo_case_list[case_num] = MontecarloCaseConfig(case_num, solver_config_file_name)

    future_list = []
    with futures.ThreadPoolExecutor(max_workers=6) as executor:
        for i in range(case_count):
            future = executor.submit(__run, i)
            future_list.append(future)
        for fut in futures.as_completed(future_list):
            fut.result()  # propagate exceptions

    case_solver_config_file_name_list = [case.solver_config_file_name for case in montecarlo_case_list]

    _execute_montecarlo_cases(work_dir, case_solver_config_file_name_list,
                              montecarlo_config, max_thread_run, stop_event=stop_event)
    ##############################################################


def _execute_montecarlo_cases(work_dir, case_solver_config_file_name_list,
                              montecarlo_config, max_thread_run, stop_event=None):
    """Run (or resume) the per-case solvers for a Monte Carlo work dir.

    Shared by the fresh-run path and resume_montecarlo(). A RunManifest makes this
    idempotent: cases already recorded complete are skipped, so calling it again on the
    same work_dir after an interruption runs only the remaining cases. stop_event, when
    set during the run, pauses cleanly after in-flight cases finish.
    """
    cases_dir = os.path.abspath(work_dir + '/cases')

    # 既定: 全ケースのフライトログを残す（従来動作）。
    # False の場合は「統計のみ出力」モード: 1ケース完了ごとに統計を抽出してログを即削除し、
    # 同時にディスク上に存在するログを抑える（解析時間・ディスク容量に制約がある場合向け）。
    manifest = RunManifest(os.path.abspath(work_dir))

    output_all_logs = montecarlo_config.get('Output All Case Logs', True)
    if output_all_logs:
        # keep-logs mode: on resume, re-run any case recorded complete whose CSV is
        # missing/empty (torn by a power loss), so post never reads an empty file.
        # Build the validator from a single scan of cases/ (O(files)); the per-case glob it
        # replaces made resume O(cases x files) and stalled on 10k-case runs. run_multi calls it
        # only during the resume decision, before any case runs, so the snapshot is current.
        run_multi(cases_dir, case_solver_config_file_name_list, max_thread_run,
                  manifest=manifest, stop_event=stop_event,
                  output_validator=_make_output_validator(cases_dir))
    else:
        import glob as _glob
        import pandas as _pd
        from post_tool.post_summary import post_summary_for_montecarlo
        from post_tool.post_montecarlo import _MC_COLS, CaseMetricsWriter

        # Persist each case's metrics as it completes (instead of once at the end) so an
        # interrupted long run keeps the metrics gathered so far. The writer is thread-safe.
        metrics_writer = CaseMetricsWriter(os.path.abspath(work_dir))

        def _extract_and_delete(cdir, solver_config_file_name):
            case_num = int(os.path.basename(solver_config_file_name).split('_', 1)[0])
            for log_path in _glob.glob(os.path.join(cdir, f'{case_num}_*_stage1_flight_log.csv')):
                is_ballistic = '_ballistic_' in os.path.basename(log_path)
                df = _pd.read_csv(log_path, usecols=_MC_COLS)
                metrics = post_summary_for_montecarlo(df)
                metrics_writer.append(case_num, is_ballistic, metrics)
                os.remove(log_path)

        run_multi(cases_dir, case_solver_config_file_name_list, max_thread_run,
                  on_case_complete=_extract_and_delete, manifest=manifest, stop_event=stop_event)

    print('Work Directory: ' + work_dir)


def _enumerate_case_solver_configs(cases_dir):
    """Primary per-case solver-config file names in cases_dir, ordered by case number.

    Excludes the *_ballistic.json variants generated per case at run time; only the
    primary `<n>_solver_config.json` files are the units run_multi drives.
    """
    import re
    pat = re.compile(r'(\d+)_solver_config\.json$')
    found = []
    for f in os.listdir(cases_dir):
        m = pat.fullmatch(f)
        if m:
            found.append((int(m.group(1)), f))
    found.sort()
    return [f for _, f in found]


def _reconcile_metrics_with_manifest(work_dir):
    """Drop case_metrics rows for cases NOT recorded complete in the manifest.

    The manifest is the source of truth for completion (it is written last, after the
    metrics row). A case interrupted between "metrics appended" and "marked complete"
    leaves an orphan row; pruning it before resume prevents a duplicate row when that
    case re-runs. No-op when there is no metrics file (full-log mode).
    """
    import pandas as _pd
    from post_tool.post_montecarlo import CASE_METRICS_FILE

    metrics_path = os.path.join(work_dir, CASE_METRICS_FILE)
    if not os.path.exists(metrics_path):
        return
    done_cases = {int(n.split('_', 1)[0]) for n in RunManifest(os.path.abspath(work_dir)).completed()}
    df = _pd.read_csv(metrics_path)
    kept = df[df['case'].isin(done_cases)]
    if len(kept) != len(df):
        kept.to_csv(metrics_path, index=False)


def resume_montecarlo(montecarlo_config_json_file_name, work_dir, max_thread_run=False,
                      stop_event=None):
    """Resume an interrupted Monte Carlo run in an existing work_dir.

    The per-case inputs were materialized (and the MC samples realized) by the original
    run, so they are reused as-is — the statistical population is unchanged. Only cases
    not yet recorded complete in the manifest are re-run. The montecarlo config is read
    solely for the "Output All Case Logs" mode flag; the error parameters are NOT
    re-sampled.
    """
    with open(montecarlo_config_json_file_name) as f:
        montecarlo_config = json.load(f)

    cases_dir = os.path.abspath(work_dir + '/cases')
    if not os.path.isdir(cases_dir):
        raise FileNotFoundError(f'cases directory not found under work_dir: {cases_dir}')

    case_solver_config_file_name_list = _enumerate_case_solver_configs(cases_dir)
    if not case_solver_config_file_name_list:
        raise FileNotFoundError(f'no per-case solver configs found in {cases_dir}')

    _reconcile_metrics_with_manifest(os.path.abspath(work_dir))

    print(f'Resuming Monte Carlo run in {work_dir} '
          f'({len(case_solver_config_file_name_list)} cases total)')
    _execute_montecarlo_cases(work_dir, case_solver_config_file_name_list,
                              montecarlo_config, max_thread_run, stop_event=stop_event)
