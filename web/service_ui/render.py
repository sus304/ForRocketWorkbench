"""Result rendering for the service-native GUI (design §11.5, Phase 9).

Ported from the legacy result page but decoupled from the Calculation DB: every builder takes
a `result_dir` (a service work_dir, local for use case ②) plus `mode` and a `key` used only for
DOM-unique ids. There is no dependency on web.db here — the compute service's job store is the
source of truth, and the GUI reads artefacts straight off the local work_dir.

Split into (a) pure, testable helpers — file discovery, summary parsing, unit rescaling, chart
option assembly, impact-ellipse maths — and (b) NiceGUI card builders that consume them. Only
the pure helpers are unit-tested; the cards are exercised by manual/e2e verification.
"""
from __future__ import annotations

import glob
import json as _json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from nicegui import ui

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

# Target apogee altitude for the reach-probability readout (Karman line, 100 km).
# altitude_apogee is scaled to km in the MC card, so this threshold is in km.
REACH_ALTITUDE_THRESHOLD_KM = 100.0

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


# ── File finders ─────────────────────────────────────────────────────────────

def find_flight_logs(result_dir: str) -> list[str]:
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


def find_summaries(result_dir: str) -> list[str]:
    if not result_dir or not os.path.isdir(result_dir):
        return []
    return sorted(glob.glob(os.path.join(result_dir, 'result_*', '_summary.txt')))


def parse_summary(path: str) -> list[tuple[str, str, str]]:
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


def get_event_positions(
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


def find_mc_result_tables(result_dir: str) -> list[tuple[str, str]]:
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


# ── API response -> DataFrame/items converters (design §6) ──────────────────────
# The GUI sources result data through the service result API (service.client), not by reading
# result_dir directly: decimation/limits are enforced once, server-side, and the mixed
# topology (local UI -> remote service) keeps working (design §3.4). These pure converters turn
# the JSON payloads back into the DataFrames/items the existing card builders already consume.

_MC_TABLE_LABELS = {
    'result_table': '',
    'decent_result_table': 'Descent',
    'ballistic_result_table': 'Ballistic',
}


def table_to_df(table: dict) -> pd.DataFrame:
    """{'columns':[...], 'rows':[[...]]} -> DataFrame (as returned by /result/tables and extract)."""
    return pd.DataFrame(table.get('rows', []), columns=table.get('columns', []))


def extract_log_to_df(log: dict) -> pd.DataFrame:
    """One /result/extract log entry -> DataFrame, numeric columns coerced for plotting.

    The API already serialises values as native numbers/None, so a plain frame usually has numeric
    dtypes; we only coerce object columns (e.g. numbers that arrived as strings). We do NOT use
    pd.to_numeric(errors='ignore') — that value was removed in pandas >= 2.2 (the VM runs a newer
    pandas than the test env) and raises 'invalid error value specified'."""
    df = pd.DataFrame(log.get('rows', []), columns=log.get('columns', []))
    for col in df.columns:
        if df[col].dtype == object:
            coerced = pd.to_numeric(df[col], errors='coerce')
            if coerced.notna().any():   # keep genuinely non-numeric columns as-is
                df[col] = coerced
    return df


def summary_items_from_api(raw: list) -> list:
    """/result/summary items ([{key,value,unit}]) -> the (key, value, unit) tuples the cards use."""
    return [(d.get('key', ''), d.get('value', ''), d.get('unit', '')) for d in (raw or [])]


# Above this many cases the Case dropdown is not pre-filled with every case; the user narrows
# with a selection expression instead (design §8, review N-8/N-3).
CASE_ENUM_CAP = 200

# Cap on cases auto-overlaid on the interactive graph at once — keeps browser transfer and the
# legend readable when a selection expression resolves to many cases (e.g. top:50).
MAX_OVERLAY_CASES = 12


def quickpick_expr(kind: str, phase: str) -> str:
    """Selection expression for a quick-pick chip. Pure/testable (design §8)."""
    if kind == 'nominal':
        return 'nominal'
    if kind == 'farthest':
        return f'top:10:downrange_impact:{phase}'
    raise ValueError(f'unknown quickpick: {kind}')


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


# Distinct line colours for overlaying several cases on one graph.
_OVERLAY_PALETTE = ['#42a5f5', '#ff9800', '#66bb6a', '#ab47bc', '#ff6b9d',
                    '#00bcd4', '#ffca28', '#8d6e63', '#26a69a', '#ef5350']


def _auto_km_scale(col: str, all_values: list) -> tuple[float, str]:
    """Decide a single m→km rescale for a column across ALL overlaid series, so shared axes stay
    consistent. Returns (scale, label)."""
    if not col.endswith('[m]'):
        return 1.0, col
    vmax = max((abs(v) for v in all_values if v is not None and not pd.isna(v)), default=0.0)
    if vmax < 10_000.0:
        return 1.0, col
    return 1e-3, col[:-3] + '[km]'


def _echart_multi_opts(series: list, x_col: str, y_col: str) -> dict:
    """Overlay several (label, DataFrame) series sharing x/y columns on one line chart. For a
    single series this matches _echart_opts (minus the legend)."""
    all_x = [v for _, df in series for v in df[x_col].tolist()]
    all_y = [v for _, df in series for v in df[y_col].tolist()]
    xscale, x_label = _auto_km_scale(x_col, all_x)
    yscale, y_label = _auto_km_scale(y_col, all_y)
    d = _D
    series_opts = []
    for i, (label, df) in enumerate(series):
        xs = [None if v is None or pd.isna(v) else v * xscale for v in df[x_col].tolist()]
        ys = [None if v is None or pd.isna(v) else v * yscale for v in df[y_col].tolist()]
        color = _OVERLAY_PALETTE[i % len(_OVERLAY_PALETTE)]
        series_opts.append({
            'type': 'line', 'name': label, 'data': list(zip(xs, ys)),
            'showSymbol': False, 'lineStyle': {'color': color, 'width': 2},
            'sampling': 'lttb',
        })
    multi = len(series) > 1
    return {
        'backgroundColor': d['bg'],
        'animation': False,
        'tooltip': {'trigger': 'axis', 'backgroundColor': '#1e1e2e',
                    'borderColor': d['border'], 'textStyle': {'color': '#ccc', 'fontSize': 11}},
        'legend': ({'data': [lbl for lbl, _ in series], 'top': 4,
                    'textStyle': {'color': d['ax'], 'fontSize': 10},
                    'type': 'scroll'} if multi else {'show': False}),
        'toolbox': {
            'show': True, 'right': 10, 'top': 5, 'itemSize': 14,
            'iconStyle': {'borderColor': d['ax']},
            'emphasis': {'iconStyle': {'borderColor': '#fff'}},
            'feature': {'dataZoom': {'yAxisIndex': 'none'}, 'restore': {},
                        'saveAsImage': {'pixelRatio': 2}},
        },
        'dataZoom': [
            {'type': 'inside'},
            {'type': 'slider', 'height': 18, 'bottom': 4, 'borderColor': d['border'],
             'fillerColor': 'rgba(66,165,245,0.15)', 'handleStyle': {'color': d['line']},
             'textStyle': {'color': d['ax'], 'fontSize': 9}},
        ],
        'grid': {'top': '13%' if multi else '6%', 'left': '10%', 'right': '3%', 'bottom': '18%'},
        'xAxis': {
            'type': 'value', 'name': x_label, 'nameLocation': 'middle', 'nameGap': 28,
            'nameTextStyle': {'color': d['ax'], 'fontSize': 11},
            'axisLabel': {'color': d['ax'], 'fontSize': 10},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
        },
        'yAxis': {
            'type': 'value', 'name': y_label, 'nameLocation': 'middle', 'nameGap': 55,
            'nameRotate': 90, 'nameTextStyle': {'color': d['ax'], 'fontSize': 11},
            'axisLabel': {'color': d['ax'], 'fontSize': 10},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
        },
        'series': series_opts,
    }


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


# Impact-dispersion ellipse math moved to service.results so the plots API and this echarts
# render share one implementation (design §3.4). Re-exported here for existing callers/tests.
from service.results import compute_impact_ellipses  # noqa: E402,F401


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


def _sensitivity_tornado_opts(df: pd.DataFrame) -> dict:
    nominal = float(df['altitude_nominal [m]'].iloc[0])
    dc = df.copy()
    dc['lo_delta'] = dc['altitude_low [m]'] - nominal
    dc['hi_delta'] = dc['altitude_high [m]'] - nominal
    dc['range']    = (dc['hi_delta'] - dc['lo_delta']).abs()
    dc = dc.sort_values('range', ascending=True)

    params = dc['param_name'].tolist()
    # Floating bar from lo_delta -> hi_delta for each parameter (row i). A custom series draws
    # each bar as an explicit rectangle so any sign works (a stacked transparent-offset bar
    # breaks for negative starts).
    bar_data = [
        {'value': [i, float(r.lo_delta), float(r.hi_delta)],
         'name': r.param_name,
         'itemStyle': {'color': '#42a5f5' if r.hi_delta >= r.lo_delta else '#ffa726'}}
        for i, (_, r) in enumerate(dc.iterrows())
    ]

    render_item = (
        'function (params, api) {'
        '  var ci = api.value(0);'
        '  var p1 = api.coord([api.value(1), ci]);'
        '  var p2 = api.coord([api.value(2), ci]);'
        '  var h = api.size([0, 1])[1] * 0.6;'
        '  var xLeft = Math.min(p1[0], p2[0]);'
        '  var w = Math.abs(p2[0] - p1[0]);'
        '  return {'
        '    type: "rect",'
        '    shape: { x: xLeft, y: p1[1] - h / 2, width: w, height: h },'
        '    style: api.style()'
        '  };'
        '}'
    )
    tip_formatter = (
        'function (p) {'
        '  var v = p.value;'
        '  return p.name + "<br/>low: " + v[1].toFixed(1) + " m<br/>high: " + v[2].toFixed(1) + " m";'
        '}'
    )

    d = _D
    return {
        'backgroundColor': d['bg'],
        'animation': False,
        'title': {'text': 'Sensitivity Tornado Chart',
                  'textStyle': {'color': d['ax'], 'fontSize': 12},
                  'left': 'center', 'top': 4},
        'tooltip': {'trigger': 'item',
                    ':formatter': tip_formatter,
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
                'type': 'custom',
                ':renderItem': render_item,
                'encode': {'x': [1, 2], 'y': 0},
                'data': bar_data,
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
    """Linearity-check chart for one parameter (see legacy result page for the maths)."""
    param_name  = str(sens_row['param_name'])
    nominal_val = float(sens_row['nominal_value'])
    y_nom       = float(sens_row['altitude_nominal [m]'])
    slope       = float(sens_row['sensitivity [m/unit]'])
    unit        = str(sens_row.get('variation_unit', ''))

    if unit == '%' and nominal_val != 0:
        slope = slope * 100.0 / nominal_val
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

    ref_lo_rows = param_cases[np.abs(param_cases['variation'] - var_lo_ref) < tol]
    if not ref_lo_rows.empty:
        x_anc = float(ref_lo_rows.iloc[0]['param_value'])
        y_anc = float(ref_lo_rows.iloc[0]['altitude_apogee [m]'])
    else:
        x_anc, y_anc = nominal_val, y_nom

    all_x = [p[0] for p in reg_pts + ref_pts] + [nominal_val]
    x_half = max(abs(x - nominal_val) for x in all_x)
    x_half = x_half * 1.20 if x_half > 0 else 1.0
    x_axis_min = nominal_val - x_half
    x_axis_max = nominal_val + x_half

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
        'title': {'text': param_name, 'textStyle': {'color': d['ax'], 'fontSize': 10},
                  'left': 'center', 'top': 2},
        'tooltip': {
            'trigger': 'item',
            'formatter': 'function(p){return p.seriesName+"<br/>x="+p.value[0].toPrecision(5)+"<br/>alt="+p.value[1].toFixed(1)+"m"}',
            'backgroundColor': '#1e1e2e', 'borderColor': d['border'],
            'textStyle': {'color': '#ccc', 'fontSize': 9},
        },
        'legend': {'show': True, 'bottom': 0, 'textStyle': {'color': '#888', 'fontSize': 8},
                   'itemWidth': 10, 'itemHeight': 8},
        'grid': {'top': 28, 'left': '18%', 'right': '5%', 'bottom': 36},
        'xAxis': {
            'type': 'value', 'name': unit, 'nameLocation': 'end',
            'nameTextStyle': {'color': d['ax'], 'fontSize': 8},
            'axisLabel': {'color': '#546e7a', 'fontSize': 7},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
            'min': x_axis_min, 'max': x_axis_max,
        },
        'yAxis': {
            'type': 'value', 'name': 'Alt [m]', 'nameLocation': 'end',
            'nameTextStyle': {'color': d['ax'], 'fontSize': 8},
            'axisLabel': {'color': '#546e7a', 'fontSize': 7},
            'axisLine': {'lineStyle': {'color': d['border']}},
            'splitLine': {'lineStyle': {'color': d['grid'], 'type': 'dashed'}},
            'min': y_axis_min, 'max': y_axis_max,
        },
        'series': [
            {'name': 'Linear', 'type': 'line', 'data': [[xl0, yl0], [xl1, yl1]],
             'lineStyle': {'color': '#78909c', 'type': 'dashed', 'width': 1.5},
             'symbol': 'none', 'emphasis': {'disabled': True}, 'z': 1},
            {'name': 'Variation', 'type': 'scatter', 'data': reg_pts, 'symbolSize': 7,
             'itemStyle': {'color': '#42a5f5'}, 'z': 2},
            {'name': 'Ref.Var.', 'type': 'scatter', 'data': ref_pts, 'symbol': 'diamond',
             'symbolSize': 11, 'itemStyle': {'color': '#ffa726'}, 'z': 3},
            {'name': 'Nominal', 'type': 'scatter', 'data': [[nominal_val, y_nom]],
             'symbol': 'triangle', 'symbolSize': 10, 'itemStyle': {'color': '#66bb6a'}, 'z': 3},
        ],
    }


# ── Entry point ────────────────────────────────────────────────────────────────

def render_result(client, job_id, mode: str, key) -> None:
    """Render every result card for a completed job, sourcing data from the service result API.

    `client` is a service.client.ServiceClient; `key` (the job id) makes DOM ids unique. Replaces
    the old local `result_dir` read so the same code serves ③ (UI on the VM) and the mixed
    topology, and so flight-log data is decimated server-side before it reaches the browser
    (design §3.4, §6). Mirrors the legacy result page's content, minus the Calculation-DB
    metadata/memo.
    """
    try:
        meta = client.result_meta(job_id)
    except Exception as exc:
        ui.label(f'No result available: {exc}').classes('text-caption text-grey')
        return

    summary_items = summary_items_from_api(_safe(lambda: client.result_summary(job_id), []))
    if summary_items:
        _build_summary_card(summary_items)

    # Optional external detailed-3D viewer link (config-gated, neutral name; design §10).
    from web.service_ui import config as _cfg
    ext_3d = _safe(lambda: _cfg.external_3d_url(), '')
    if ext_3d:
        with ui.row().classes('q-mb-sm'):
            ui.button('Open in detailed 3D',
                      on_click=lambda u=ext_3d: ui.navigate.to(u, new_tab=True)) \
                .props('flat color=primary icon=open_in_new')

    if mode == 'sensitivity':
        _build_sensitivity_card(client, job_id)

    if mode == 'montecarlo':
        for logical in meta.get('tables', []):
            if not logical.endswith('result_table'):
                continue
            try:
                df_mc = table_to_df(client.result_table(job_id, logical))
                _build_mc_card(df_mc, _MC_TABLE_LABELS.get(logical, ''))
            except Exception as exc:
                with ui.card().classes('w-full q-mb-md'):
                    ui.label(f'MC stats error: {exc}').classes('text-negative text-caption')

    if 'flight' in meta.get('kinds', ['flight']):
        _build_flight_section(client, job_id, meta, key, summary_items)


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _build_flight_section(client, job_id, meta: dict, key, summary_items: list) -> None:
    """Case-selection UI + per-case flight-log cards (ground track, 3D, interactive graph).

    A selection expression (nominal / id / top-bottom) resolves to a case list; the chosen case's
    decimated flight log drives the cards. Document-quality overlays of many cases are produced by
    the plots API instead (design §5); here one case is shown at a time to keep browser transfer
    and echarts light. Re-selecting re-fetches and redraws only this section.
    """
    phases = meta.get('phases') or ['stage1']
    cases_by_phase = meta.get('cases_by_phase') or {}
    case_count = int(meta.get('case_count') or 0)
    small = 0 < case_count <= CASE_ENUM_CAP
    state: dict = {'select': 'nominal', 'phase': phases[0], 'case': None}

    with ui.card().classes('w-full q-mb-md'):
        ui.label('Flight Case').classes('text-subtitle2 q-mb-xs')
        with ui.row().classes('items-center q-gutter-sm'):
            sel_in = ui.input('Selection', value='nominal',
                              placeholder='nominal | id:0,3 | top:5:downrange_impact | filter:min_sg<1') \
                .props('dense').style('min-width:300px')
            phase_sel = ui.select(phases, value=state['phase'], label='Phase',
                                  on_change=lambda _: _on_phase()).props('dense') \
                if len(phases) > 1 else None
            # Multi-select: several cases overlay on the graph; map/3D/download use the first.
            case_sel = ui.select([], label='Cases', multiple=True) \
                .props('dense use-chips').style('min-width:200px')
            ui.button('Apply', on_click=lambda: _resolve_cases())
        with ui.row().classes('q-gutter-xs q-mt-xs'):
            ui.label('Quick:').classes('text-caption text-grey q-my-auto')
            ui.button('Nominal', on_click=lambda: _quick('nominal')).props('dense flat')
            ui.button('Farthest 10', on_click=lambda: _quick('farthest')).props('dense flat')
            ui.label('複数選択で重ね描き（地図/3D/DL は先頭ケース）') \
                .classes('text-caption text-grey q-my-auto')
        # For small runs the Case dropdown lists every real case (from meta.cases_by_phase); the
        # selection expression narrows large runs (design §8 / review N-8).

    cards = ui.column().classes('w-full')

    def _current_phase():
        return phase_sel.value if phase_sel is not None else state['phase']

    def _selected_cases():
        v = case_sel.value
        if isinstance(v, list):
            return [c for c in v if c is not None]
        return [v] if v is not None else []

    def _enumerate_small():
        # Populate the dropdown from the real per-phase case numbers, no server round-trip.
        cases = list(cases_by_phase.get(_current_phase(), []))
        state['phase'] = _current_phase()
        case_sel.set_options(cases, value=[cases[0]] if cases else [])
        _draw_case()

    def _on_phase():
        if small:
            _enumerate_small()
        else:
            _resolve_cases()

    def _quick(kind):
        sel_in.value = quickpick_expr(kind, _current_phase())
        _resolve_cases()

    def _resolve_cases():
        state['select'] = (sel_in.value or 'nominal').strip()
        state['phase'] = _current_phase()
        try:
            resolved = client.result_cases(job_id, state['select'])
        except Exception as exc:
            case_sel.set_options([], value=[])
            cards.clear()
            with cards:
                ui.label(f'Selection error: {exc}').classes('text-negative text-caption')
            return
        cases = [int(c['case']) for c in resolved]
        # Default to overlaying the whole resolved set (e.g. Farthest 10 → 10 lines); the user can
        # prune in the dropdown. Cap the auto-overlay so a huge selection isn't drawn by accident.
        default = cases[:MAX_OVERLAY_CASES]
        case_sel.set_options(cases, value=default)
        _draw_case()

    def _draw_case():
        cards.clear()
        cases = _selected_cases()
        if not cases:
            return
        if len(cases) > MAX_OVERLAY_CASES:
            cases = cases[:MAX_OVERLAY_CASES]
        primary = cases[0]
        id_expr = 'id:' + ','.join(str(c) for c in cases)
        try:
            ex = client.extract(job_id, id_expr, phase=state['phase'], max_points=2000)
        except Exception as exc:
            with cards:
                ui.label(f'Extract error: {exc}').classes('text-negative text-caption')
            return
        logs = ex.get('logs', [])
        if not logs:
            with cards:
                ui.label('No flight log for this case/phase.').classes('text-caption text-grey')
            return
        series = [(f"case {lg.get('case', i)}", extract_log_to_df(lg)) for i, lg in enumerate(logs)]
        primary_df = series[0][1]
        with cards:
            _build_download_row(client, job_id, state, cases)
            if len(series) > 1:
                ui.label(f'{len(series)} cases overlaid — Ground Track / 3D show case {primary}.') \
                    .classes('text-caption text-grey')
            if {'Latitude [deg]', 'Longitude [deg]'}.issubset(primary_df.columns):
                _build_map_card(primary_df, f'{key}-{primary}', summary_items)
            if {'Latitude [deg]', 'Altitude [m]'}.issubset(primary_df.columns):
                _build_cesium_card(primary_df, summary_items, f'{key}-{primary}')
            try:
                _build_graph_card(series)
            except Exception as exc:
                ui.label(f'Graph error: {exc}').classes('text-negative')

    case_sel.on_value_change(lambda _: _draw_case())
    _enumerate_small() if small else _resolve_cases()


def _build_download_row(client, job_id, state, cases) -> None:
    """PNG/SVG/CSV download buttons. The UI holds the bearer token and proxies the bytes to the
    browser (design §6): the browser never talks to the API directly. PNG/SVG/CSV cover the
    primary (first) case; when several cases are selected, a ZIP bundles every one's flight log."""
    primary = cases[0]
    phase = state['phase']
    sel = f'id:{primary}'

    def _dl_plot(fmt):
        col = 'Altitude [m]'
        data = client.plot(job_id, 'timeseries', fmt=fmt, select=sel, column=col, phase=phase)
        ui.download(data, f'job{job_id}_case{primary}_{col}.{fmt}'.replace(' ', '_'))

    def _dl_csv():
        data = client.extract_file(job_id, sel, fmt='csv', phase=phase, max_points=0)
        ui.download(data, f'job{job_id}_case{primary}.csv')

    def _dl_zip():
        # Bundle every selected case; raw (max_points=0) only for a handful, else near-full points.
        id_expr = 'id:' + ','.join(str(c) for c in cases)
        mp = 0 if len(cases) <= 3 else 20000
        data = client.extract_file(job_id, id_expr, fmt='zip', phase=phase, max_points=mp)
        ui.download(data, f'job{job_id}_cases_{"_".join(str(c) for c in cases)}.zip')

    with ui.row().classes('q-gutter-xs q-mb-xs'):
        ui.label('Download:').classes('text-caption text-grey q-my-auto')
        ui.button('PNG', on_click=lambda: _dl_plot('png')).props('dense flat color=primary')
        ui.button('SVG', on_click=lambda: _dl_plot('svg')).props('dense flat color=primary')
        ui.button('CSV', on_click=_dl_csv).props('dense flat color=primary')
        if len(cases) > 1:
            ui.button(f'All CSVs (ZIP ×{len(cases)})', on_click=_dl_zip) \
                .props('dense flat color=primary')


# ── Cards ────────────────────────────────────────────────────────────────────

def _build_summary_card(items: list):
    """items: (key, value, unit) tuples from the /result/summary API (already merged across
    per-phase summary files)."""
    if not items:
        return
    with ui.card().classes('w-full q-mb-md'):
        ui.label('Flight Summary').classes('text-subtitle2 q-mb-sm')

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


def _build_sensitivity_card(client, job_id):
    try:
        df = table_to_df(client.result_table(job_id, 'sensitivity_results'))
    except Exception:
        return
    cases_df = _safe(lambda: table_to_df(client.result_table(job_id, 'sensitivity_cases')), None)
    if df.empty:
        return

    with ui.card().classes('w-full q-mb-md'):
        ui.label('Sensitivity Analysis Results').classes('text-subtitle2 q-mb-sm')

        n_params = len(df)
        chart_h = max(180, n_params * 44 + 80)
        ui.echart(_sensitivity_tornado_opts(df)).style(f'width:100%;height:{chart_h}px')

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


def _build_mc_card(df_mc: pd.DataFrame, label: str):
    avail = [(col, disp, raw_unit, disp_unit, scale, clr)
             for col, disp, raw_unit, disp_unit, scale, clr in _MC_PARAMS
             if col in df_mc.columns]
    n = len(df_mc)
    title = 'Monte Carlo Statistics' + (f' — {label}' if label else '') + f'  (n = {n})'

    with ui.card().classes('w-full q-mb-md'):
        ui.label(title).classes('text-subtitle2 q-mb-sm')

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
                        if col == 'altitude_apogee':
                            prob = float(np.count_nonzero(arr >= REACH_ALTITUDE_THRESHOLD_KM)) / len(arr) * 100.0
                            ui.label(f'P(≥{REACH_ALTITUDE_THRESHOLD_KM:g}km): {prob:.1f}%').classes(
                                'text-caption text-weight-bold').style(f'color:{clr}')

        if n >= 10 and avail:
            with ui.grid(columns=2).classes('w-full q-mb-sm'):
                for col, disp, raw_unit, disp_unit, scale, clr in avail:
                    arr = df_mc[col].dropna().to_numpy(dtype=float) * scale
                    if len(arr) < 5:
                        continue
                    ui.echart(_mc_histogram_opts(arr.tolist(), disp, disp_unit, clr)).style(
                        'width:100%;height:220px')

        if 'lat_impact' in df_mc.columns and 'lon_impact' in df_mc.columns and n >= 3:
            lats = df_mc['lat_impact'].dropna().tolist()
            lons = df_mc['lon_impact'].dropna().tolist()
            if len(lats) >= 3:
                east, north, mean_lat, mean_lon, ne_ell, ll_ell = compute_impact_ellipses(lats, lons)
                scatter_data = [[float(e), float(nv)] for e, nv in zip(east, north)]
                ui.echart(_mc_impact_scatter_opts(scatter_data, ne_ell)).style('width:100%;height:380px')

                with ui.card().classes('w-full q-mt-sm'):
                    ui.label('Impact Points Map').classes('text-subtitle2 q-mb-xs')
                    m2 = ui.leaflet(center=(mean_lat, mean_lon), zoom=10).style('height:350px;width:100%')
                    m2.tile_layer(
                        url_template='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                        options={'attribution': '© OpenStreetMap contributors', 'maxZoom': 18},
                    )
                    step = max(1, len(lats) // 300)
                    for lat, lon in zip(lats[::step], lons[::step]):
                        m2.generic_layer(name='circleMarker', args=[
                            [float(lat), float(lon)],
                            {'radius': 3, 'color': '#ff9800', 'fillColor': '#ff9800',
                             'fillOpacity': 0.55, 'weight': 0},
                        ])
                    for _nsig, ell_clr, ll_pts in ll_ell:
                        m2.generic_layer(name='polyline', args=[
                            ll_pts, {'color': ell_clr, 'weight': 2, 'opacity': 0.85},
                        ])
                    m2.generic_layer(name='circleMarker', args=[
                        [mean_lat, mean_lon],
                        {'radius': 7, 'color': '#f44336', 'fillColor': '#f44336',
                         'fillOpacity': 1.0, 'weight': 2},
                    ])
                    bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
                    ui.timer(0.3, lambda b=bounds: m2.run_map_method(
                        'fitBounds', b, {'padding': [24, 24]}), once=True)


def _build_map_card(df: pd.DataFrame, key, summary_items: list | None = None):
    step = max(1, len(df) // 1000)
    dfs = df.iloc[::step]
    lats = dfs['Latitude [deg]'].tolist()
    lons = dfs['Longitude [deg]'].tolist()
    coords = [[lat, lon] for lat, lon in zip(lats, lons)]

    center = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
    bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

    event_positions = get_event_positions(summary_items or [], df)

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


def _build_cesium_card(df: pd.DataFrame, summary_items: list | None, key):
    step = max(1, len(df) // 2000)
    dfs = df.iloc[::step]
    lats = dfs['Latitude [deg]'].tolist()
    lons = dfs['Longitude [deg]'].tolist()
    alts = dfs['Altitude [m]'].tolist()

    flat: list[float] = []
    for la, lo, al in zip(lats, lons, alts):
        flat.extend([lo, la, max(al, 0.0)])

    event_positions = get_event_positions(summary_items or [], df)
    ev_js = _json.dumps([
        {'label': label, 'lat': lat, 'lon': lon, 'alt': max(alt, 0.0),
         'color': _EVENT_COLORS.get(label.split(':')[0].strip(), '#9e9e9e')}
        for label, lat, lon, alt in event_positions
    ])

    container_id = f'cesium-{key}'
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


def _build_graph_card(logs: list):
    """logs: [(label, DataFrame)] already fetched (decimated) via the extract API. When more than
    one case is passed they are OVERLAID on one chart (nominal vs farthest, etc.); axis/preset
    switching is client-side over the in-memory frames, no server round-trip (design §6 / B10).

    Common columns are the intersection across all cases so a chosen axis exists in every series.
    """
    if not logs:
        return
    common = list(logs[0][1].columns)
    for _lbl, df in logs[1:]:
        cset = set(df.columns)
        common = [c for c in common if c in cset]
    if not common:
        common = list(logs[0][1].columns)

    with ui.card().classes('w-full'):
        title = 'Interactive Graph' + (f'  —  {len(logs)} cases overlaid' if len(logs) > 1 else '')
        ui.label(title).classes('text-subtitle2 q-mb-xs')

        default_x = 'Time [s]'     if 'Time [s]'     in common else common[0]
        default_y = 'Altitude [m]' if 'Altitude [m]' in common else \
            (common[1] if len(common) > 1 else common[0])

        with ui.row().classes('items-center q-gutter-xs q-mb-xs'):
            ui.label('Preset:').classes('text-caption text-grey q-my-auto')
            preset_row = ui.row().classes('q-gutter-xs')

        with ui.row().classes('q-gutter-md q-mb-sm'):
            x_sel = ui.select(common, value=default_x, label='X Axis',
                              on_change=lambda _: _refresh()).style('min-width:230px')
            y_sel = ui.select(common, value=default_y, label='Y Axis',
                              on_change=lambda _: _refresh()).style('min-width:230px')

        chart = ui.echart(_echart_multi_opts(logs, default_x, default_y)).style(
            'width:100%;height:500px'
        )

        def _refresh():
            xc, yc = x_sel.value, y_sel.value
            if all(xc in df.columns and yc in df.columns for _lbl, df in logs):
                chart.options.update(_echart_multi_opts(logs, xc, yc))
                chart.update()

        def _rebuild_presets():
            preset_row.clear()
            with preset_row:
                for pn, px, py in _PRESETS:
                    if px in common and py in common:
                        def _click(x=px, y=py):
                            x_sel.set_value(x)
                            y_sel.set_value(y)
                            _refresh()
                        ui.button(pn, on_click=_click).props('dense flat color=primary')

        _rebuild_presets()
