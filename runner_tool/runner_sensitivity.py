import os
import csv
import json
import shutil
from copy import deepcopy
import numpy as np
from concurrent import futures

from runner_tool.json_api import (
    get_stage_config,
    get_rocket_param, get_engine_param, get_soe,
    CA_file_is_enable, get_CA_file_name, set_CA_file_name,
    get_constant_CA, set_constant_CA,
    get_burnoutCA_file_name, set_burnoutCA_file_name, set_constant_burnoutCA,
    thrust_file_is_enable, get_thrust_file_name, set_thrust_file_name,
    get_constant_thrust, set_constant_thrust,
    xcg_file_is_enable, get_xcg_file_name, set_xcg_file_name,
    moi_file_is_enable, get_moi_file_name, set_moi_file_name,
)
from runner_tool.runner_montecarlo import _SCALAR_PARAM_REGISTRY
from runner_tool.runner_multi import run_multi
from path_define import runner_sensitivity_directory, make_unique_work_dir

# TODO: Add coupled parameter support (e.g., simultaneous Thrust + Isp variation,
#       or Thrust + propellant mass flow rate variation). Currently each parameter
#       varies independently (One-At-a-Time, OAT method).
# TODO: Add XCG sensitivity support (file-mode: absolute offset, constant-mode: direct value).
# TODO: Add MOI sensitivity support (file-mode: multiplier applied to all axes).

_AVAILABLE_PARAMS = sorted(_SCALAR_PARAM_REGISTRY.keys()) + ['Thrust', 'CA']


def _compute_param_value(nominal, variation, unit):
    """
    unit='%'  -> new = nominal * (1 + variation/100)
    unit=other -> new = nominal + variation  (absolute offset in given unit)
    """
    if unit == '%':
        return nominal * (1.0 + variation / 100.0)
    return nominal + variation


def run_sensitivity(solver_config_json_file_name, sensitivity_config_json_file_name, max_thread_run=False):
    work_dir = make_unique_work_dir(runner_sensitivity_directory)

    with open(solver_config_json_file_name) as f:
        solver_config = json.load(f)
    stage_config = get_stage_config(solver_config, 1)
    rocket_param = get_rocket_param(stage_config)
    engine_param = get_engine_param(stage_config)
    soe = get_soe(stage_config)

    with open(sensitivity_config_json_file_name) as f:
        sensitivity_config = json.load(f)

    shutil.copy(sensitivity_config_json_file_name, work_dir + '/sensitivity_config.json')

    sens_params = sensitivity_config.get('Sensitivity Parameters', [])

    # Build case definitions: (case_num, param_name, variation, unit, nominal, param_value)
    case_defs = [(0, 'nominal', 0.0, '%', None, None)]
    case_num = 1

    base_cfg = {
        'rocket_param': rocket_param,
        'engine_param': engine_param,
        'soe': soe,
        'solver_config': solver_config,
    }

    for sp in sens_params:
        param_name = sp['Name']
        unit = sp.get('Variation Unit', '%')
        variations = sp['Variations']

        if param_name in _SCALAR_PARAM_REGISTRY:
            cfg_key, getter, _ = _SCALAR_PARAM_REGISTRY[param_name]
            nominal = getter(base_cfg[cfg_key])
        elif param_name == 'Thrust':
            if thrust_file_is_enable(engine_param) and unit != '%':
                raise ValueError(
                    f'Thrust in file mode only supports Variation Unit "%", got "{unit}". '
                    'Use "%" to apply a scaling multiplier to the entire thrust curve.')
            nominal = 1.0 if thrust_file_is_enable(engine_param) else get_constant_thrust(engine_param)
        elif param_name == 'CA':
            if CA_file_is_enable(rocket_param) and unit != '%':
                raise ValueError(
                    f'CA in file mode only supports Variation Unit "%", got "{unit}". '
                    'Use "%" to apply a scaling multiplier to the entire CA curve.')
            nominal = 1.0 if CA_file_is_enable(rocket_param) else get_constant_CA(rocket_param)
        else:
            raise ValueError(
                f'Unknown sensitivity parameter: "{param_name}".\n'
                f'Available parameters: {_AVAILABLE_PARAMS}')

        for var in variations:
            case_defs.append((case_num, param_name, var, unit, nominal,
                              _compute_param_value(nominal, var, unit)))
            case_num += 1

    # Pre-load file-based arrays once (shared across threads via closure; read-only)
    ca_mach_arr = ca_base_arr = np.array([])
    if CA_file_is_enable(rocket_param):
        arr = np.loadtxt(get_CA_file_name(rocket_param), delimiter=',', skiprows=1)
        ca_mach_arr, ca_base_arr = arr[:, 0], arr[:, 1]

    thrust_time_arr = thrust_vac_arr = thrust_mdot_arr = np.array([])
    if thrust_file_is_enable(engine_param):
        arr = np.loadtxt(get_thrust_file_name(engine_param), delimiter=',', skiprows=1)
        thrust_time_arr, thrust_vac_arr, thrust_mdot_arr = arr[:, 0], arr[:, 1], arr[:, 2]

    calc_dir = 'cases'
    os.mkdir(work_dir + '/' + calc_dir)
    prefix = work_dir + '/' + calc_dir + '/'

    def _generate_case(cdef):
        cn, pname, var, unit, nominal, new_value = cdef

        sc    = deepcopy(solver_config)
        stc   = deepcopy(stage_config)
        rp    = deepcopy(rocket_param)
        ep    = deepcopy(engine_param)
        soe_c = deepcopy(soe)

        # Apply variation for the target parameter
        if pname in _SCALAR_PARAM_REGISTRY:
            cfg_key, _, setter = _SCALAR_PARAM_REGISTRY[pname]
            cfgs = {'rocket_param': rp, 'engine_param': ep, 'soe': soe_c, 'solver_config': sc}
            setter(cfgs[cfg_key], new_value)
        elif pname == 'Thrust':
            if thrust_file_is_enable(engine_param):
                mult = 1.0 + var / 100.0
                tf = f'{cn}_thrust.csv'
                np.savetxt(prefix + tf,
                           np.c_[thrust_time_arr, thrust_vac_arr * mult, thrust_mdot_arr],
                           delimiter=',', fmt='%0.5f', header='t,f,mdot', comments='')
                ep = set_thrust_file_name(ep, tf)
            else:
                ep = set_constant_thrust(ep, new_value)
        elif pname == 'CA':
            if CA_file_is_enable(rocket_param):
                mult = 1.0 + var / 100.0
                cf = f'{cn}_CA.csv'
                np.savetxt(prefix + cf,
                           np.c_[ca_mach_arr, ca_base_arr * mult],
                           delimiter=',', fmt='%0.6f', header='mach,CA', comments='')
                rp = set_CA_file_name(rp, cf)
                rp = set_burnoutCA_file_name(rp, cf)
            else:
                rp = set_constant_CA(rp, new_value)
                rp = set_constant_burnoutCA(rp, new_value)

        # Fix absolute paths for file-based parameters that are not being varied
        if CA_file_is_enable(rocket_param) and pname != 'CA':
            abs_ca = os.path.abspath(get_CA_file_name(rocket_param))
            rp = set_CA_file_name(rp, abs_ca)
            rp = set_burnoutCA_file_name(rp, abs_ca)

        if thrust_file_is_enable(engine_param) and pname != 'Thrust':
            ep = set_thrust_file_name(ep, os.path.abspath(get_thrust_file_name(engine_param)))

        if xcg_file_is_enable(rocket_param):
            rp = set_xcg_file_name(rp, os.path.abspath(get_xcg_file_name(rocket_param)))

        if moi_file_is_enable(rocket_param):
            rp = set_moi_file_name(rp, os.path.abspath(get_moi_file_name(rocket_param)))

        # Fix wind path
        wind_path = sc['Wind Condition'].get('Wind File Path', '')
        if wind_path:
            sc['Wind Condition']['Wind File Path'] = os.path.abspath(wind_path)

        # Write case JSON files
        rp_file  = f'{cn}_rocket_param.json'
        ep_file  = f'{cn}_engine_param.json'
        soe_file = f'{cn}_soe.json'
        stc_file = f'{cn}_stage_config.json'
        sc_file  = f'{cn}_solver_config.json'

        with open(prefix + rp_file, 'w') as f:
            json.dump(rp, f, indent=4)
        stc['Rocket Configuration File Path'] = rp_file

        with open(prefix + ep_file, 'w') as f:
            json.dump(ep, f, indent=4)
        stc['Engine Configuration File Path'] = ep_file

        with open(prefix + soe_file, 'w') as f:
            json.dump(soe_c, f, indent=4)
        stc['Sequence of Event File Path'] = soe_file

        with open(prefix + stc_file, 'w') as f:
            json.dump(stc, f, indent=4)
        sc['Stage1 Config File List'] = stc_file

        sc['Model ID'] = f'{cn}_{solver_config.get("Model ID", "model")}'
        with open(prefix + sc_file, 'w') as f:
            json.dump(sc, f, indent=4)

    with futures.ThreadPoolExecutor(max_workers=6) as executor:
        futs = [executor.submit(_generate_case, cdef) for cdef in case_defs]
        for fut in futures.as_completed(futs):
            fut.result()  # propagate exceptions

    with open(work_dir + '/sensitivity_case_list.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['case', 'param_name', 'variation', 'variation_unit', 'nominal_value', 'param_value'])
        for cn, pname, var, unit, nominal, new_val in case_defs:
            writer.writerow([cn, pname, var, unit,
                             '' if nominal is None else nominal,
                             '' if new_val is None else new_val])

    solver_config_file_list = [f'{cn}_solver_config.json' for cn, *_ in case_defs]
    cases_dir = os.path.abspath(work_dir + '/' + calc_dir)
    run_multi(cases_dir, solver_config_file_list, max_thread_run)

    print('Work Directory: ' + work_dir)
    return work_dir
