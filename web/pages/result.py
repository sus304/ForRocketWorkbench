import glob
import json as _json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from nicegui import ui, app

from web.db.database import get_session
from web.db.models import Calculation
from web.pages.shared import build_header

_PRESETS = [
    ('Altitude',    'Time [s]',      'Altitude [m]'),
    ('Mach',        'Time [s]',      'MachNumber [-]'),
    ('MaxQ',        'Time [s]',      'DynamicPressure [kPa]'),
    ('G-Load',      'Time [s]',      'Gccx-body [G]'),
    ('AoA',         'Time [s]',      'AoA [deg]'),
    ('Downrange',   'Time [s]',      'Downrange [m]'),
    ('Trajectory',  'Downrange [m]', 'Altitude [m]'),
    ('Total AoA',   'Time [s]',      'TotalAoA [deg]'),
    ('Resonance Λ', 'Time [s]',      'ResonanceRatio [-]'),
    ('Gyro Sg',     'Time [s]',      'GyroStabilityFactor Sg [-]'),
    ('Spin Freq',   'Time [s]',      'SpinFreq [Hz]'),
]

_D = {
    'bg': '#121212', 'plot': '#1a1a2e', 'line': '#42a5f5',
    'ax': '#90a4ae', 'grid': '#2a2a2a', 'border': '#444',
}

_SUMMARY_SECTIONS = [
    ('Launcher Clear', 'rocket_launch'),
    ('Max Q',          'compress'),
    ('Max Speed',      'speed'),
    ('Max Mach',       'air'),
    ('Apogee',         'arrow_upward'),
    ('Landing',        'flag'),
]

_EVENT_COLORS = {
    'Launcher Clear': '#4caf50',
    'Max Q':          '#ff9800',
    'Max Speed':      '#00bcd4',
    'Max Mach':       '#9c27b0',
    'Apogee':         '#e91e63',
    'Landing':        '#f44336',
}

_CESIUM_VERSION = '1.104'


# ── DB helpers ───────────────────────────────────────────────────────────────

def _update_memo(calc_id: int, memo: str):
    session = get_session()
    try:
        calc = session.get(Calculation, calc_id)
        if calc:
            calc.memo = memo
            session.commit()
    finally:
        session.close()


# ── File finders ─────────────────────────────────────────────────────────────

def _find_flight_logs(result_dir: str) -> list[str]:
    if not result_dir or not os.path.isdir(result_dir):
        return []
    files: list[str] = []
    for pat in ['*_flight_log.csv', 'result_*/*_flight_log.csv']:
        files.extend(sorted(glob.glob(os.path.join(result_dir, pat))))
    seen: set[str] = set()
    unique: list[str] = []
    for f in files:
        stem = Path(f).stem
        if stem not in seen:
            seen.add(stem)
            unique.append(f)
    return unique


def _find_summaries(result_dir: str) -> list[str]:
    if not result_dir or not os.path.isdir(result_dir):
        return []
    return sorted(glob.glob(os.path.join(result_dir, 'result_*', '_summary.txt')))


def _parse_summary(path: str) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                comma = line.find(',')
                if comma < 0:
                    continue
                key = line[:comma].strip()
                rest = line[comma + 1:].strip()
                if rest.endswith(']'):
                    b = rest.rfind('[')
                    if b > 0:
                        value, unit = rest[:b].strip(), rest[b:]
                    else:
                        value, unit = rest, ''
                else:
                    value, unit = rest, ''
                items.append((key, value, unit))
    except Exception:
        pass
    return items


def _get_event_positions(
    items: list[tuple[str, str, str]],
    df: pd.DataFrame,
) -> list[tuple[str, float, float, float]]:
    """Return [(label, lat, lon, alt_m)] for key events that have a time in the summary."""
    if 'Time [s]' not in df.columns or 'Latitude [deg]' not in df.columns:
        return []
    has_alt = 'Altitude [m]' in df.columns
    seen: set[str] = set()
    events: list[tuple[str, float, float, float]] = []
    for sec_label, _ in _SUMMARY_SECTIONS:
        if sec_label in seen:
            continue
        for key, val, unit in items:
            if key.startswith(sec_label) and '[s]' in unit:
                try:
                    t = float(val)
                    idx = (df['Time [s]'] - t).abs().idxmin()
                    row = df.loc[idx]
                    alt = float(row['Altitude [m]']) if has_alt else 0.0
                    label = f'{sec_label}: {val} {unit}'
                    events.append((label, float(row['Latitude [deg]']), float(row['Longitude [deg]']), alt))
                    seen.add(sec_label)
                    break
                except (ValueError, KeyError):
                    pass
    return events


# ── Chart helpers ─────────────────────────────────────────────────────────────

def _auto_km(col: str, values: list) -> tuple[list, str]:
    """If column is in [m] and abs-max ≥ 10 km, rescale to km and rename label."""
    if not col.endswith('[m]'):
        return values, col
    vmax = max((abs(v) for v in values if v is not None and not pd.isna(v)), default=0.0)
    if vmax < 10_000.0:
        return values, col
    scaled = [None if v is None or pd.isna(v) else v * 1e-3 for v in values]
    return scaled, col[:-3] + '[km]'


def _echart_opts(df: pd.DataFrame, x_col: str, y_col: str) -> dict:
    xs, x_label = _auto_km(x_col, df[x_col].tolist())
    ys, y_label = _auto_km(y_col, df[y_col].tolist())
    data = list(zip(xs, ys))
    d = _D
    return {
        'backgroundColor': d['bg'],
        'animation': False,
        'tooltip': {
            'trigger': 'axis',
            'backgroundColor': '#1e1e2e',
            'borderColor': d['border'],
            'textStyle': {'color': '#ccc', 'fontSize': 11},
        },
        'toolbox': {
            'show': True, 'right': 10, 'top': 5, 'itemSize': 14,
            'iconStyle': {'borderColor': d['ax']},
            'emphasis': {'iconStyle': {'borderColor': '#fff'}},
            'feature': {
                'dataZoom': {'yAxisIndex': 'none'},
                'restore': {},
                'saveAsImage': {'pixelRatio': 2},
            },
        },
        'dataZoom': [
            {'type': 'inside'},
            {
                'type': 'slider', 'height': 18, 'bottom': 4,
                'borderColor': d['border'],
                'fillerColor': 'rgba(66,165,245,0.15)',
                'handleStyle': {'color': d['line']},
                'textStyle': {'color': d['ax'], 'fontSize': 9},
            },
        ],
        'grid': {'top': '6%', 'left': '10%', 'right': '3%', 'bottom': '18%'},
        'xAxis': {
            'type': 'value', 'name': x_label,
            'nameLocation': 'middle', 'nameGap': 28,
            'nameTextStyle': {'color': d['ax'], 'fontSize': 11},
            'axisLabel': {'color': d['ax'], 'fontSize': 10},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
        },
        'yAxis': {
            'type': 'value', 'name': y_label,
            'nameLocation': 'middle', 'nameGap': 55, 'nameRotate': 90,
            'nameTextStyle': {'color': d['ax'], 'fontSize': 11},
            'axisLabel': {'color': d['ax'], 'fontSize': 10},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
        },
        'series': [{
            'type': 'line', 'name': y_label, 'data': data,
            'showSymbol': False,
            'lineStyle': {'color': d['line'], 'width': 2},
            'sampling': 'lttb',
        }],
    }


# ── Page ─────────────────────────────────────────────────────────────────────

@ui.page('/result/{calc_id}')
def result_page(calc_id: int):
    build_header()

    session = get_session()
    try:
        calc = session.get(Calculation, calc_id)
        if not calc:
            ui.label('Calculation not found.').classes('text-negative q-pa-md')
            return
        project_name = calc.project.name if calc.project else '—'
        result_dir   = calc.result_dir or ''
        mode         = calc.mode
        model_name   = calc.model_name or '—'
        status       = calc.status
        error_msg    = getattr(calc, 'error_message', '') or ''
        started      = calc.started_at.strftime('%Y-%m-%d %H:%M:%S') if calc.started_at else '—'
        finished     = calc.finished_at.strftime('%Y-%m-%d %H:%M:%S') if calc.finished_at else '—'
        memo_value   = calc.memo or ''
    finally:
        session.close()

    with ui.column().classes('q-pa-md w-full'):
        with ui.row().classes('items-center q-mb-md'):
            ui.button('← Back', on_click=lambda: ui.navigate.to('/')).props('flat')
            ui.label(f'Result #{calc_id}').classes('text-h6 q-ml-sm')

        # ── Error ────────────────────────────────────────────────────────────
        if status == 'failed':
            with ui.card().classes('w-full q-mb-md').style('border:1px solid #c62828'):
                with ui.row().classes('items-center q-gutter-sm q-mb-xs'):
                    ui.icon('error_outline', size='1.4rem').classes('text-negative')
                    ui.label('Calculation Failed').classes('text-subtitle1 text-negative')
                if error_msg:
                    ui.separator()
                    ui.label(error_msg).classes('text-caption').style(
                        'white-space:pre-wrap;word-break:break-all;font-family:monospace'
                    )

        # ── Metadata ─────────────────────────────────────────────────────────
        with ui.card().classes('w-full q-mb-md'):
            with ui.grid(columns=4).classes('w-full'):
                for label, value in [
                    ('Mode', mode), ('Project', project_name),
                    ('Model ID', model_name), ('Status', status),
                    ('Started', started), ('Finished', finished),
                ]:
                    with ui.column().classes('q-pa-xs'):
                        ui.label(label).classes('text-caption text-grey')
                        ui.label(value).classes('text-body2 text-weight-medium')

        # ── Memo ─────────────────────────────────────────────────────────────
        with ui.card().classes('w-full q-mb-md'):
            ui.label('Memo').classes('text-subtitle2')
            memo_input = ui.textarea(value=memo_value).classes('w-full')
            ui.button(
                'Save Memo',
                on_click=lambda: (_update_memo(calc_id, memo_input.value),
                                  ui.notify('Memo saved.', type='positive')),
            ).props('color=primary flat')

        # ── Result directory ─────────────────────────────────────────────────
        with ui.card().classes('w-full q-mb-md'):
            ui.label('Result Directory').classes('text-subtitle2')
            if result_dir:
                ui.label(result_dir).classes('text-caption text-grey q-mt-xs')
                if os.path.isdir(result_dir):
                    ui.button('Open Folder',
                              on_click=lambda: os.startfile(result_dir)
                              ).props('flat icon=folder_open color=primary')
            else:
                ui.label('No result directory recorded.').classes('text-caption text-grey')

        # ── Summary ──────────────────────────────────────────────────────────
        summary_files = _find_summaries(result_dir)
        summary_items: list[tuple[str, str, str]] = []
        if summary_files:
            summary_items = _parse_summary(summary_files[0])
            _build_summary_card(summary_files)

        # ── Sensitivity results ───────────────────────────────────────────────
        if mode == 'sensitivity':
            _build_sensitivity_card(result_dir)

        # ── Monte Carlo statistics ────────────────────────────────────────────
        if mode == 'montecarlo':
            for mc_label, mc_path in _find_mc_result_tables(result_dir):
                try:
                    df_mc = pd.read_csv(mc_path)
                    _build_mc_card(df_mc, mc_label)
                except Exception as exc:
                    with ui.card().classes('w-full q-mb-md'):
                        ui.label(f'MC stats error: {exc}').classes('text-negative text-caption')

        # ── Ground-track map ─────────────────────────────────────────────────
        csv_files = _find_flight_logs(result_dir)
        df: pd.DataFrame | None = None
        if csv_files:
            try:
                df = pd.read_csv(csv_files[0]).dropna(how='any', axis=1)
            except Exception:
                df = None

        if df is not None and 'Latitude [deg]' in df.columns and 'Longitude [deg]' in df.columns:
            _build_map_card(df, calc_id, summary_items)

        # ── 3-D trajectory (CesiumJS) ─────────────────────────────────────────
        if df is not None and 'Latitude [deg]' in df.columns and 'Altitude [m]' in df.columns:
            _build_cesium_card(df, summary_items, calc_id)

        # ── Interactive graph ─────────────────────────────────────────────────
        if csv_files:
            try:
                _build_graph_card(csv_files, df)
            except Exception as exc:
                with ui.card().classes('w-full'):
                    ui.label(f'Graph error: {exc}').classes('text-negative')


# ── Summary card ─────────────────────────────────────────────────────────────

def _build_summary_card(summary_files: list[str]):
    with ui.card().classes('w-full q-mb-md'):
        ui.label('Flight Summary').classes('text-subtitle2 q-mb-sm')
        for path in summary_files:
            items = _parse_summary(path)
            if not items:
                continue
            if len(summary_files) > 1:
                ui.label(Path(path).parent.name).classes('text-caption text-grey q-mb-xs')

            buckets: dict[str, list[tuple[str, str, str]]] = {}
            leftovers: list[tuple[str, str, str]] = []
            for key, val, unit in items:
                matched = False
                for sec_label, _ in _SUMMARY_SECTIONS:
                    if key.startswith(sec_label):
                        short = key[len(sec_label):].strip() or key
                        buckets.setdefault(sec_label, []).append((short, val, unit))
                        matched = True
                        break
                if not matched:
                    leftovers.append((key, val, unit))

            for sec_label, icon in _SUMMARY_SECTIONS:
                sec_items = buckets.get(sec_label)
                if not sec_items:
                    continue
                time_hint = next(
                    (f'{v} {u}' for k, v, u in sec_items if '[s]' in u),
                    sec_items[0][1] + (' ' + sec_items[0][2] if sec_items[0][2] else ''),
                ).strip()
                header = f'{sec_label}   {time_hint}'
                with ui.expansion(header, icon=icon).classes('w-full'):
                    with ui.grid(columns=2).classes('w-full q-pa-xs q-col-gutter-sm'):
                        for sk, v, u in sec_items:
                            with ui.row().classes('items-baseline q-gutter-xs'):
                                ui.label((sk + ':') if sk else '').classes('text-caption text-grey')
                                ui.label(v).classes('text-body2 text-weight-medium')
                                if u:
                                    ui.label(u).classes('text-caption text-grey')

            if leftovers:
                with ui.expansion('Other', icon='more_horiz').classes('w-full'):
                    with ui.grid(columns=2).classes('w-full q-pa-xs q-col-gutter-sm'):
                        for k, v, u in leftovers:
                            with ui.row().classes('items-baseline q-gutter-xs'):
                                ui.label(k + ':').classes('text-caption text-grey')
                                ui.label(v).classes('text-body2 text-weight-medium')
                                if u:
                                    ui.label(u).classes('text-caption text-grey')


# ── Sensitivity helpers ───────────────────────────────────────────────────────

def _sensitivity_tornado_opts(df: pd.DataFrame) -> dict:
    nominal = float(df['altitude_nominal [m]'].iloc[0])
    dc = df.copy()
    dc['lo_delta'] = dc['altitude_low [m]'] - nominal
    dc['hi_delta'] = dc['altitude_high [m]'] - nominal
    dc['range']    = (dc['hi_delta'] - dc['lo_delta']).abs()
    dc = dc.sort_values('range', ascending=True)

    params  = dc['param_name'].tolist()
    offsets = [float(min(r.lo_delta, r.hi_delta)) for _, r in dc.iterrows()]
    widths  = [float(abs(r.hi_delta - r.lo_delta))  for _, r in dc.iterrows()]
    colors  = ['#42a5f5' if r.hi_delta >= r.lo_delta else '#ffa726' for _, r in dc.iterrows()]
    width_data = [{'value': w, 'itemStyle': {'color': c}} for w, c in zip(widths, colors)]

    d = _D
    return {
        'backgroundColor': d['bg'],
        'animation': False,
        'title': {'text': 'Sensitivity Tornado Chart',
                  'textStyle': {'color': d['ax'], 'fontSize': 12},
                  'left': 'center', 'top': 4},
        'tooltip': {'trigger': 'axis', 'axisPointer': {'type': 'shadow'},
                    'backgroundColor': '#1e1e2e', 'borderColor': d['border'],
                    'textStyle': {'color': '#ccc', 'fontSize': 10}},
        'grid': {'top': 36, 'left': '22%', 'right': '8%', 'bottom': 36},
        'xAxis': {
            'type': 'value',
            'name': 'Apogee Change from Nominal [m]',
            'nameLocation': 'middle', 'nameGap': 28,
            'nameTextStyle': {'color': d['ax'], 'fontSize': 10},
            'axisLabel': {'color': '#546e7a', 'fontSize': 9},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
        },
        'yAxis': {
            'type': 'category', 'data': params,
            'axisLabel': {'color': d['ax'], 'fontSize': 9},
            'axisLine': {'lineStyle': {'color': d['border']}},
        },
        'series': [
            {
                'type': 'bar', 'stack': 'tornado',
                'data': offsets,
                'itemStyle': {'color': 'transparent'},
                'emphasis': {'disabled': True},
                'tooltip': {'show': False},
            },
            {
                'type': 'bar', 'stack': 'tornado',
                'data': width_data,
                'markLine': {
                    'symbol': ['none', 'none'],
                    'data': [{'xAxis': 0}],
                    'lineStyle': {'color': '#ffffff', 'width': 1.5, 'type': 'solid'},
                    'label': {'show': False},
                    'animation': False,
                },
            },
        ],
    }


def _sensitivity_linearity_opts(sens_row: 'pd.Series', cases_df: 'pd.DataFrame') -> dict:
    """
    Build a linearity-check chart for one parameter.

    X axis  : param_value  (actual physical value, from sensitivity_cases.csv)
    Y axis  : altitude [m]
    Points  : all computed variations — orange★ for Reference Variations, blue● for others
    Nominal : green ◆
    Line    : linear slope anchored on the two Reference Variation points
    """
    param_name  = str(sens_row['param_name'])
    nominal_val = float(sens_row['nominal_value'])
    y_nom       = float(sens_row['altitude_nominal [m]'])
    slope       = float(sens_row['sensitivity [m/unit]'])
    unit        = str(sens_row.get('variation_unit', ''))
    var_lo_ref  = float(sens_row['variation_low'])
    var_hi_ref  = float(sens_row['variation_high'])

    param_cases = (cases_df[cases_df['param_name'] == param_name]
                   .dropna(subset=['altitude_apogee [m]', 'param_value'])
                   .sort_values('param_value')
                   .copy())
    if param_cases.empty:
        return {}

    tol = 1e-9
    ref_mask = (
        (np.abs(param_cases['variation'] - var_lo_ref) < tol) |
        (np.abs(param_cases['variation'] - var_hi_ref) < tol)
    )
    reg_cases = param_cases[~ref_mask]
    ref_cases = param_cases[ref_mask]

    reg_pts = [[float(r['param_value']), float(r['altitude_apogee [m]'])]
               for _, r in reg_cases.iterrows()]
    ref_pts = [[float(r['param_value']), float(r['altitude_apogee [m]'])]
               for _, r in ref_cases.iterrows()]

    # Anchor linear line on the low reference point
    ref_lo_rows = param_cases[np.abs(param_cases['variation'] - var_lo_ref) < tol]
    if not ref_lo_rows.empty:
        x_anc = float(ref_lo_rows.iloc[0]['param_value'])
        y_anc = float(ref_lo_rows.iloc[0]['altitude_apogee [m]'])
    else:
        x_anc, y_anc = nominal_val, y_nom

    # ── Axis ranges: nominal at centre, symmetric ────────────────────────────
    all_x = [p[0] for p in reg_pts + ref_pts] + [nominal_val]
    x_half = max(abs(x - nominal_val) for x in all_x)
    x_half = x_half * 1.20 if x_half > 0 else 1.0
    x_axis_min = nominal_val - x_half
    x_axis_max = nominal_val + x_half

    # Line endpoints span the full x axis range
    xl0, xl1 = x_axis_min, x_axis_max
    yl0 = y_anc + slope * (xl0 - x_anc)
    yl1 = y_anc + slope * (xl1 - x_anc)

    all_y = [p[1] for p in reg_pts + ref_pts] + [y_nom, yl0, yl1]
    y_half = max(abs(y - y_nom) for y in all_y)
    y_half = y_half * 1.20 if y_half > 0 else 1.0
    y_axis_min = y_nom - y_half
    y_axis_max = y_nom + y_half

    d = _D
    return {
        'backgroundColor': d['bg'],
        'animation': False,
        'title': {
            'text': param_name,
            'textStyle': {'color': d['ax'], 'fontSize': 10},
            'left': 'center', 'top': 2,
        },
        'tooltip': {
            'trigger': 'item',
            'formatter': 'function(p){return p.seriesName+"<br/>x="+p.value[0].toPrecision(5)+"<br/>alt="+p.value[1].toFixed(1)+"m"}',
            'backgroundColor': '#1e1e2e', 'borderColor': d['border'],
            'textStyle': {'color': '#ccc', 'fontSize': 9},
        },
        'legend': {
            'show': True, 'bottom': 0,
            'textStyle': {'color': '#888', 'fontSize': 8},
            'itemWidth': 10, 'itemHeight': 8,
        },
        'grid': {'top': 28, 'left': '18%', 'right': '5%', 'bottom': 36},
        'xAxis': {
            'type': 'value',
            'name': unit,
            'nameLocation': 'end',
            'nameTextStyle': {'color': d['ax'], 'fontSize': 8},
            'axisLabel': {'color': '#546e7a', 'fontSize': 7},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
            'min': x_axis_min,
            'max': x_axis_max,
        },
        'yAxis': {
            'type': 'value',
            'name': 'Alt [m]',
            'nameLocation': 'end',
            'nameTextStyle': {'color': d['ax'], 'fontSize': 8},
            'axisLabel': {'color': '#546e7a', 'fontSize': 7},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
            'min': y_axis_min,
            'max': y_axis_max,
        },
        'series': [
            {
                'name': 'Linear',
                'type': 'line',
                'data': [[xl0, yl0], [xl1, yl1]],
                'lineStyle': {'color': '#78909c', 'type': 'dashed', 'width': 1.5},
                'symbol': 'none',
                'emphasis': {'disabled': True},
                'z': 1,
            },
            {
                'name': 'Variation',
                'type': 'scatter',
                'data': reg_pts,
                'symbolSize': 7,
                'itemStyle': {'color': '#42a5f5'},
                'z': 2,
            },
            {
                'name': 'Ref.Var.',
                'type': 'scatter',
                'data': ref_pts,
                'symbol': 'diamond',
                'symbolSize': 11,
                'itemStyle': {'color': '#ffa726'},
                'z': 3,
            },
            {
                'name': 'Nominal',
                'type': 'scatter',
                'data': [[nominal_val, y_nom]],
                'symbol': 'triangle',
                'symbolSize': 10,
                'itemStyle': {'color': '#66bb6a'},
                'z': 3,
            },
        ],
    }


def _build_sensitivity_card(result_dir: str):
    sens_path  = os.path.join(result_dir, 'sensitivity_results.csv')
    cases_path = os.path.join(result_dir, 'sensitivity_cases.csv')
    if not os.path.isfile(sens_path):
        return
    try:
        df = pd.read_csv(sens_path)
        cases_df = pd.read_csv(cases_path) if os.path.isfile(cases_path) else None
    except Exception:
        return
    if df.empty:
        return

    with ui.card().classes('w-full q-mb-md'):
        ui.label('Sensitivity Analysis Results').classes('text-subtitle2 q-mb-sm')

        # Tornado chart
        n_params = len(df)
        chart_h = max(180, n_params * 44 + 80)
        ui.echart(_sensitivity_tornado_opts(df)).style(f'width:100%;height:{chart_h}px')

        # Summary table
        _SENS_COLS = [
            ('param_name',           'Parameter',       'left'),
            ('nominal_value',        'Nominal',         'right'),
            ('variation_unit',       'Unit',            'center'),
            ('sensitivity [m/unit]', 'Sens [m/unit]',   'right'),
            ('sensitivity [m/%]',    'Sens [m/%]',      'right'),
            ('altitude_low [m]',     'Alt Low [m]',     'right'),
            ('altitude_nominal [m]', 'Alt Nominal [m]', 'right'),
            ('altitude_high [m]',    'Alt High [m]',    'right'),
        ]
        t_cols = [{'name': f.replace(' ', '_').replace('[', '').replace(']', '').replace('/', '_'),
                   'label': lbl, 'field': f, 'align': align}
                  for f, lbl, align in _SENS_COLS if f in df.columns]
        t_rows = df[[c['field'] for c in t_cols]].round(3).to_dict('records')
        ui.table(columns=t_cols, rows=t_rows, row_key='param_name').classes('w-full text-caption q-mt-sm')

        # Linearity check — collapsible
        has_cases = (
            cases_df is not None
            and 'param_value' in cases_df.columns
            and 'altitude_apogee [m]' in cases_df.columns
            and 'variation_low' in df.columns
        )
        if has_cases:
            with ui.expansion('Linearity Check', icon='scatter_plot').classes('w-full q-mt-xs'):
                ui.label(
                    '● Variation points  ◆ Reference Variations (used for sensitivity)  ▲ Nominal  — Linear slope'
                ).classes('text-caption text-grey q-mb-sm')
                n_cols = min(3, n_params)
                with ui.grid(columns=n_cols).classes('w-full'):
                    for _, row in df.iterrows():
                        opts = _sensitivity_linearity_opts(row, cases_df)
                        if opts:
                            ui.echart(opts).style('width:100%;height:220px')


# ── Monte Carlo helpers ───────────────────────────────────────────────────────

def _find_mc_result_tables(result_dir: str) -> list[tuple[str, str]]:
    if not result_dir or not os.path.isdir(result_dir):
        return []
    candidates = [
        ('',          'result_table.csv'),
        ('Descent',   'decent_result_table.csv'),
        ('Ballistic', 'ballistic_result_table.csv'),
    ]
    return [(lbl, os.path.join(result_dir, fn))
            for lbl, fn in candidates
            if os.path.isfile(os.path.join(result_dir, fn))]


# (col, display, raw_unit, display_unit, scale, color)
_MC_PARAMS = [
    ('altitude_apogee',         'Apogee Alt.',     'm',    'km',    1e-3, '#42a5f5'),
    ('maxQ',                    'Max Q',           'kPa',  'kPa',   1.0,  '#ffa726'),
    ('mach',                    'Max Mach',        '-',    '-',     1.0,  '#ab47bc'),
    ('downrange_impact',        'Downrange',       'm',    'km',    1e-3, '#66bb6a'),
    ('peak_total_aoa',          'Peak TotalAoA',   'deg',  'deg',   1.0,  '#ff6b9d'),
    ('aoa_launch_clear',        'AoA LaunchClear', 'deg',  'deg',   1.0,  '#ffc75f'),
    ('peak_spin_rate',          'Peak SpinRate',   'deg/s','deg/s', 1.0,  '#845ef7'),
    ('spin_rate_burnout',       'SpinRate Burnout','deg/s','deg/s', 1.0,  '#cc5de8'),
    ('min_sg',                  'Min Sg',          '-',    '-',     1.0,  '#20c997'),
    ('min_resonance_ratio',     'Min Res. Λ',      '-',    '-',     1.0,  '#ff922b'),
    ('max_trim_aoa',            'Max TrimAoA',     'deg',  'deg',   1.0,  '#748ffc'),
    ('max_lateral_aero_load',   'Max Lat. Load',   'N',    'N',     1.0,  '#ffa8a8'),
]


def _fmtv(v: float) -> str:
    """Format float without scientific notation, choosing decimal places by magnitude."""
    a = abs(v)
    if a >= 1000:
        return f'{v:.1f}'
    elif a >= 100:
        return f'{v:.2f}'
    elif a >= 10:
        return f'{v:.3f}'
    elif a >= 0.1:
        return f'{v:.4f}'
    else:
        return f'{v:.5f}'


def _mc_histogram_opts(data: list, title: str, unit: str, color: str) -> dict:
    arr = np.array(data, dtype=float)
    n_bins = max(10, min(40, max(2, len(arr) // 10)))
    counts, edges = np.histogram(arr, bins=n_bins)
    labels = [_fmtv(float(edges[i])) for i in range(len(edges) - 1)]
    mean, std = float(arr.mean()), float(arr.std())
    d = _D
    return {
        'backgroundColor': d['bg'],
        'animation': False,
        'title': {
            'text': f'{title} [{unit}]',
            'subtext': f'μ = {_fmtv(mean)}   σ = {_fmtv(std)}',
            'textStyle': {'color': d['ax'], 'fontSize': 11},
            'subtextStyle': {'color': '#546e7a', 'fontSize': 9},
            'left': 'center', 'top': 2,
        },
        'grid': {'top': 55, 'left': '14%', 'right': '5%', 'bottom': '22%'},
        'xAxis': {
            'type': 'category', 'data': labels,
            'axisLabel': {'color': '#546e7a', 'fontSize': 7, 'rotate': 35,
                          'interval': max(0, n_bins // 5 - 1)},
            'axisLine': {'lineStyle': {'color': d['border']}},
        },
        'yAxis': {
            'type': 'value', 'name': 'Count',
            'nameTextStyle': {'color': '#546e7a', 'fontSize': 9},
            'axisLabel': {'color': '#546e7a', 'fontSize': 8},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
        },
        'series': [{'type': 'bar', 'data': [int(c) for c in counts],
                    'itemStyle': {'color': color, 'opacity': 0.78}}],
    }


def _compute_impact_ellipses(lat_list: list, lon_list: list):
    """Compute 1σ/2σ/3σ impact ellipses in both NE and lat/lon coordinates.

    Returns east, north arrays [m], mean_lat, mean_lon,
    ne_ellipses [(nsig, color, [[e,n],...])],
    ll_ellipses [(nsig, color, [[lat,lon],...])].
    """
    lats = np.array(lat_list, dtype=float)
    lons = np.array(lon_list, dtype=float)
    mean_lat = float(lats.mean())
    mean_lon = float(lons.mean())
    R = 6_371_000.0
    cos_lat = float(np.cos(np.radians(mean_lat)))
    north = (lats - mean_lat) * (np.pi / 180) * R
    east  = (lons - mean_lon) * (np.pi / 180) * R * cos_lat

    ne_ellipses: list = []
    ll_ellipses: list = []
    if len(lats) >= 3:
        try:
            cov = np.cov(np.stack([east, north]))
            eigvals, eigvecs = np.linalg.eigh(cov)
            order = np.argsort(eigvals)[::-1]
            eigvals, eigvecs = eigvals[order], eigvecs[:, order]
            theta = np.linspace(0, 2 * np.pi, 120)
            cos_t, sin_t = np.cos(theta), np.sin(theta)
            for nsig, clr in [(1, '#4caf50'), (2, '#ff9800'), (3, '#f44336')]:
                a = nsig * float(np.sqrt(max(float(eigvals[0]), 0.0)))
                b = nsig * float(np.sqrt(max(float(eigvals[1]), 0.0)))
                ne_pts: list = []
                ll_pts: list = []
                for ct, st in zip(cos_t, sin_t):
                    v = eigvecs @ np.array([a * ct, b * st])
                    e, nv = float(v[0]), float(v[1])
                    ne_pts.append([e, nv])
                    ll_pts.append([
                        mean_lat + nv / R * (180 / np.pi),
                        mean_lon + e / (R * cos_lat) * (180 / np.pi),
                    ])
                ne_pts.append(ne_pts[0])
                ll_pts.append(ll_pts[0])
                ne_ellipses.append((nsig, clr, ne_pts))
                ll_ellipses.append((nsig, clr, ll_pts))
        except Exception:
            pass
    return east, north, mean_lat, mean_lon, ne_ellipses, ll_ellipses


def _mc_impact_scatter_opts(scatter_data: list, ne_ellipses: list) -> dict:
    ellipse_series = [
        {'type': 'line', 'name': f'{nsig}σ', 'data': pts,
         'showSymbol': False, 'lineStyle': {'color': clr, 'width': 1.5}, 'z': 1}
        for nsig, clr, pts in ne_ellipses
    ]
    d = _D
    return {
        'backgroundColor': d['bg'],
        'animation': False,
        'title': {'text': 'Impact Scatter (Local NE)',
                  'textStyle': {'color': d['ax'], 'fontSize': 11},
                  'left': 'center', 'top': 2},
        'legend': {'data': ['Impact', '1σ', '2σ', '3σ'],
                   'textStyle': {'color': d['ax'], 'fontSize': 9},
                   'right': 6, 'top': 4, 'itemWidth': 12, 'itemHeight': 8},
        'tooltip': {'trigger': 'item', 'backgroundColor': '#1e1e2e',
                    'borderColor': d['border'], 'textStyle': {'color': '#ccc', 'fontSize': 10}},
        'grid': {'top': 36, 'left': '12%', 'right': '4%', 'bottom': '12%'},
        'xAxis': {
            'type': 'value', 'name': 'East [m]',
            'nameLocation': 'middle', 'nameGap': 22,
            'nameTextStyle': {'color': d['ax'], 'fontSize': 10},
            'axisLabel': {'color': '#546e7a', 'fontSize': 9},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
        },
        'yAxis': {
            'type': 'value', 'name': 'North [m]',
            'nameLocation': 'middle', 'nameGap': 50, 'nameRotate': 90,
            'nameTextStyle': {'color': d['ax'], 'fontSize': 10},
            'axisLabel': {'color': '#546e7a', 'fontSize': 9},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
        },
        'series': [
            {'type': 'scatter', 'name': 'Impact', 'data': scatter_data,
             'symbolSize': 5, 'itemStyle': {'color': '#42a5f5', 'opacity': 0.45}, 'z': 2},
            *ellipse_series,
        ],
    }


def _build_mc_card(df_mc: pd.DataFrame, label: str):
    avail = [(col, disp, raw_unit, disp_unit, scale, clr)
             for col, disp, raw_unit, disp_unit, scale, clr in _MC_PARAMS
             if col in df_mc.columns]
    n = len(df_mc)
    title = 'Monte Carlo Statistics' + (f' — {label}' if label else '') + f'  (n = {n})'

    with ui.card().classes('w-full q-mb-md'):
        ui.label(title).classes('text-subtitle2 q-mb-sm')

        # Summary stats grid
        if avail:
            with ui.grid(columns=len(avail)).classes('w-full q-mb-sm'):
                for col, disp, raw_unit, disp_unit, scale, clr in avail:
                    arr = df_mc[col].dropna().to_numpy(dtype=float) * scale
                    if not len(arr):
                        continue
                    mean, std = float(arr.mean()), float(arr.std())
                    with ui.card().classes('q-pa-sm').style('background:#1a2744'):
                        ui.label(f'{disp} [{disp_unit}]').classes('text-caption text-grey')
                        ui.label(_fmtv(mean)).classes('text-weight-bold').style(f'color:{clr}')
                        ui.label(f'σ = {_fmtv(std)}').classes('text-caption text-grey')
                        ui.label(f'+3σ:  {_fmtv(mean + 3 * std)}').classes('text-caption text-grey')
                        ui.label(f'−3σ:  {_fmtv(mean - 3 * std)}').classes('text-caption text-grey')

        # Histograms
        if n >= 10 and avail:
            with ui.grid(columns=2).classes('w-full q-mb-sm'):
                for col, disp, raw_unit, disp_unit, scale, clr in avail:
                    arr = df_mc[col].dropna().to_numpy(dtype=float) * scale
                    if len(arr) < 5:
                        continue
                    ui.echart(_mc_histogram_opts(arr.tolist(), disp, disp_unit, clr)).style(
                        'width:100%;height:220px')

        # 2-D impact scatter + Leaflet map with ellipses
        if 'lat_impact' in df_mc.columns and 'lon_impact' in df_mc.columns and n >= 3:
            lats = df_mc['lat_impact'].dropna().tolist()
            lons = df_mc['lon_impact'].dropna().tolist()
            if len(lats) >= 3:
                east, north, mean_lat, mean_lon, ne_ell, ll_ell = _compute_impact_ellipses(lats, lons)
                scatter_data = [[float(e), float(nv)] for e, nv in zip(east, north)]
                ui.echart(_mc_impact_scatter_opts(scatter_data, ne_ell)).style('width:100%;height:380px')

                with ui.card().classes('w-full q-mt-sm'):
                    ui.label('Impact Points Map').classes('text-subtitle2 q-mb-xs')
                    m2 = ui.leaflet(center=(mean_lat, mean_lon), zoom=10).style('height:350px;width:100%')
                    m2.tile_layer(
                        url_template='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                        options={'attribution': '© OpenStreetMap contributors', 'maxZoom': 18},
                    )
                    # Impact scatter (sampled)
                    step = max(1, len(lats) // 300)
                    for lat, lon in zip(lats[::step], lons[::step]):
                        m2.generic_layer(name='circleMarker', args=[
                            [float(lat), float(lon)],
                            {'radius': 3, 'color': '#ff9800', 'fillColor': '#ff9800',
                             'fillOpacity': 0.55, 'weight': 0},
                        ])
                    # 1σ/2σ/3σ ellipses
                    for _nsig, ell_clr, ll_pts in ll_ell:
                        m2.generic_layer(name='polyline', args=[
                            ll_pts,
                            {'color': ell_clr, 'weight': 2, 'opacity': 0.85},
                        ])
                    # Mean impact point
                    m2.generic_layer(name='circleMarker', args=[
                        [mean_lat, mean_lon],
                        {'radius': 7, 'color': '#f44336', 'fillColor': '#f44336',
                         'fillOpacity': 1.0, 'weight': 2},
                    ])
                    bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
                    ui.timer(0.3, lambda b=bounds: m2.run_map_method(
                        'fitBounds', b, {'padding': [24, 24]}), once=True)


# ── Ground track map ─────────────────────────────────────────────────────────

def _build_map_card(df: pd.DataFrame, calc_id: int, summary_items: list | None = None):
    step = max(1, len(df) // 1000)
    dfs = df.iloc[::step]
    lats = dfs['Latitude [deg]'].tolist()
    lons = dfs['Longitude [deg]'].tolist()
    coords = [[lat, lon] for lat, lon in zip(lats, lons)]

    center = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
    bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

    event_positions = _get_event_positions(summary_items or [], df)

    with ui.card().classes('w-full q-mb-md'):
        ui.label('Ground Track').classes('text-subtitle2 q-mb-sm')
        m = ui.leaflet(center=center, zoom=8).style('height:420px;width:100%')
        m.tile_layer(
            url_template='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            options={'attribution': '© OpenStreetMap contributors', 'maxZoom': 18},
        )
        m.generic_layer(name='polyline', args=[coords, {'color': '#42a5f5', 'weight': 2, 'opacity': 0.85}])

        tooltip_layers: list[tuple] = []

        if event_positions:
            for label, lat, lon, _alt in event_positions:
                sec = label.split(':')[0].strip()
                color = _EVENT_COLORS.get(sec, '#9e9e9e')
                layer = m.generic_layer(name='circleMarker', args=[
                    [lat, lon],
                    {'radius': 9, 'color': color, 'fillColor': color, 'fillOpacity': 0.9, 'weight': 2},
                ])
                tooltip_layers.append((layer, label))
        else:
            # Fallback: plain launch/landing dots
            m.generic_layer(name='circleMarker', args=[
                [lats[0], lons[0]],
                {'radius': 7, 'color': '#4caf50', 'fillColor': '#4caf50', 'fillOpacity': 1, 'weight': 2},
            ])
            m.generic_layer(name='circleMarker', args=[
                [lats[-1], lons[-1]],
                {'radius': 7, 'color': '#f44336', 'fillColor': '#f44336', 'fillOpacity': 1, 'weight': 2},
            ])

        if tooltip_layers:
            def _bind_tooltips():
                for layer, label in tooltip_layers:
                    layer.run_method('bindTooltip', label, {'direction': 'top', 'sticky': False})
            ui.timer(0.5, _bind_tooltips, once=True)

        ui.timer(0.3, lambda: m.run_map_method('fitBounds', bounds, {'padding': [30, 30]}), once=True)


# ── CesiumJS 3-D trajectory ───────────────────────────────────────────────────

def _build_cesium_card(df: pd.DataFrame, summary_items: list | None, calc_id: int):
    step = max(1, len(df) // 2000)
    dfs = df.iloc[::step]
    lats = dfs['Latitude [deg]'].tolist()
    lons = dfs['Longitude [deg]'].tolist()
    alts = dfs['Altitude [m]'].tolist()

    # [lon, lat, alt, ...] flat array for Cartesian3.fromDegreesArrayHeights
    flat: list[float] = []
    for la, lo, al in zip(lats, lons, alts):
        flat.extend([lo, la, max(al, 0.0)])

    event_positions = _get_event_positions(summary_items or [], df)
    ev_js = _json.dumps([
        {'label': label, 'lat': lat, 'lon': lon, 'alt': max(alt, 0.0),
         'color': _EVENT_COLORS.get(label.split(':')[0].strip(), '#9e9e9e')}
        for label, lat, lon, alt in event_positions
    ])

    container_id = f'cesium-{calc_id}'
    flat_js      = _json.dumps(flat)

    ui.add_head_html(
        f'<link href="https://cesium.com/downloads/cesiumjs/releases/{_CESIUM_VERSION}'
        f'/Build/Cesium/Widgets/widgets.css" rel="stylesheet">\n'
        f'<script src="https://cesium.com/downloads/cesiumjs/releases/{_CESIUM_VERSION}'
        f'/Build/Cesium/Cesium.js"></script>\n'
        f'<style>#{container_id} .cesium-widget-credits{{display:none}}</style>'
    )

    with ui.card().classes('w-full q-mb-md'):
        ui.label('3D Trajectory').classes('text-subtitle2 q-mb-sm')
        ui.html(f'<div id="{container_id}" style="height:600px;width:100%;border-radius:4px;"></div>')

    js = f'''
(function waitCesium() {{
    if (typeof Cesium === "undefined" || !document.getElementById({_json.dumps(container_id)})) {{
        setTimeout(waitCesium, 200); return;
    }}
    var el = document.getElementById({_json.dumps(container_id)});
    if (el._cesiumWidget) return;

    try {{ Cesium.Ion.defaultAccessToken = ""; }} catch(e) {{}}

    var viewer = new Cesium.Viewer({_json.dumps(container_id)}, {{
        baseLayerPicker: false,
        geocoder: false,
        homeButton: true,
        animation: false,
        timeline: false,
        sceneModePicker: true,
        navigationHelpButton: false,
        infoBox: false,
        selectionIndicator: false,
        terrainProvider: new Cesium.EllipsoidTerrainProvider()
    }});

    try {{
        viewer.imageryLayers.removeAll();
        viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({{
            url: "https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png",
            maximumLevel: 18,
            credit: "\\u00a9 OpenStreetMap contributors"
        }}));
    }} catch(e) {{ console.warn("OSM imagery:", e); }}

    var flat = {flat_js};
    var positions = Cesium.Cartesian3.fromDegreesArrayHeights(flat);
    viewer.entities.add({{
        polyline: {{
            positions: positions,
            width: 2,
            material: new Cesium.Color(0.26, 0.65, 0.96, 1.0),
            clampToGround: false
        }}
    }});

    var events = {ev_js};
    events.forEach(function(ev) {{
        var c = Cesium.Color.fromCssColorString(ev.color);
        viewer.entities.add({{
            position: Cesium.Cartesian3.fromDegrees(ev.lon, ev.lat, ev.alt),
            point: {{ pixelSize: 10, color: c, outlineColor: Cesium.Color.WHITE, outlineWidth: 1 }},
            label: {{
                text: ev.label,
                font: "12px sans-serif",
                pixelOffset: new Cesium.Cartesian2(0, -18),
                fillColor: Cesium.Color.WHITE,
                outlineColor: Cesium.Color.BLACK,
                outlineWidth: 2,
                style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                showBackground: true,
                backgroundColor: new Cesium.Color(0, 0, 0, 0.55),
                disableDepthTestDistance: Number.POSITIVE_INFINITY
            }}
        }});
    }});

    viewer.zoomTo(viewer.entities);
}})();
'''
    ui.timer(0.6, lambda: ui.run_javascript(js), once=True)


# ── Interactive graph ─────────────────────────────────────────────────────────

def _build_graph_card(csv_files: list[str], preloaded_df: pd.DataFrame | None):
    state: dict = {}

    def _load(path: str) -> pd.DataFrame:
        return pd.read_csv(path).dropna(how='any', axis=1)

    state['df'] = preloaded_df if preloaded_df is not None else _load(csv_files[0])

    with ui.card().classes('w-full'):
        ui.label('Interactive Graph').classes('text-subtitle2 q-mb-xs')

        if len(csv_files) > 1:
            names = [Path(f).stem for f in csv_files]

            def _on_csv(e):
                idx = names.index(e.value) if e.value in names else 0
                state['df'] = _load(csv_files[idx])
                _rebuild_presets()
                _refresh()

            ui.select(names, value=names[0], label='Flight log',
                      on_change=_on_csv).classes('q-mb-xs')

        cols = list(state['df'].columns)
        default_x = 'Time [s]'     if 'Time [s]'     in cols else cols[0]
        default_y = 'Altitude [m]' if 'Altitude [m]'  in cols else cols[1]

        with ui.row().classes('items-center q-gutter-xs q-mb-xs'):
            ui.label('Preset:').classes('text-caption text-grey q-my-auto')
            preset_row = ui.row().classes('q-gutter-xs')

        with ui.row().classes('q-gutter-md q-mb-sm'):
            x_sel = ui.select(cols, value=default_x, label='X Axis',
                              on_change=lambda _: _refresh()).style('min-width:230px')
            y_sel = ui.select(cols, value=default_y, label='Y Axis',
                              on_change=lambda _: _refresh()).style('min-width:230px')

        chart = ui.echart(_echart_opts(state['df'], default_x, default_y)).style(
            'width:100%;height:500px'
        )

        def _refresh():
            df, xc, yc = state['df'], x_sel.value, y_sel.value
            if xc in df.columns and yc in df.columns:
                chart.options.update(_echart_opts(df, xc, yc))
                chart.update()

        def _rebuild_presets():
            preset_row.clear()
            cols_now = list(state['df'].columns)
            with preset_row:
                for pn, px, py in _PRESETS:
                    if px in cols_now and py in cols_now:
                        def _click(x=px, y=py):
                            x_sel.set_value(x)
                            y_sel.set_value(y)
                            _refresh()
                        ui.button(pn, on_click=_click).props('dense flat color=primary')

        _rebuild_presets()
