import os
import glob
import threading
import numpy as np
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor

from post_tool.post_summary import post_summary_for_montecarlo, post_3sigma_summary
from post_tool.post_ellipse import (DEFAULT_K, EllipseError, convention_label,
                                    ellipse_latlon, envelope_latlon, fit_impact_ellipse,
                                    write_ellipse_summary)
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


# Single per-case pass reads each flight log ONCE with the union of the metric and IIP
# columns. The previous pipeline read every log twice (metrics pass + IIP pass) through
# ThreadPoolExecutor, whose GIL contention made post ~4x slower than even a serial loop
# (VM measurement 2026-07-19: 187s for 2000 cases / 7.5GB vs ~49s serial; per-case cost is
# ~70% CSV parsing). One read + ProcessPoolExecutor puts the parse on all cores.
_NEEDED_COLS = frozenset(_MC_COLS) | frozenset(IIP_INPUT_COLUMNS)


def _process_case_full(args):
    """Process one flight log end-to-end: read once, extract metrics, and (gated) write the
    IIP time-history CSV next to it. Top-level and picklable for ProcessPoolExecutor
    (Windows spawn re-imports the module, so this must not live in a closure).

    args: (log_path, iip, iip_min_apogee); log_path must be absolute so the worker does not
    depend on the parent's cwd. Returns a dict; status 'empty' flags a torn/empty case CSV
    (e.g. power loss), which is skipped rather than failing the whole post (resume re-runs
    such a case, so this is a safety net)."""
    log_path, iip, iip_min_apogee = args
    name = os.path.basename(log_path)
    out = {'file': name, 'case': int(name.split('_', 1)[0]),
           'ballistic': '_ballistic_' in name}
    try:
        df = pd.read_csv(log_path, usecols=lambda c: c in _NEEDED_COLS)
    except (pd.errors.EmptyDataError, pd.errors.ParserError):
        out['status'] = 'empty'
        return out
    out['status'] = 'ok'
    out['metrics'] = post_summary_for_montecarlo(df)
    # IIP: ECI 列を持たない（minimum_dump 等の）ログ、頂点高度ゲート未満はスキップ。
    if not has_iip_input(df.columns):
        out['iip'] = 'no_eci'
    elif not should_run_iip(df, iip, iip_min_apogee):
        out['iip'] = 'small'
    else:
        write_iip_log(df, log_path.rsplit('_flight_log.csv', 1)[0])
        out['iip'] = 'written'
    return out


def _post_worker_count(max_thread_run=False):
    """Physical cores by default (like runner_multi: parse is memory-heavy and SMT
    oversubscription does not pay); logical with max_thread_run."""
    try:
        import psutil
        n = psutil.cpu_count(logical=max_thread_run)
    except Exception:  # noqa: BLE001 — psutil is a dependency, but never fail post over it
        n = None
    return n or os.cpu_count() or 1


# Below this many logs a serial loop beats paying the pool's process start-up + import cost
# (also keeps the many small-N tests fast). Real MC runs are far above it.
_SERIAL_THRESHOLD = 16


def _run_case_pipeline(log_file_list, iip=None, iip_min_apogee=IIP_MIN_APOGEE_M,
                       max_thread_run=False):
    """Run _process_case_full over every log (single read per case), in parallel across
    processes for real workloads. Returns the list of per-case result dicts."""
    jobs = [(os.path.abspath(f), iip, iip_min_apogee) for f in sorted(log_file_list)]
    workers = _post_worker_count(max_thread_run)
    if len(jobs) <= _SERIAL_THRESHOLD or workers == 1:
        results = [_process_case_full(j) for j in jobs]
    else:
        chunk = max(1, len(jobs) // (workers * 8))
        with ProcessPoolExecutor(max_workers=workers) as executor:
            results = list(tqdm(executor.map(_process_case_full, jobs, chunksize=chunk),
                                total=len(jobs)))

    empty = sum(1 for r in results if r['status'] == 'empty')
    if empty:
        print(f'Warning: skipped {empty} empty/unreadable case log(s)')
    counts = _iip_counts(results)
    if counts['no_eci']:
        print(f"IIP: {counts['no_eci']}/{len(results)} 件は ECI 列が無くスキップ")
    if counts['small']:
        print(f"IIP: {counts['small']}/{len(results)} 件は頂点高度がしきい値未満でスキップ")
    return results


def _iip_counts(results):
    """Tally the per-case IIP outcomes from _run_case_pipeline results."""
    return {key: sum(1 for r in results if r.get('iip') == key)
            for key in ('written', 'no_eci', 'small')}


def _metric_lists(results, ballistic):
    """Rebuild the 16 per-case metric lists (sorted by case) for one scenario from the
    pipeline results — the shape _save_impact_results() consumes."""
    rows = sorted(((r['case'],) + r['metrics'] for r in results
                   if r['status'] == 'ok' and r['ballistic'] == ballistic),
                  key=lambda x: x[0])
    cols = list(zip(*rows)) if rows else [[] for _ in range(16)]
    return tuple(list(c) for c in cols)


def _write_dispersion_ellipse(impact_points, prefix, k=DEFAULT_K):
    """Fit the impact-dispersion ellipse once, then write the ellipse KML, the rectangle that
    circumscribes it, and the fit diagnostics.

    Both KMLs carry the containment convention in their name/description: the file name only
    says "3sigma", which a reader will take for the 1-D 99.73% and which neither file contains.
    """
    try:
        fit = fit_impact_ellipse([p[0] for p in impact_points], [p[1] for p in impact_points])
    except EllipseError as err:
        print(f"落下分散楕円: 算出できませんでした（{err}）")
        return None

    conv = convention_label(k)
    dump_montecarlo_envelop_kml(
        envelope_latlon(fit, k), prefix,
        name=f"Impact dispersion envelope (k={k:g})",
        description=("Rectangle circumscribing the impact dispersion ellipse, aligned with the "
                     f"ellipse principal axes — not the ellipse itself, and it contains more "
                     f"than the ellipse does. Ellipse convention: {conv}."))
    dump_montecarlo_envelop_kml(
        ellipse_latlon(fit, k), (prefix + '_ellipse') if prefix else 'ellipse',
        name=f"Impact dispersion ellipse (k={k:g})",
        description=(f"Impact dispersion covariance ellipse. {conv}. This is NOT the 99.73% of "
                     f"the 1-D 3-sigma values in the *_summary.txt of the same run."))

    diag = write_ellipse_summary(fit, prefix, k)
    print(f"落下分散楕円: {conv} / 実測包含率 {diag['containment_empirical']:.2f}% "
          f"(n={fit.n}, 半長軸 {k * fit.sigma_a:.1f} m, 半短軸 {k * fit.sigma_b:.1f} m, "
          f"主軸方位 {fit.azimuth_deg:.1f} deg)")
    for w in diag['warnings']:
        print(f"落下分散楕円 警告: {w}")
    return fit


def _save_impact_results(case_numbers, maxQ, max_mach, time_apogee, altitude, vel_apogee,
                         downrange, impact_points, prefix,
                         peak_total_aoa=None, aoa_launch_clear=None,
                         peak_spin_rate=None, spin_rate_burnout=None,
                         min_sg=None, min_resonance_ratio=None,
                         max_trim_aoa=None, max_lateral_aero_load=None):
    """Write result_table.csv, envelope KMLs, and 3-sigma summary for one scenario."""
    _write_dispersion_ellipse(impact_points, prefix)
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
            # 単一パス: 各 flight_log を1回だけ読み、メトリクス抽出と（ログ非削除モードの）
            # per-case IIP 時間履歴 CSV 書き出しを同じ読みで済ませる。
            log_file_list = [f for f in glob.glob('*_flight_log.csv') if '_stage1_' in f]
            results = _run_case_pipeline(log_file_list, iip=iip, iip_min_apogee=iip_min_apogee,
                                         max_thread_run=max_thread_run)

        exist_decent = any(r['ballistic'] for r in results if r['status'] == 'ok')

        (case_numbers, maxQ, max_mach, time_apogee, altitude,
         vel_apogee, impact_points, downrange,
         peak_total_aoa, aoa_launch_clear, peak_spin_rate, spin_rate_burnout,
         min_sg, min_resonance_ratio, max_trim_aoa, max_lateral_aero_load) = _metric_lists(results, ballistic=False)

        # results are written in montecarlo_work_dir (one level above cases/)
        if exist_decent:
            (b_case_numbers, b_maxQ, b_max_mach, b_time_apogee, b_altitude,
             b_vel_apogee, b_impact_points, b_downrange,
             b_peak_total_aoa, b_aoa_launch_clear, b_peak_spin_rate, b_spin_rate_burnout,
             b_min_sg, b_min_resonance_ratio, b_max_trim_aoa, b_max_lateral_aero_load) = _metric_lists(results, ballistic=True)
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
