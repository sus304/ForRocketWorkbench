import os
import json
import shutil
from copy import deepcopy
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

from runner_tool.runner_multi import run_multi, _case_output_valid
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


def _sample_from_config(ep, mean, size):
    """
    Sample errors using the error parameter config dict.
      "Error Unit": "%"  → std = |mean| * value/100/3   (percentage of nominal)
      "Error Unit": <str> → std = value/3                (absolute, unit is documentation only)
    """
    unit = ep.get('Error Unit', '%')
    if unit == '%':
        std_low  = abs(mean) * ep['Error 3sigma Low']  / 100.0 / 3
        std_high = abs(mean) * ep['Error 3sigma High'] / 100.0 / 3
    else:
        std_low  = ep['Error 3sigma Low']  / 3
        std_high = ep['Error 3sigma High'] / 3
    return _sample_errors(mean, std_low, std_high, size)


# Registry for scalar error parameters.
# Each entry: (config_key, getter, setter)
#   config_key: 'rocket_param' | 'engine_param' | 'soe' | 'solver_config'
# Error unit and magnitude come from the montecarlo config at runtime.
# Note: file-based variants (Enable *File = true) are not supported via this registry; for
# constant mode the registry samples directly, while POI also has a dedicated file-mode
# block below (see _POI_COMPONENTS). Other params remain constant-mode only.
_SCALAR_PARAM_REGISTRY = {
    'Launcher Azimuth':         ('solver_config', get_azimuth,                         set_azimuth                        ),
    'Launcher Elevation':       ('solver_config', get_elevation,                       set_elevation                      ),
    'Propellant Mass':          ('rocket_param',  get_mass_prop,                       set_mass_prop                      ),
    'Mass Inert':               ('rocket_param',  get_mass_inert,                      set_mass_inert                     ),
    'CNa':                      ('rocket_param',  get_constant_CNa,                    set_constant_CNa                   ),
    'XCP':                      ('rocket_param',  get_constant_xcp,                    set_constant_xcp                   ),
    'Cld':                      ('rocket_param',  get_constant_Cld,                    set_constant_Cld                   ),
    'Clp':                      ('rocket_param',  get_constant_Clp,                    set_constant_Clp                   ),
    'Cmq':                      ('rocket_param',  get_constant_Cmq,                    set_constant_Cmq                   ),
    'Cnr':                      ('rocket_param',  get_constant_Cnr,                    set_constant_Cnr                   ),
    'Fin Cant Angle':           ('rocket_param',  get_cant_angle,                      set_cant_angle                     ),
    'Engine Miss-Alignment Y':  ('engine_param',  get_engine_miss_alignment_y,         set_engine_miss_alignment_y        ),
    'Engine Miss-Alignment Z':  ('engine_param',  get_engine_miss_alignment_z,         set_engine_miss_alignment_z        ),
    'Gas Jet Moment':           ('rocket_param',  get_gas_jet_moment,                  set_gas_jet_moment                 ),
    'Gas Jet Duration':         ('rocket_param',  get_gas_jet_duration,                set_gas_jet_duration               ),
    'CG Offset Y':              ('rocket_param',  get_cg_offset_y,                     set_cg_offset_y                    ),
    'CG Offset Z':              ('rocket_param',  get_cg_offset_z,                     set_cg_offset_z                    ),
    'Thrust Point Offset Y':    ('rocket_param',  get_thrust_point_offset_y,           set_thrust_point_offset_y          ),
    'Thrust Point Offset Z':    ('rocket_param',  get_thrust_point_offset_z,           set_thrust_point_offset_z          ),
    'POI Ixy':                  ('rocket_param',  get_constant_poi_ixy,                set_constant_poi_ixy               ),
    'POI Ixz':                  ('rocket_param',  get_constant_poi_ixz,                set_constant_poi_ixz               ),
    'POI Iyz':                  ('rocket_param',  get_constant_poi_iyz,                set_constant_poi_iyz               ),
    'Primary Parachute Drag':        ('soe', get_parachute_drag_factor,           set_parachute_drag_factor          ),
    'Primary Parachute Open Time':   ('soe', get_parachute_open_time,             set_parachute_open_time            ),
    'Secondary Parachute Drag':      ('soe', get_secondary_parachute_drag_factor, set_secondary_parachute_drag_factor),
    'Secondary Parachute Open Time': ('soe', get_secondary_parachute_open_time,   set_secondary_parachute_open_time  ),
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
            xcg_samples = _sample_from_config(ep_xcg, 0.0, case_count)  # offset from nominal
            xcg_samples[0] = 0.0
        else:
            mean = get_constant_xcg(rocket_param)
            xcg_samples = _sample_from_config(ep_xcg, mean, case_count)
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

    # ---- Generic scalar parameters ----------------------------------
    scalar_samples = {}
    _base_configs = {
        'rocket_param': rocket_param,
        'engine_param': engine_param,
        'soe': soe,
        'solver_config': solver_config,
    }
    for name, (cfg_key, getter, setter) in _SCALAR_PARAM_REGISTRY.items():
        if name in _POI_PARAM_NAMES and poi_file_mode:
            continue  # POI in file mode is handled by the dedicated poi_jobs block
        ep = error_params.get(name)
        if ep is None or not ep.get('Enable', False):
            continue
        mean = getter(_base_configs[cfg_key])
        samples = _sample_from_config(ep, mean, case_count)
        samples[0] = mean
        scalar_samples[name] = (samples, cfg_key, setter)

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
        run_multi(cases_dir, case_solver_config_file_name_list, max_thread_run,
                  manifest=manifest, stop_event=stop_event,
                  output_validator=lambda f: _case_output_valid(cases_dir, f))
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
