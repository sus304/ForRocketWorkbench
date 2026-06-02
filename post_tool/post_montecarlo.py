import glob
import numpy as np
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

from post_tool.post_summary import post_summary_for_montecarlo, post_3sigma_summary
from post_tool.post_ellipse import get_ellipse_points
from post_tool.post_kml import dump_montecarlo_points_kml, dump_montecarlo_envelop_kml

from path_define import chdir

_MC_COLS = [
    'Time [s]', 'Altitude [m]', 'Downrange [m]',
    'Latitude [deg]', 'Longitude [deg]',
    'Vx-body [m/s]', 'Vy-body [m/s]', 'Vz-body [m/s]',
    'DynamicPressure [kPa]', 'MachNumber [-]',
    'TotalAoA [deg]', 'AngleVelx [deg/s]',
    'Burning [0/1]', 'Fz-gravity [N]',
    'GyroStabilityFactor Sg [-]', 'ResonanceRatio [-]',
    'TrimAoA [deg]', 'LateralAeroLoad [N]',
]


def _process_one_case(log_file, kml_suffix=''):
    case_number = int(log_file.split('_', 1)[0])
    df = pd.read_csv(log_file, usecols=_MC_COLS)
    result = post_summary_for_montecarlo(df)
    return (case_number,) + result


def _collect_case_results(log_file_list, kml_suffix=''):
    """Process flight log files in parallel; return collected per-case metrics."""
    results = []
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_process_one_case, f, kml_suffix): f for f in log_file_list}
        for future in tqdm(as_completed(futures), total=len(log_file_list)):
            results.append(future.result())
    results.sort(key=lambda x: x[0])

    case_numbers              = [r[0]  for r in results]
    maxQ_list                 = [r[1]  for r in results]
    max_mach_list             = [r[2]  for r in results]
    time_apogee_list          = [r[3]  for r in results]
    altitude_list             = [r[4]  for r in results]
    vel_apogee_list           = [r[5]  for r in results]
    impact_points             = [r[6]  for r in results]
    downrange_list            = [r[7]  for r in results]
    peak_total_aoa_list       = [r[8]  for r in results]
    aoa_launch_clear_list     = [r[9]  for r in results]
    peak_spin_rate_list       = [r[10] for r in results]
    spin_rate_burnout_list    = [r[11] for r in results]
    min_sg_list               = [r[12] for r in results]
    min_resonance_ratio_list  = [r[13] for r in results]
    max_trim_aoa_list         = [r[14] for r in results]
    max_lateral_aero_load_list = [r[15] for r in results]
    return (case_numbers, maxQ_list, max_mach_list, time_apogee_list, altitude_list,
            vel_apogee_list, impact_points, downrange_list,
            peak_total_aoa_list, aoa_launch_clear_list, peak_spin_rate_list, spin_rate_burnout_list,
            min_sg_list, min_resonance_ratio_list, max_trim_aoa_list, max_lateral_aero_load_list)


def _save_impact_results(case_numbers, maxQ, max_mach, time_apogee, altitude, vel_apogee,
                         downrange, impact_points, prefix,
                         peak_total_aoa=None, aoa_launch_clear=None,
                         peak_spin_rate=None, spin_rate_burnout=None,
                         min_sg=None, min_resonance_ratio=None,
                         max_trim_aoa=None, max_lateral_aero_load=None):
    """Write result_table.csv, envelope KMLs, and 3-sigma summary for one scenario."""
    envelope_pts, ellipse_pts = get_ellipse_points(impact_points)
    dump_montecarlo_envelop_kml(envelope_pts, prefix)
    dump_montecarlo_envelop_kml(ellipse_pts, (prefix + '_ellipse') if prefix else 'ellipse')
    dump_montecarlo_points_kml(impact_points, case_numbers, prefix)

    lat_list = [p[0] for p in impact_points]
    lon_list = [p[1] for p in impact_points]

    extra = [
        (peak_total_aoa,        'peak_total_aoa'),
        (aoa_launch_clear,      'aoa_launch_clear'),
        (peak_spin_rate,        'peak_spin_rate'),
        (spin_rate_burnout,     'spin_rate_burnout'),
        (min_sg,                'min_sg'),
        (min_resonance_ratio,   'min_resonance_ratio'),
        (max_trim_aoa,          'max_trim_aoa'),
        (max_lateral_aero_load, 'max_lateral_aero_load'),
    ]

    cols = [case_numbers, maxQ, max_mach, time_apogee, altitude, vel_apogee, downrange, lat_list, lon_list]
    header = 'case,maxQ,mach,time_apogee,altitude_apogee,vel_apogee,downrange_impact,lat_impact,lon_impact'
    fmt = ['%d'] + ['%0.6f'] * 8

    for data, name in extra:
        if data is not None:
            cols.append(data)
            header += f',{name}'
            fmt.append('%0.6f')

    output = np.c_[cols].T
    fname = (prefix + '_result_table.csv') if prefix else 'result_table.csv'
    np.savetxt(fname, output, fmt=fmt, delimiter=',', header=header, comments='')
    post_3sigma_summary(case_numbers, maxQ, max_mach, time_apogee, altitude, vel_apogee, downrange, prefix,
                        peak_total_aoa, aoa_launch_clear, peak_spin_rate, spin_rate_burnout,
                        min_sg, min_resonance_ratio, max_trim_aoa, max_lateral_aero_load)


def post_montecarlo(montecarlo_work_dir, montecarlo_calc_dir='cases/', max_thread_run=False):
    with chdir(montecarlo_work_dir):
        with chdir(montecarlo_calc_dir):
            log_file_list = glob.glob('*_flight_log.csv')

            stage1_log_file_list = []
            stage1_ballistic_log_file_list = []
            for file in log_file_list:
                if '_stage1_' in file:
                    if '_ballistic_' in file:
                        stage1_ballistic_log_file_list.append(file)
                    else:
                        stage1_log_file_list.append(file)

            exist_decent = len(stage1_ballistic_log_file_list) > 0

            (case_numbers, maxQ, max_mach, time_apogee, altitude,
             vel_apogee, impact_points, downrange,
             peak_total_aoa, aoa_launch_clear, peak_spin_rate, spin_rate_burnout,
             min_sg, min_resonance_ratio, max_trim_aoa, max_lateral_aero_load) = _collect_case_results(stage1_log_file_list)

            if exist_decent:
                (b_case_numbers, b_maxQ, b_max_mach, b_time_apogee, b_altitude,
                 b_vel_apogee, b_impact_points, b_downrange,
                 b_peak_total_aoa, b_aoa_launch_clear, b_peak_spin_rate, b_spin_rate_burnout,
                 b_min_sg, b_min_resonance_ratio, b_max_trim_aoa, b_max_lateral_aero_load) = _collect_case_results(
                    stage1_ballistic_log_file_list, kml_suffix='_ballistic')

        # results are written in montecarlo_work_dir (one level above cases/)
        if exist_decent:
            _save_impact_results(case_numbers, maxQ, max_mach, time_apogee, altitude,
                                 vel_apogee, downrange, impact_points, 'decent',
                                 peak_total_aoa, aoa_launch_clear, peak_spin_rate, spin_rate_burnout,
                                 min_sg, min_resonance_ratio, max_trim_aoa, max_lateral_aero_load)
            _save_impact_results(b_case_numbers, b_maxQ, b_max_mach, b_time_apogee, b_altitude,
                                 b_vel_apogee, b_downrange, b_impact_points, 'ballistic',
                                 b_peak_total_aoa, b_aoa_launch_clear, b_peak_spin_rate, b_spin_rate_burnout,
                                 b_min_sg, b_min_resonance_ratio, b_max_trim_aoa, b_max_lateral_aero_load)
        else:
            _save_impact_results(case_numbers, maxQ, max_mach, time_apogee, altitude,
                                 vel_apogee, downrange, impact_points, '',
                                 peak_total_aoa, aoa_launch_clear, peak_spin_rate, spin_rate_burnout,
                                 min_sg, min_resonance_ratio, max_trim_aoa, max_lateral_aero_load)
