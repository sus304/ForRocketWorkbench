"""Barrowman CP / static margin calculator page."""
from __future__ import annotations

from nicegui import ui

from web.service_ui.layout import service_header
from web.tools import barrowman as bm

_NOSE_OPTIONS = {k: v for k, v in bm.NOSE_LABELS.items()}

# (g1x, g1y, g2x)
# g1x: P1の先端からのx位置 (ノーズ長さ比)
# g1y: P1の中心線からのy位置 (半径比)
# g2x: P2のボディ根元からの手前オフセット (ノーズ長さ比)
#      P2.y = top_y/bot_y (ボディ直径) → 根元で水平接線 → 段差なし
_NOSE_CUBIC = {
    'tangent_ogive': (0.15, 0.70, 0.08),
    'haack':         (0.10, 0.80, 0.06),
    'von_karman':    (0.10, 0.80, 0.06),
    'parabolic':     (0.25, 0.50, 0.20),
    'power_series':  (0.30, 0.40, 0.25),
    'elliptical':    (0.05, 0.92, 0.05),
}


def _rocket_svg(
    nose_len: float,
    nose_type: str,
    d_ref: float,
    fin_sets: list,
    boattail,
    xcp,
    xcg,
) -> str:
    VW = 700
    MX = 55
    draw_w = VW - 2 * MX

    r_ref = max(d_ref / 2, 1.0)
    nose_len = max(nose_len, 1.0)

    body_end = nose_len
    for fs in fin_sets:
        if fs.get('Cr', 0) > 0:
            body_end = max(body_end, fs['x_root_le'] + fs['Cr'])
    if boattail:
        body_end = max(body_end, boattail['x_front'] + boattail['length'])
    total = max(body_end, nose_len + 10.0)

    scale = draw_w / total
    r_scaled = r_ref * scale

    max_span_r = r_ref
    for fs in fin_sets:
        if fs.get('span', 0) > 0 and fs.get('d_body', 0) > 0:
            max_span_r = max(max_span_r, fs['d_body'] / 2 + fs['span'])
    max_r_scaled = max_span_r * scale

    VH = max(180, int(2 * max_r_scaled + 100))
    cy = VH / 2 - 8

    def sx(mm): return MX + mm * scale
    def sy(r):  return cy - r * scale  # 正の r → 画面上方

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VW} {VH}" '
        f'width="100%" style="background:var(--wb-bg);border-radius:6px;display:block">'
    ]

    # Centerline
    parts.append(
        f'<line x1="{sx(0):.1f}" y1="{cy:.1f}" x2="{sx(total):.1f}" y2="{cy:.1f}" '
        f'stroke="#1e3a5c" stroke-width="1" stroke-dasharray="6,4"/>'
    )

    # ── ノーズベジェ計算 ──────────────────────────────────────────
    tx, nx = sx(0), sx(nose_len)
    top_y, bot_y = sy(r_ref), sy(-r_ref)
    dx = nx - tx

    if nose_type == 'conical':
        nose_upper = f'L {nx:.1f} {top_y:.1f}'
        nose_lower = f'L {tx:.1f} {cy:.1f}'
    else:
        g1x, g1y, g2x = _NOSE_CUBIC.get(nose_type, (0.15, 0.70, 0.08))
        p1x     = tx + dx * g1x
        p1y_top = cy - r_scaled * g1y
        p1y_bot = cy + r_scaled * g1y
        p2x     = nx - dx * g2x           # P2.y = top_y/bot_y → 根元で水平接線
        nose_upper = f'C {p1x:.1f} {p1y_top:.1f} {p2x:.1f} {top_y:.1f} {nx:.1f} {top_y:.1f}'
        nose_lower = f'C {p2x:.1f} {bot_y:.1f} {p1x:.1f} {p1y_bot:.1f} {tx:.1f} {cy:.1f}'

    # ── フィン (ボディより先に描画して根本をボディで隠す) ──────────
    for fs in fin_sets:
        Cr   = fs.get('Cr', 0)
        span = fs.get('span', 0)
        if Cr <= 0 or span <= 0:
            continue
        xrl = fs['x_root_le']
        Ct  = fs.get('Ct', 0)
        swp = fs.get('sweep_le', 0)
        rb  = fs['d_body'] / 2
        x1, x2 = sx(xrl), sx(xrl + swp)
        x3, x4 = sx(xrl + swp + Ct), sx(xrl + Cr)
        for above in (False, True):
            yr = sy(rb)  if above else sy(-rb)
            yt = sy(rb + span) if above else sy(-(rb + span))
            fp = f'M {x1:.1f} {yr:.1f} L {x2:.1f} {yt:.1f} L {x3:.1f} {yt:.1f} L {x4:.1f} {yr:.1f} Z'
            parts.append(f'<path d="{fp}" fill="#152050" stroke="#64b5f6" stroke-width="1.5"/>')

    # ── ロケット本体を1つのパスで描画 (継ぎ目ゼロ) ───────────────
    # 上半分: 先端 → ノーズ曲線 → ボディ上面 → 後端/ボートテール
    # 下半分: 後端 → ボディ下面 → ノーズ曲線 → 先端 (逆順)
    body_path = [f'M {tx:.1f} {cy:.1f}', nose_upper]

    if boattail:
        bbt0 = sx(boattail['x_front'])
        bbt1 = sx(boattail['x_front'] + boattail['length'])
        r1_bt, r2_bt = boattail['d1'] / 2, boattail['d2'] / 2
        body_path += [
            f'L {bbt0:.1f} {top_y:.1f}',           # 上ボディ
            f'L {bbt0:.1f} {sy(r1_bt):.1f}',       # ボートテール前端 (段差)
            f'L {bbt1:.1f} {sy(r2_bt):.1f}',       # 上テーパー
            f'L {bbt1:.1f} {sy(-r2_bt):.1f}',      # 後端キャップ
            f'L {bbt0:.1f} {sy(-r1_bt):.1f}',      # 下テーパー
            f'L {bbt0:.1f} {bot_y:.1f}',            # ボートテール前端 (段差)
            f'L {nx:.1f} {bot_y:.1f}',              # 下ボディ
        ]
    else:
        rear_x = sx(body_end)
        body_path += [
            f'L {rear_x:.1f} {top_y:.1f}',         # 上ボディ
            f'L {rear_x:.1f} {bot_y:.1f}',         # 後端キャップ
            f'L {nx:.1f} {bot_y:.1f}',              # 下ボディ
        ]

    body_path += [nose_lower, 'Z']
    parts.append(
        f'<path d="{" ".join(body_path)}" fill="#1e3060" stroke="#42a5f5" stroke-width="1.5"/>'
    )

    # ── CP マーカー ───────────────────────────────────────────────
    if xcp is not None and 0 < xcp <= total * 1.05:
        cpx = sx(xcp)
        parts.append(
            f'<line x1="{cpx:.1f}" y1="{sy(r_ref)+4:.1f}" '
            f'x2="{cpx:.1f}" y2="{sy(-r_ref)-4:.1f}" '
            f'stroke="#e91e63" stroke-width="2" stroke-dasharray="5,3"/>'
        )
        parts.append(f'<circle cx="{cpx:.1f}" cy="{cy:.1f}" r="6" fill="#e91e63" opacity="0.9"/>')
        parts.append(
            f'<text x="{cpx:.1f}" y="{sy(r_ref)-10:.1f}" text-anchor="middle" '
            f'fill="#e91e63" font-size="12" font-family="monospace">CP</text>'
        )

    # ── CG マーカー ───────────────────────────────────────────────
    if xcg is not None and 0 < xcg <= total * 1.05:
        cgx = sx(xcg)
        parts.append(
            f'<line x1="{cgx:.1f}" y1="{sy(r_ref)+4:.1f}" '
            f'x2="{cgx:.1f}" y2="{sy(-r_ref)-4:.1f}" '
            f'stroke="#4caf50" stroke-width="2" stroke-dasharray="5,3"/>'
        )
        parts.append(f'<circle cx="{cgx:.1f}" cy="{cy:.1f}" r="6" fill="#4caf50" opacity="0.9"/>')
        parts.append(
            f'<text x="{cgx:.1f}" y="{sy(-r_ref)+18:.1f}" text-anchor="middle" '
            f'fill="#4caf50" font-size="12" font-family="monospace">CG</text>'
        )

    # ── 全長寸法 ──────────────────────────────────────────────────
    dim_y = sy(-max_span_r) + 28
    parts.append(
        f'<line x1="{sx(0):.1f}" y1="{dim_y:.1f}" x2="{sx(total):.1f}" y2="{dim_y:.1f}" '
        f'stroke="#334155" stroke-width="1"/>'
    )
    for tick_x in (sx(0), sx(total)):
        parts.append(
            f'<line x1="{tick_x:.1f}" y1="{dim_y-3:.1f}" '
            f'x2="{tick_x:.1f}" y2="{dim_y+3:.1f}" stroke="#334155" stroke-width="1"/>'
        )
    parts.append(
        f'<text x="{(sx(0)+sx(total))/2:.1f}" y="{dim_y+13:.1f}" text-anchor="middle" '
        f'fill="#475569" font-size="11" font-family="monospace">{total:.0f} mm</text>'
    )

    # ── 凡例 (右上) ──────────────────────────────────────────────
    legend = []
    if xcp is not None and 0 < xcp <= total * 1.05:
        legend.append(('#e91e63', f'CP {xcp:.0f} mm'))
    if xcg is not None and 0 < xcg <= total * 1.05:
        legend.append(('#4caf50', f'CG {xcg:.0f} mm'))
    for i, (color, text) in enumerate(legend):
        ly = 14 + i * 16
        parts.append(f'<circle cx="{VW-MX+8}" cy="{ly}" r="4" fill="{color}"/>')
        parts.append(
            f'<text x="{VW-MX}" y="{ly+4}" text-anchor="end" '
            f'fill="{color}" font-size="11" font-family="monospace">{text}</text>'
        )

    parts.append('</svg>')
    return ''.join(parts)


@ui.page('/tools/barrowman')
def barrowman_page():
    service_header('Tools')

    # ── mutable state shared across closures ──────────────────────────────────
    fin_set_inputs: list[dict] = []   # ui-element dicts per fin set
    _el: dict = {}                    # 'fin_cards_panel', 'result_panel', inputs

    # ── helpers ───────────────────────────────────────────────────────────────
    def _v(el, default: float = 0.0) -> float:
        try:
            v = el.value
            return float(v) if v is not None else default
        except Exception:
            return default

    def recalc():
        panel = _el.get('result_panel')
        if panel is None:
            return

        comps: list[dict] = [{
            'type':      'nose',
            'name':      'Nose',
            'nose_type': _el['nose_type'].value or 'tangent_ogive',
            'length':    _v(_el['nose_len']),
        }]

        for i, fi in enumerate(fin_set_inputs):
            comps.append({
                'type':      'fins',
                'name':      f'Fin Set {i + 1}',
                'n':         max(1, int(_v(fi['n'], 4))),
                'Cr':        _v(fi['Cr']),
                'Ct':        _v(fi['Ct']),
                'span':      _v(fi['span']),
                'sweep_le':  _v(fi['sweep_le']),
                'd_body':    _v(fi['d_body']),
                'x_root_le': _v(fi['x_root_le']),
            })

        if _el.get('trans_sw') and _el['trans_sw'].value:
            comps.append({
                'type':    'transition',
                'name':    'Boattail',
                'd_front': _v(_el['trans_d1']),
                'd_rear':  _v(_el['trans_d2']),
                'length':  _v(_el['trans_len']),
                'x_front': _v(_el['trans_x']),
            })

        d_ref_v = max(_v(_el['d_ref'], 1), 1)
        xcg_v   = _v(_el['xcg']) if _el['xcg'].value is not None else None

        res = bm.compute(comps, d_ref_v, xcg_v)
        _render_results(panel, res)

    def _render_results(panel, res: dict):
        panel.clear()
        with panel:
            # ── 1. 静的安定余裕 (最上部に常時表示) ──────────────────
            sm = res['static_margin']
            if sm is not None:
                if sm >= 2.0:
                    color, icon, badge_col = 'positive', '✓', 'positive'
                elif sm >= 1.0:
                    color, icon, badge_col = 'positive', '✓', 'positive'
                elif sm >= 0:
                    color, icon, badge_col = 'warning', '△', 'warning'
                else:
                    color, icon, badge_col = 'negative', '✗', 'negative'

                stable_str = (
                    'Stable  ≥ 2 cal' if sm >= 2.0 else
                    'Marginally stable' if sm >= 1.0 else
                    'Unstable  < 1 cal' if sm >= 0 else
                    'Unstable  CP ahead of CG'
                )
                try:
                    _nl = _v(_el['nose_len']) if 'nose_len' in _el else 0
                    _be = _nl
                    for _fi in fin_set_inputs:
                        _be = max(_be, _v(_fi['x_root_le']) + _v(_fi['Cr']))
                    if _el.get('trans_sw') and _el['trans_sw'].value:
                        _be = max(_be, _v(_el['trans_x']) + _v(_el['trans_len']))
                    _total_len = max(_be, _nl + 10.0)
                    _d_ref = max(_v(_el['d_ref'], 1), 1.0) if 'd_ref' in _el else 1.0
                    sm_len_pct = sm * _d_ref / _total_len * 100
                except Exception:
                    sm_len_pct = None

                with ui.card().classes('w-full q-pa-sm q-mb-xs wb-subpanel').style(
                    f'border-left:3px solid var(--q-{badge_col})'
                ):
                    with ui.row().classes('items-center q-gutter-md no-wrap'):
                        ui.label(f'{icon} Static Margin').classes(f'text-caption text-{color}')
                        sm_str = f"{sm:.2f} cal"
                        if sm_len_pct is not None:
                            sm_str += f"  /  {sm_len_pct:.1f} %L"
                        ui.label(sm_str).classes(f'text-weight-bold text-h5 text-{color}')
                        ui.label(stable_str).classes('text-caption text-grey q-ml-sm')
            elif not res['rows']:
                ui.label('有効なコンポーネントがありません。').classes('text-grey')

            # ── 2. ロケット形状 SVG ───────────────────────────────
            try:
                nose_type_v = (_el['nose_type'].value or 'tangent_ogive') if 'nose_type' in _el else 'tangent_ogive'
                nose_len_v  = _v(_el['nose_len']) if 'nose_len' in _el else 400.0
                d_ref_v     = max(_v(_el['d_ref'], 150), 1.0) if 'd_ref' in _el else 150.0
                xcg_v       = _v(_el['xcg']) if ('xcg' in _el and _el['xcg'].value is not None) else None
                fs_data = [
                    {
                        'Cr': _v(fi['Cr']), 'Ct': _v(fi['Ct']),
                        'span': _v(fi['span']), 'sweep_le': _v(fi['sweep_le']),
                        'd_body': max(_v(fi['d_body']), 1.0), 'x_root_le': _v(fi['x_root_le']),
                    }
                    for fi in fin_set_inputs
                ]
                bt = None
                if _el.get('trans_sw') and _el['trans_sw'].value:
                    bt = {
                        'd1': _v(_el['trans_d1']), 'd2': _v(_el['trans_d2']),
                        'length': _v(_el['trans_len']), 'x_front': _v(_el['trans_x']),
                    }
                xcp_v = res.get('xcp_total') if res.get('rows') else None
                ui.html(_rocket_svg(nose_len_v, nose_type_v, d_ref_v, fs_data, bt, xcp_v, xcg_v)).classes('w-full q-mb-sm')
            except Exception:
                pass

            if not res['rows']:
                return

            # ── 3. コンポーネントテーブル ─────────────────────────
            table_rows = [
                {
                    'component': r['component'],
                    'cna':       f"{r['CNa']:.4f}",
                    'xcp':       f"{r['xcp']:.1f}",
                }
                for r in res['rows']
            ]
            cols = [
                {'name': 'component', 'label': 'Component',  'field': 'component', 'align': 'left'},
                {'name': 'cna',       'label': 'CNα',        'field': 'cna',       'align': 'right'},
                {'name': 'xcp',       'label': 'XCP [mm]',   'field': 'xcp',       'align': 'right'},
            ]
            ui.table(columns=cols, rows=table_rows, row_key='component').classes('w-full')

            ui.separator().classes('q-my-sm')

            # ── 4. 合計値 ─────────────────────────────────────────
            with ui.row().classes('q-gutter-xl q-mt-xs items-end'):
                with ui.column():
                    ui.label('Total CNα').classes('text-caption text-grey')
                    ui.label(f"{res['CNa_total']:.4f}").classes('text-weight-bold text-h6')
                with ui.column():
                    ui.label('XCP from nose').classes('text-caption text-grey')
                    ui.label(f"{res['xcp_total']:.1f} mm").classes('text-weight-bold text-h6')

    def rebuild_fins(count: int):
        fp = _el.get('fin_cards_panel')
        if fp is None:
            return
        fp.clear()
        fin_set_inputs.clear()
        with fp:
            for i in range(count):
                fi: dict = {}
                with ui.card().classes('w-full q-mb-xs wb-subpanel'):
                    ui.label(f'Fin Set {i + 1}').classes('text-subtitle2 q-mb-xs')
                    with ui.grid(columns=4).classes('w-full'):
                        fi['n']         = ui.number('N fins',              value=4,   min=3, max=16, step=1,
                                                    on_change=lambda _: recalc()).props('dense')
                        fi['Cr']        = ui.number('Root chord Cr [mm]',  value=200, min=0,
                                                    on_change=lambda _: recalc()).props('dense')
                        fi['Ct']        = ui.number('Tip chord Ct [mm]',   value=100, min=0,
                                                    on_change=lambda _: recalc()).props('dense')
                        fi['span']      = ui.number('Span b [mm]',         value=150, min=0,
                                                    on_change=lambda _: recalc()).props('dense')
                        fi['sweep_le']  = (ui.number('LE sweep offset [mm]', value=50, min=0,
                                                    on_change=lambda _: recalc()).props('dense')
                                           .tooltip('Horizontal distance from root leading edge to tip leading edge'))
                        fi['d_body']    = ui.number('Body Ø at fins [mm]', value=150, min=1,
                                                    on_change=lambda _: recalc()).props('dense')
                        fi['x_root_le'] = ui.number('Root LE from nose [mm]', value=700, min=0,
                                                    on_change=lambda _: recalc()).props('dense')
                fin_set_inputs.append(fi)
        recalc()

    # ── layout ────────────────────────────────────────────────────────────────
    with ui.row().classes('items-center q-pa-md q-gutter-sm'):
        ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/tools')).props('flat round')
        ui.label('Barrowman CP Calculator').classes('text-h6')
        ui.badge('Subsonic · Barrowman 1967').props('color=blue-grey outline')
        ui.space()
        with ui.row().classes('q-gutter-xs'):
            ui.button('Mass', on_click=lambda: ui.navigate.to('/tools/mass')).props('flat dense').classes('text-grey')
            ui.button('Engine', on_click=lambda: ui.navigate.to('/tools/engine')).props('flat dense').classes('text-grey')

    with ui.row().classes('w-full no-wrap q-px-md q-gutter-md'):
        # ── Left: inputs ──────────────────────────────────────────────────────
        with ui.column().classes('q-gutter-sm').style('min-width:520px; max-width:680px'):

            # Reference
            with ui.card().classes('w-full'):
                ui.label('Reference').classes('text-subtitle2 q-mb-xs')
                with ui.row().classes('q-gutter-md'):
                    _el['d_ref'] = (ui.number('Reference diameter d_ref [mm]', value=150, min=1,
                                              on_change=lambda _: recalc())
                                    .tooltip('Max body diameter used as reference for CNα and static margin'))
                    _el['xcg']   = (ui.number('CG from nose tip [mm]  (optional)', value=None,
                                              on_change=lambda _: recalc())
                                    .tooltip('If set, static margin = (XCP − XCG) / d_ref'))

            # Nose cone
            with ui.card().classes('w-full'):
                ui.label('Nose Cone').classes('text-subtitle2 q-mb-xs')
                with ui.row().classes('q-gutter-md items-center'):
                    _el['nose_type'] = (ui.select(_NOSE_OPTIONS, value='tangent_ogive', label='Shape',
                                                  on_change=lambda _: recalc())
                                        .style('min-width:220px'))
                    _el['nose_len']  = ui.number('Length [mm]', value=400, min=0,
                                                 on_change=lambda _: recalc())
                ui.label('CNα = 2.0 for all shapes (subsonic, Barrowman)').classes('text-caption text-grey')

            # Fin sets
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center q-mb-xs'):
                    ui.label('Fin Sets').classes('text-subtitle2')
                    ui.space()
                    ui.number('Sets', value=1, min=1, max=4, step=1,
                              on_change=lambda e: rebuild_fins(max(1, int(e.value or 1)))
                              ).props('dense').style('max-width:80px')
                _el['fin_cards_panel'] = ui.column().classes('w-full')

            # Boattail / transition
            with ui.card().classes('w-full'):
                ui.label('Boattail / Transition  (optional)').classes('text-subtitle2')
                _el['trans_sw'] = ui.switch('Include boattail / transition', on_change=lambda _: recalc())
                with ui.grid(columns=4).classes('w-full q-mt-xs'):
                    _el['trans_d1']  = ui.number('Front Ø d₁ [mm]',    value=150, min=1,  on_change=lambda _: recalc()).props('dense')
                    _el['trans_d2']  = ui.number('Rear Ø d₂ [mm]',     value=100, min=1,  on_change=lambda _: recalc()).props('dense')
                    _el['trans_len'] = ui.number('Length [mm]',          value=100, min=0,  on_change=lambda _: recalc()).props('dense')
                    _el['trans_x']   = ui.number('Position (nose) [mm]', value=900, min=0,  on_change=lambda _: recalc()).props('dense')

        # ── Right: results ────────────────────────────────────────────────────
        with ui.column().classes('flex-grow q-gutter-sm'):
            with ui.card().classes('w-full'):
                ui.label('Results').classes('text-subtitle2 q-mb-xs')
                _el['result_panel'] = ui.column().classes('w-full')

            # Reference card
            with ui.card().classes('w-full wb-subpanel'):
                ui.label('Barrowman Method Notes').classes('text-caption text-grey q-mb-xs')
                notes = [
                    'CNα = 2 for all subsonic nose shapes',
                    'Fin CNα includes body-fin interference factor (1 + r/s)',
                    'Static Margin = (XCP − XCG) / d_ref [calibers]',
                    'SM ≥ 2 cal: well-stabilised  |  SM < 1 cal: unstable',
                    'Valid for subsonic, axisymmetric, low-angle-of-attack flight',
                ]
                for note in notes:
                    ui.label(f'• {note}').classes('text-caption text-grey')

    # ── initialise after all elements are created ─────────────────────────────
    rebuild_fins(1)
