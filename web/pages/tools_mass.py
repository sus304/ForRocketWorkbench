"""Mass budget / CG / moment-of-inertia calculator page."""
from __future__ import annotations

from nicegui import ui

from web.service_ui.layout import service_header
from web.tools import mass_budget as mb

_CG_COLORS = ['#42a5f5', '#66bb6a', '#ffa726', '#ef5350', '#ab47bc', '#26c6da', '#8d6e63', '#78909c']


def _cg_svg(rows: list, xcg: float) -> str:
    if not rows:
        return ''

    VW, VH = 700, 100
    MX, MY = 50, 18
    draw_w = VW - 2 * MX

    positions = [r['x_cg_mm'] for r in rows]
    x_min = min(positions + [xcg])
    x_max = max(positions + [xcg])
    span = max(x_max - x_min, 1.0)
    pad = span * 0.15
    x0, x1_range = x_min - pad, x_max + pad
    rng = x1_range - x0

    def sx(mm): return MX + (mm - x0) / rng * draw_w

    cy = VH / 2

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VW} {VH}" '
        f'width="100%" style="background:#0d1117;border-radius:6px;display:block;margin-top:6px">'
    ]

    # Axis
    parts.append(
        f'<line x1="{MX}" y1="{cy:.1f}" x2="{VW-MX}" y2="{cy:.1f}" '
        f'stroke="#1e3a5c" stroke-width="1.5"/>'
    )

    # Tick marks
    for i in range(5):
        tick_mm = x0 + i / 4 * rng
        tick_x = sx(tick_mm)
        parts.append(
            f'<line x1="{tick_x:.1f}" y1="{cy-3:.1f}" x2="{tick_x:.1f}" y2="{cy+3:.1f}" '
            f'stroke="#334155" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{tick_x:.1f}" y="{VH-3:.1f}" text-anchor="middle" '
            f'fill="#475569" font-size="9" font-family="monospace">{tick_mm:.0f}</text>'
        )

    # Component circles (alternating above/below axis)
    for i, row in enumerate(rows):
        cx_pos = sx(row['x_cg_mm'])
        r = max(6, min(22, row['fraction'] * 90))
        color = _CG_COLORS[i % len(_CG_COLORS)]
        above = (i % 2 == 0)
        cy_pos = cy - r - 3 if above else cy + r + 3
        parts.append(
            f'<circle cx="{cx_pos:.1f}" cy="{cy_pos:.1f}" r="{r:.1f}" '
            f'fill="{color}" opacity="0.8"/>'
        )
        name = row['name'][:8] if row['name'] else f'C{i+1}'
        parts.append(
            f'<text x="{cx_pos:.1f}" y="{cy_pos:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" fill="white" font-size="8" font-family="sans-serif">{name}</text>'
        )
        # Connector line to axis
        conn_y1 = cy_pos + r if above else cy_pos - r
        parts.append(
            f'<line x1="{cx_pos:.1f}" y1="{conn_y1:.1f}" x2="{cx_pos:.1f}" y2="{cy:.1f}" '
            f'stroke="{color}" stroke-width="1" opacity="0.5"/>'
        )

    # Total CG vertical marker
    gcx = sx(xcg)
    parts.append(
        f'<line x1="{gcx:.1f}" y1="{MY:.1f}" x2="{gcx:.1f}" y2="{VH-MY:.1f}" '
        f'stroke="#4caf50" stroke-width="2.5"/>'
    )
    parts.append(
        f'<text x="{gcx+5:.1f}" y="{MY+10:.1f}" '
        f'fill="#4caf50" font-size="10" font-family="monospace">CG: {xcg:.0f} mm</text>'
    )

    parts.append('</svg>')
    return ''.join(parts)

_DEFAULT_COMPONENTS = [
    {'name': 'Nose cone',     'mass': 0.8,  'x_cg': 130.0, 'Iyy_self': 0.0,   'Ixx': 0.0},
    {'name': 'Body tube',     'mass': 2.5,  'x_cg': 450.0, 'Iyy_self': 0.05,  'Ixx': 0.002},
    {'name': 'Fin set',       'mass': 0.4,  'x_cg': 820.0, 'Iyy_self': 0.01,  'Ixx': 0.0},
    {'name': 'Engine (dry)',  'mass': 1.5,  'x_cg': 900.0, 'Iyy_self': 0.02,  'Ixx': 0.001},
    {'name': 'Propellant',    'mass': 2.0,  'x_cg': 880.0, 'Iyy_self': 0.03,  'Ixx': 0.001},
]


@ui.page('/tools/mass')
def mass_page():
    service_header('Tools')

    # ── state ─────────────────────────────────────────────────────────────────
    import copy
    comp_data: list[dict] = copy.deepcopy(_DEFAULT_COMPONENTS)
    comp_inputs: list[dict] = []   # parallel list of ui-element dicts

    _el: dict = {}   # 'comp_panel', 'result_panel'

    # ── helpers ───────────────────────────────────────────────────────────────
    def _v(el, default: float = 0.0) -> float:
        try:
            v = el.value
            return float(v) if v is not None else default
        except Exception:
            return default

    def _save_state():
        """Flush all input values back into comp_data before rebuilding."""
        for i, ci in enumerate(comp_inputs):
            if i >= len(comp_data):
                break
            comp_data[i]['name']     = ci['name'].value or ''
            comp_data[i]['mass']     = _v(ci['mass'])
            comp_data[i]['x_cg']    = _v(ci['x_cg'])
            comp_data[i]['Iyy_self'] = _v(ci['Iyy_self'])
            comp_data[i]['Ixx']      = _v(ci['Ixx'])

    def recalc():
        panel = _el.get('result_panel')
        if panel is None:
            return
        comps = [
            {
                'name':      ci['name'].value or '',
                'mass':      _v(ci['mass']),
                'x_cg':      _v(ci['x_cg']),
                'Iyy_self':  _v(ci['Iyy_self']),
                'Ixx':       _v(ci['Ixx']),
            }
            for ci in comp_inputs
        ]
        res = mb.compute(comps)
        _render_results(panel, res)

    def _render_results(panel, res: dict):
        panel.clear()
        with panel:
            if res['total_mass'] <= 0:
                ui.label('コンポーネントを追加してください。').classes('text-grey')
                return

            # Summary metrics
            with ui.grid(columns=2).classes('w-full q-gutter-sm q-mb-sm'):
                for label, value, unit in [
                    ('Total Mass',   f"{res['total_mass']:.4f}", 'kg'),
                    ('CG from ref.', f"{res['xcg']:.1f}",       'mm'),
                    ('Iyy (lateral)',f"{res['Iyy']:.6f}",       'kg·m²'),
                    ('Ixx (axial)',  f"{res['Ixx']:.6f}",       'kg·m²'),
                ]:
                    with ui.card().classes('q-pa-sm').style('background:#1a2744'):
                        ui.label(label).classes('text-caption text-grey')
                        ui.label(f'{value} {unit}').classes('text-weight-bold')

            # Component breakdown table
            if res['rows']:
                trows = [
                    {
                        'name':    r['name'],
                        'mass':    f"{r['mass_kg']:.4f}",
                        'xcg':     f"{r['x_cg_mm']:.1f}",
                        'pct':     f"{r['fraction'] * 100:.1f}%",
                        'Iyy':     f"{r['Iyy_kgm2']:.6f}",
                        'Ixx':     f"{r['Ixx_kgm2']:.6f}",
                    }
                    for r in res['rows']
                ]
                cols = [
                    {'name': 'name', 'label': 'Component',   'field': 'name', 'align': 'left'},
                    {'name': 'mass', 'label': 'Mass [kg]',   'field': 'mass', 'align': 'right'},
                    {'name': 'xcg',  'label': 'X_CG [mm]',  'field': 'xcg',  'align': 'right'},
                    {'name': 'pct',  'label': 'Mass %',      'field': 'pct',  'align': 'right'},
                    {'name': 'Iyy',  'label': 'Iyy [kg·m²]','field': 'Iyy',  'align': 'right'},
                    {'name': 'Ixx',  'label': 'Ixx [kg·m²]','field': 'Ixx',  'align': 'right'},
                ]
                ui.table(columns=cols, rows=trows, row_key='name').classes('w-full text-caption')

            # CG position diagram
            if res['rows']:
                try:
                    ui.html(_cg_svg(res['rows'], res['xcg'])).classes('w-full')
                except Exception:
                    pass

    def rebuild_comp_panel():
        panel = _el.get('comp_panel')
        if panel is None:
            return
        panel.clear()
        comp_inputs.clear()
        with panel:
            for i, data in enumerate(comp_data):
                ci: dict = {}
                with ui.row().classes('items-center q-gutter-xs w-full no-wrap'):
                    ci['name']     = (ui.input(value=data['name'])
                                      .style('min-width:110px')
                                      .props('dense outlined')
                                      .on('blur', lambda _: recalc()))
                    ci['mass']     = (ui.number(value=data['mass'],     min=0, step=0.1, format='%.3f')
                                      .style('max-width:90px').props('dense outlined')
                                      .on_value_change(lambda _: recalc()))
                    ci['x_cg']    = (ui.number(value=data['x_cg'],     step=10,  format='%.1f')
                                      .style('max-width:90px').props('dense outlined')
                                      .on_value_change(lambda _: recalc()))
                    ci['Iyy_self'] = (ui.number(value=data.get('Iyy_self', 0), min=0, step=0.001, format='%.4f')
                                      .style('max-width:90px').props('dense outlined')
                                      .on_value_change(lambda _: recalc()))
                    ci['Ixx']      = (ui.number(value=data.get('Ixx', 0),      min=0, step=0.001, format='%.4f')
                                      .style('max-width:90px').props('dense outlined')
                                      .on_value_change(lambda _: recalc()))

                    def do_remove(idx=i):
                        _save_state()
                        comp_data.pop(idx)
                        rebuild_comp_panel()
                        recalc()

                    ui.button(icon='delete', on_click=do_remove).props('flat round dense color=negative')
                comp_inputs.append(ci)
        recalc()

    def add_comp():
        _save_state()
        comp_data.append({
            'name': f'Component {len(comp_data) + 1}',
            'mass': 1.0, 'x_cg': 500.0, 'Iyy_self': 0.0, 'Ixx': 0.0,
        })
        rebuild_comp_panel()

    # ── layout ────────────────────────────────────────────────────────────────
    with ui.row().classes('items-center q-pa-md q-gutter-sm'):
        ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/tools')).props('flat round')
        ui.label('Mass Budget & Inertia Calculator').classes('text-h6')
        ui.space()
        with ui.row().classes('q-gutter-xs'):
            ui.button('Barrowman', on_click=lambda: ui.navigate.to('/tools/barrowman')).props('flat dense').classes('text-grey')
            ui.button('Engine',    on_click=lambda: ui.navigate.to('/tools/engine')).props('flat dense').classes('text-grey')

    with ui.column().classes('q-px-md w-full q-gutter-sm'):

        # Column headers row
        with ui.row().classes('items-center q-gutter-xs w-full no-wrap q-ml-xs'):
            for label, width in [
                ('Component name',  '110px'),
                ('Mass [kg]',        '90px'),
                ('X_CG [mm]',        '90px'),
                ('Iyy_self [kg·m²]', '90px'),
                ('Ixx [kg·m²]',      '90px'),
            ]:
                ui.label(label).classes('text-caption text-grey').style(f'min-width:{width}')

        # Component rows panel
        _el['comp_panel'] = ui.column().classes('w-full')

        # Add button
        ui.button('+ Add Component', on_click=add_comp).props('flat color=primary')

        ui.separator().classes('q-my-sm')

        # Results panel
        with ui.card().classes('w-full'):
            ui.label('Results').classes('text-subtitle2 q-mb-xs')
            _el['result_panel'] = ui.column().classes('w-full')

        # Notes
        with ui.card().classes('w-full').style('background:#1a2744'):
            ui.label('Notes').classes('text-caption text-grey q-mb-xs')
            for note in [
                'Iyy_self: lateral MOI of each component about its own CG [kg·m²]',
                'Ixx: axial (spin) MOI of each component [kg·m²]',
                'Parallel-axis theorem is applied automatically: Iyy_total = Σ(Iyy_self_i + m_i · Δx_i²)',
                'X_CG is measured from the same reference point (e.g. nose tip) for all components',
            ]:
                ui.label(f'• {note}').classes('text-caption text-grey')

    # ── initialise ────────────────────────────────────────────────────────────
    rebuild_comp_panel()
