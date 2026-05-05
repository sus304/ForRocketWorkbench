import glob
import json
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from scipy.stats import linregress
from tqdm import tqdm

from path_define import chdir


def _extract_apogee(log_file):
    case_num = int(log_file.split('_', 1)[0])
    df = pd.read_csv(log_file, usecols=['Altitude [m]'])
    return case_num, float(df['Altitude [m]'].max())


def post_sensitivity(sensitivity_work_dir, calc_dir='cases'):
    with chdir(sensitivity_work_dir):
        with open('sensitivity_config.json') as f:
            sensitivity_config = json.load(f)

        case_list_df = pd.read_csv('sensitivity_case_list.csv')

        with chdir(calc_dir):
            log_files = [f for f in glob.glob('*_stage1_flight_log.csv')
                         if '_ballistic_' not in f]
            altitude_map = {}
            with ThreadPoolExecutor() as executor:
                fs = {executor.submit(_extract_apogee, f): f for f in log_files}
                for future in tqdm(as_completed(fs), total=len(fs), desc='Collecting results'):
                    cn, alt = future.result()
                    altitude_map[cn] = alt

        case_list_df['altitude_apogee [m]'] = case_list_df['case'].map(altitude_map)

        nominal_altitude = altitude_map.get(0)
        if nominal_altitude is None:
            raise ValueError('Nominal case (case 0) flight log not found in ' + calc_dir)

        case_list_df.to_csv('sensitivity_cases.csv', index=False, float_format='%.4f')

        method = sensitivity_config.get('Sensitivity Calculation', {}).get('Method', 'two_point')
        sp_cfg_map = {sp['Name']: sp for sp in sensitivity_config.get('Sensitivity Parameters', [])}

        sensitivity_rows = []
        param_names = [n for n in case_list_df['param_name'].unique() if n != 'nominal']

        for param_name in param_names:
            param_df = (case_list_df[case_list_df['param_name'] == param_name]
                        .dropna(subset=['altitude_apogee [m]'])
                        .copy())
            if len(param_df) < 2:
                print(f'Warning: {param_name} has fewer than 2 valid results, skipping.')
                continue

            nominal_val = float(param_df['nominal_value'].iloc[0])
            unit = param_df['variation_unit'].iloc[0]
            sp_cfg = sp_cfg_map.get(param_name, {})
            ref_vars = sp_cfg.get('Reference Variations', None)

            param_df_sorted = param_df.sort_values('variation')

            if method == 'two_point':
                if ref_vars is not None:
                    tol = 1e-9
                    lo = param_df[np.abs(param_df['variation'] - ref_vars[0]) < tol]
                    hi = param_df[np.abs(param_df['variation'] - ref_vars[1]) < tol]
                    if lo.empty or hi.empty:
                        print(f'Warning: {param_name} Reference Variations {ref_vars} '
                              'not found in Variations list; using min/max instead.')
                        lo_row, hi_row = param_df_sorted.iloc[0], param_df_sorted.iloc[-1]
                    else:
                        lo_row, hi_row = lo.iloc[0], hi.iloc[0]
                else:
                    lo_row, hi_row = param_df_sorted.iloc[0], param_df_sorted.iloc[-1]

                alt_lo  = lo_row['altitude_apogee [m]']
                alt_hi  = hi_row['altitude_apogee [m]']
                pval_lo = lo_row['param_value']
                pval_hi = hi_row['param_value']
                var_lo  = lo_row['variation']
                var_hi  = hi_row['variation']

                delta_alt   = alt_hi - alt_lo
                delta_param = pval_hi - pval_lo

                if unit == '%':
                    delta_pct = var_hi - var_lo
                else:
                    delta_pct = ((pval_hi - nominal_val) - (pval_lo - nominal_val)) / nominal_val * 100 \
                        if nominal_val != 0 else float('nan')

                sens_per_unit = delta_alt / delta_param if delta_param != 0 else float('nan')
                sens_per_pct  = delta_alt / delta_pct  if delta_pct  != 0 else float('nan')

            elif method == 'linear_fit':
                lo_row = param_df_sorted.iloc[0]
                hi_row = param_df_sorted.iloc[-1]
                alt_lo, alt_hi = lo_row['altitude_apogee [m]'], hi_row['altitude_apogee [m]']
                pval_lo, pval_hi = lo_row['param_value'], hi_row['param_value']
                var_lo, var_hi = lo_row['variation'], hi_row['variation']

                slope_unit, *_ = linregress(param_df['param_value'], param_df['altitude_apogee [m]'])

                if unit == '%':
                    slope_pct, *_ = linregress(param_df['variation'], param_df['altitude_apogee [m]'])
                else:
                    if nominal_val != 0:
                        pct_vals = (param_df['param_value'] - nominal_val) / nominal_val * 100
                    else:
                        pct_vals = param_df['variation']
                    slope_pct, *_ = linregress(pct_vals, param_df['altitude_apogee [m]'])

                sens_per_unit = slope_unit
                sens_per_pct  = slope_pct

            else:
                raise ValueError(f'Unknown Method "{method}". Use "two_point" or "linear_fit".')

            sensitivity_rows.append({
                'param_name':             param_name,
                'nominal_value':          nominal_val,
                'variation_unit':         unit,
                'sensitivity [m/unit]':   round(sens_per_unit, 4),
                'sensitivity [m/%]':      round(sens_per_pct,  4),
                'altitude_nominal [m]':   round(nominal_altitude, 3),
                'altitude_low [m]':       round(alt_lo,  3),
                'altitude_high [m]':      round(alt_hi,  3),
                'variation_low':          var_lo,
                'variation_high':         var_hi,
            })

        results_df = pd.DataFrame(sensitivity_rows)
        results_df.to_csv('sensitivity_results.csv', index=False)

        print('\n=== Sensitivity Results ===')
        cols = ['param_name', 'nominal_value', 'variation_unit',
                'sensitivity [m/unit]', 'sensitivity [m/%]',
                'altitude_nominal [m]', 'altitude_low [m]', 'altitude_high [m]']
        print(results_df[cols].to_string(index=False))

        _plot_tornado(results_df, nominal_altitude)


def _plot_tornado(results_df, nominal_altitude):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if results_df.empty:
        return

    df = results_df.copy()
    df['impact_range'] = (df['altitude_high [m]'] - df['altitude_low [m]']).abs()
    df = df.sort_values('impact_range', ascending=True)  # widest bar at bottom

    fig, ax = plt.subplots(figsize=(10, max(4, len(df) * 0.65 + 1.5)))

    for i, (_, row) in enumerate(df.iterrows()):
        lo = row['altitude_low [m]']  - nominal_altitude
        hi = row['altitude_high [m]'] - nominal_altitude
        bar_start = min(lo, hi)
        bar_width = abs(hi - lo)
        color = '#4C72B0' if hi >= lo else '#DD8452'
        ax.barh(i, bar_width, left=bar_start, height=0.6,
                color=color, alpha=0.85, edgecolor='white', linewidth=0.5)

        label_lo = f'{row["variation_low"]:+g}{row["variation_unit"]}'
        label_hi = f'{row["variation_high"]:+g}{row["variation_unit"]}'
        ax.text(bar_start - 2, i, label_lo, ha='right', va='center', fontsize=7, color='#555')
        ax.text(bar_start + bar_width + 2, i, label_hi, ha='left', va='center', fontsize=7, color='#555')

    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(df['param_name'].tolist(), fontsize=9)
    ax.set_xlabel('Apogee Altitude Change from Nominal [m]', fontsize=11)
    ax.set_title('Sensitivity Tornado Chart', fontsize=13)
    ax.axvline(0, color='black', linewidth=1.0, zorder=5)
    ax.grid(axis='x', alpha=0.3, linestyle='--')

    plt.tight_layout()
    plt.savefig('sensitivity_tornado.png', dpi=150, bbox_inches='tight')
    plt.close()
    print('Saved: sensitivity_tornado.png')
