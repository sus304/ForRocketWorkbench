import os
import glob
import threading
import numpy as np
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

from post_tool.post_summary import post_summary_for_montecarlo, post_3sigma_summary
from post_tool.post_ellipse import get_ellipse_points
from post_tool.post_kml import dump_montecarlo_points_kml, dump_montecarlo_envelop_kml
from post_tool.post_iip import (write_iip_log, has_iip_input, should_run_iip,
                                 IIP_INPUT_COLUMNS, IIP_MIN_APOGEE_M)

from path_define import chdir

# Statistics-only mode: per-case metrics are extracted during the run and persisted
# here (one row per case), so the heavy per-case flight logs need not be kept.
CASE_METRICS_FILE = 'case_metrics.csv'

# Column order mirrors the per-case tuple from post_summary_for_montecarlo(),
# with pos_landing flattened into lat_impact / lon_impact.
_CASE_METRICS_HEADER = [
    'type', 'case', 'maxQ', 'mach', 'time_apogee', 'altitude_apogee', 'vel_apogee',
    'lat_impact', 'lon_impact', 'downrange_impact',
    'peak_total_aoa', 'aoa_launch_clear', 'peak_spin_rate', 'spin_rate_burnout',
    'min_sg', 'min_resonance_ratio', 'max_trim_aoa', 'max_lateral_aero_load',
]

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


def _metrics_row(case_num, is_ballistic, m):
    """Build one CASE_METRICS_FILE row dict from a post_summary_for_montecarlo() tuple."""
    (dyn_q, mach, t_apogee, alt, vel_apogee, pos_landing, downrange,
     peak_aoa, aoa_lc, peak_spin, spin_bo, min_sg, min_res, max_trim, max_lat) = m
    return {
        'type': 'ballistic' if is_ballistic else 'stage1',
        'case': int(case_num), 'maxQ': dyn_q, 'mach': mach,
        'time_apogee': t_apogee, 'altitude_apogee': alt, 'vel_apogee': vel_apogee,
        'lat_impact': pos_landing[0], 'lon_impact': pos_landing[1],
        'downrange_impact': downrange,
        'peak_total_aoa': peak_aoa, 'aoa_launch_clear': aoa_lc,
        'peak_spin_rate': peak_spin, 'spin_rate_burnout': spin_bo,
        'min_sg': min_sg, 'min_resonance_ratio': min_res,
        'max_trim_aoa': max_trim, 'max_lateral_aero_load': max_lat,
    }


def write_case_metrics(work_dir, collected):
    """Persist per-case Monte Carlo metrics (statistics-only mode) to CASE_METRICS_FILE.

    collected: list of (case_number, is_ballistic, metrics_tuple), where metrics_tuple
    is the return value of post_summary_for_montecarlo() for that case's flight log.
    Written to work_dir so the later post phase can rebuild the statistics without the
    (already deleted) per-case flight logs.
    """
    rows = [_metrics_row(case_num, is_ballistic, m) for case_num, is_ballistic, m in collected]
    df = pd.DataFrame(rows, columns=_CASE_METRICS_HEADER)
    df.sort_values(['type', 'case'], inplace=True)
    df.to_csv(os.path.join(work_dir, CASE_METRICS_FILE), index=False)


class CaseMetricsWriter:
    """Incrementally persist per-case metrics (statistics-only mode), appending one row
    as each case completes instead of writing all rows once at the end.

    This bounds the loss from an interrupted long run to the case currently in flight:
    the metrics gathered so far are already on disk. Rows are appended in completion
    order (not case order); the post phase sorts by case on read, so order does not
    matter. Thread-safe: workers call :meth:`append` concurrently.
    """

    def __init__(self, work_dir):
        self.path = os.path.join(work_dir, CASE_METRICS_FILE)
        self._lock = threading.Lock()

    def append(self, case_num, is_ballistic, m):
        df = pd.DataFrame([_metrics_row(case_num, is_ballistic, m)], columns=_CASE_METRICS_HEADER)
        with self._lock:
            write_header = not os.path.exists(self.path)
            df.to_csv(self.path, mode='a', header=write_header, index=False)


def _process_one_case(log_file, kml_suffix=''):
    case_number = int(log_file.split('_', 1)[0])
    try:
        df = pd.read_csv(log_file, usecols=_MC_COLS)
    except (pd.errors.EmptyDataError, pd.errors.ParserError):
        # Empty/corrupt case CSV (e.g. torn by a power loss). Skip it rather than fail the
        # whole post; resume normally re-runs such a case, so this is a safety net.
        return None
    result = post_summary_for_montecarlo(df)
    return (case_number,) + result


def _write_case_iip_logs(log_file_list, iip=None, iip_min_apogee=IIP_MIN_APOGEE_M):
    """ログ非削除モード専用: 各ケースの flight_log から IIP 時間履歴 CSV
    (`<case>_iip_log.csv`) を flight_log の隣に書き出す。

    iip=None は頂点高度ゲート（小型ロケットはケース毎に自動スキップ）。
    ECI 列を持たない（minimum_dump 等の）ログはスキップする。
    戻り値: (written, skipped_no_eci, skipped_small)。"""
    def _one(log_file):
        try:
            df = pd.read_csv(log_file, usecols=lambda c: c in IIP_INPUT_COLUMNS)
        except (pd.errors.EmptyDataError, pd.errors.ParserError):
            return 'empty'  # torn/empty case CSV; skip rather than fail the whole post
        if not has_iip_input(df.columns):
            return 'no_eci'
        if not should_run_iip(df, iip, iip_min_apogee):
            return 'small'
        write_iip_log(df, log_file.rsplit('_flight_log.csv', 1)[0])
        return 'written'

    with ThreadPoolExecutor() as executor:
        results = list(tqdm(executor.map(_one, log_file_list), total=len(log_file_list)))
    written = sum(1 for r in results if r == 'written')
    skipped_no_eci = sum(1 for r in results if r == 'no_eci')
    skipped_small = sum(1 for r in results if r == 'small')
    skipped_empty = sum(1 for r in results if r == 'empty')
    if skipped_no_eci:
        print(f'IIP: {skipped_no_eci}/{len(results)} 件は ECI 列が無くスキップ')
    if skipped_small:
        print(f'IIP: {skipped_small}/{len(results)} 件は頂点高度がしきい値未満でスキップ')
    if skipped_empty:
        print(f'IIP: {skipped_empty}/{len(results)} 件は空/破損ログでスキップ')
    return written, skipped_no_eci, skipped_small


def _collect_case_results(log_file_list, kml_suffix=''):
    """Process flight log files in parallel; return collected per-case metrics."""
    results = []
    skipped = 0
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_process_one_case, f, kml_suffix): f for f in log_file_list}
        for future in tqdm(as_completed(futures), total=len(log_file_list)):
            r = future.result()
            if r is None:  # empty/corrupt case CSV was skipped
                skipped += 1
                continue
            results.append(r)
    if skipped:
        print(f'Warning: skipped {skipped} empty/unreadable case log(s)')
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


def _lists_from_metrics(sub_df):
    """Rebuild the per-case metric lists (sorted by case) from a CASE_METRICS_FILE subframe.

    Returns the same set of lists that _collect_case_results() produces, so the existing
    _save_impact_results() can be reused unchanged.
    """
    sub_df = sub_df.sort_values('case')
    impact_points = [[lat, lon] for lat, lon in zip(sub_df['lat_impact'], sub_df['lon_impact'])]
    return {
        'case_numbers':          sub_df['case'].astype(int).tolist(),
        'maxQ':                  sub_df['maxQ'].tolist(),
        'max_mach':              sub_df['mach'].tolist(),
        'time_apogee':           sub_df['time_apogee'].tolist(),
        'altitude':              sub_df['altitude_apogee'].tolist(),
        'vel_apogee':            sub_df['vel_apogee'].tolist(),
        'impact_points':         impact_points,
        'downrange':             sub_df['downrange_impact'].tolist(),
        'peak_total_aoa':        sub_df['peak_total_aoa'].tolist(),
        'aoa_launch_clear':      sub_df['aoa_launch_clear'].tolist(),
        'peak_spin_rate':        sub_df['peak_spin_rate'].tolist(),
        'spin_rate_burnout':     sub_df['spin_rate_burnout'].tolist(),
        'min_sg':                sub_df['min_sg'].tolist(),
        'min_resonance_ratio':   sub_df['min_resonance_ratio'].tolist(),
        'max_trim_aoa':          sub_df['max_trim_aoa'].tolist(),
        'max_lateral_aero_load': sub_df['max_lateral_aero_load'].tolist(),
    }


def _save_from_metrics(d, prefix):
    _save_impact_results(d['case_numbers'], d['maxQ'], d['max_mach'], d['time_apogee'],
                         d['altitude'], d['vel_apogee'], d['downrange'], d['impact_points'], prefix,
                         d['peak_total_aoa'], d['aoa_launch_clear'], d['peak_spin_rate'], d['spin_rate_burnout'],
                         d['min_sg'], d['min_resonance_ratio'], d['max_trim_aoa'], d['max_lateral_aero_load'])


def _post_montecarlo_from_metrics(montecarlo_work_dir):
    """Statistics-only post: build result tables / KMLs / 3-sigma summary from
    CASE_METRICS_FILE when the per-case flight logs were not kept."""
    with chdir(montecarlo_work_dir):
        df = pd.read_csv(CASE_METRICS_FILE)
        nominal = df[df['type'] == 'stage1']
        ballistic = df[df['type'] == 'ballistic']

        if len(ballistic) > 0:
            _save_from_metrics(_lists_from_metrics(nominal), 'decent')
            _save_from_metrics(_lists_from_metrics(ballistic), 'ballistic')
        else:
            _save_from_metrics(_lists_from_metrics(nominal), '')


def post_montecarlo(montecarlo_work_dir, montecarlo_calc_dir='cases/', max_thread_run=False,
                    iip=None, iip_min_apogee=IIP_MIN_APOGEE_M):
    # Statistics-only mode: per-case flight logs were extracted and deleted during the run,
    # leaving only CASE_METRICS_FILE. Rebuild the statistics from it.
    if os.path.exists(os.path.join(montecarlo_work_dir, CASE_METRICS_FILE)):
        _post_montecarlo_from_metrics(montecarlo_work_dir)
        return

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

            # ログ非削除モードでのみ: 各ケースの IIP 時間履歴 CSV を cases/ 内に書き出す
            _write_case_iip_logs(log_file_list, iip=iip, iip_min_apogee=iip_min_apogee)

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
