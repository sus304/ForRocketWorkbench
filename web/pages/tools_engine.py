"""Hybrid rocket engine performance calculator page."""
from __future__ import annotations

from matplotlib import pyplot as plt
from nicegui import ui

from web.service_ui.layout import service_header
from web.tools import engine_perf as ep

_FUEL_KEYS = list(ep.FUEL_PRESETS.keys())


def _grain_svg(d_port_mm: float, d_outer_mm: float, L_grain_mm: float) -> str:
    r_out = max(d_outer_mm / 2, 1.0)
    r_in  = min(d_port_mm / 2, r_out * 0.97)

    VW, VH = 580, 135
    cs_cx, cs_cy = 72, VH / 2 - 4
    r_draw = 52
    r_in_draw = r_draw * r_in / r_out

    sv_x0 = 150
    sv_w  = VW - sv_x0 - 18
    h_out = r_draw * 2
    h_in  = h_out * r_in / r_out
    sv_cy = VH / 2 - 4

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VW} {VH}" '
        f'width="100%" style="background:var(--wb-bg);border-radius:6px;display:block">'
    ]

    # Cross-section
    parts.append(f'<text x="{cs_cx}" y="11" text-anchor="middle" fill="#546e7a" font-size="9" font-family="monospace">CROSS-SECTION</text>')
    parts.append(f'<circle cx="{cs_cx}" cy="{cs_cy:.1f}" r="{r_draw}" fill="#5d3519" stroke="#ffa726" stroke-width="1.5"/>')
    # The port reads as a hole punched through to the page, so it takes the page-ground token.
    # Set via `style` rather than the `fill` attribute: var() in an SVG presentation attribute is
    # not reliably supported, while a style declaration always is.
    parts.append(f'<circle cx="{cs_cx}" cy="{cs_cy:.1f}" r="{r_in_draw:.1f}" style="fill:var(--wb-bg)" stroke="#64b5f6" stroke-width="1"/>')
    parts.append(f'<text x="{cs_cx}" y="{cs_cy+r_draw+14:.1f}" text-anchor="middle" fill="#ffa726" font-size="9" font-family="monospace">Ø{d_outer_mm:.0f} mm</text>')
    if r_in_draw > 12:
        parts.append(f'<text x="{cs_cx}" y="{cs_cy:.1f}" text-anchor="middle" dominant-baseline="middle" fill="#64b5f6" font-size="9" font-family="monospace">Ø{d_port_mm:.0f}</text>')
    else:
        parts.append(f'<text x="{cs_cx}" y="{cs_cy-r_in_draw-5:.1f}" text-anchor="middle" fill="#64b5f6" font-size="9" font-family="monospace">Ø{d_port_mm:.0f}</text>')

    # Side view
    parts.append(f'<text x="{sv_x0+sv_w/2:.1f}" y="11" text-anchor="middle" fill="#546e7a" font-size="9" font-family="monospace">SIDE VIEW</text>')
    parts.append(
        f'<rect x="{sv_x0}" y="{sv_cy-h_out/2:.1f}" '
        f'width="{sv_w:.1f}" height="{h_out:.1f}" '
        f'fill="#5d3519" stroke="#ffa726" stroke-width="1.5" rx="2"/>'
    )
    parts.append(
        f'<rect x="{sv_x0}" y="{sv_cy-h_in/2:.1f}" '
        f'width="{sv_w:.1f}" height="{h_in:.1f}" '
        f'style="fill:var(--wb-bg)" stroke="#64b5f6" stroke-width="1"/>'
    )

    # Length dimension
    dim_y = sv_cy + h_out / 2 + 16
    parts.append(f'<line x1="{sv_x0}" y1="{dim_y:.1f}" x2="{sv_x0+sv_w:.1f}" y2="{dim_y:.1f}" stroke="#334155" stroke-width="1"/>')
    for xt in (sv_x0, sv_x0 + sv_w):
        parts.append(f'<line x1="{xt:.1f}" y1="{dim_y-3:.1f}" x2="{xt:.1f}" y2="{dim_y+3:.1f}" stroke="#334155" stroke-width="1"/>')
    parts.append(f'<text x="{sv_x0+sv_w/2:.1f}" y="{dim_y+12:.1f}" text-anchor="middle" fill="#475569" font-size="10" font-family="monospace">L = {L_grain_mm:.0f} mm</text>')

    # Outer diameter arrow (left of side view)
    ax = sv_x0 - 12
    parts.append(f'<line x1="{ax}" y1="{sv_cy-h_out/2:.1f}" x2="{ax}" y2="{sv_cy+h_out/2:.1f}" stroke="#ffa726" stroke-width="1"/>')
    parts.append(f'<text x="{ax-3:.1f}" y="{sv_cy+4:.1f}" text-anchor="end" fill="#ffa726" font-size="9" font-family="monospace">Ø{d_outer_mm:.0f}</text>')

    parts.append('</svg>')
    return ''.join(parts)


@ui.page('/tools/engine')
def engine_page():
    service_header('Tools')

    _el: dict = {}   # holds all input ui-elements + 'result_panel', 'chart_holder'

    # ── helpers ───────────────────────────────────────────────────────────────
    def _v(key: str, default: float = 0.0) -> float:
        try:
            v = _el[key].value
            return float(v) if v is not None else default
        except Exception:
            return default

    def _apply_fuel_preset(name: str):
        p = ep.FUEL_PRESETS.get(name, {})
        if p:
            _el['rho'].set_value(p['rho'])
            _el['a'].set_value(p['a'])
            _el['n_reg'].set_value(p['n'])
        recalc()

    def _get_cf() -> float:
        """Return Cf: compute from expansion ratio, or use manual input."""
        if _el['cf_mode'].value == 'compute':
            try:
                Pc_est = 2e6     # rough estimate for first iteration
                return ep.calc_cf(
                    _v('gamma', 1.25),
                    _v('eps', 4.0),
                    Pc_est,
                    _v('Pa', 101325.0),
                )
            except Exception:
                return 1.5
        else:
            return _v('Cf_manual', 1.5)

    def recalc():
        rp = _el.get('result_panel')
        ch = _el.get('chart_holder')
        if rp is None:
            return

        try:
            Cf = _get_cf()
            pt = ep.calc_point(
                m_dot_ox   = _v('m_dot_ox', 0.5),
                d_port_mm  = _v('d_port', 50.0),
                L_grain_mm = _v('L_grain', 400.0),
                rho_fuel   = _v('rho', 920.0),
                a          = _v('a', 0.116),
                n          = _v('n_reg', 0.347),
                cstar      = _v('cstar', 1550.0) * _v('eta_cstar', 0.95),
                d_throat_mm= _v('d_throat', 30.0),
                Cf         = Cf,
            )
        except Exception as exc:
            rp.clear()
            with rp:
                ui.label(f'計算エラー: {exc}').classes('text-negative')
            return

        _render_results(rp, pt, Cf)

        if ch is not None and _el.get('run_sim') and _el['run_sim'].value:
            _run_simulation(ch, Cf)

    def _render_results(panel, pt: dict, Cf: float):
        panel.clear()
        with panel:
            # Fuel grain cross-section / side-view diagram
            try:
                ui.html(_grain_svg(
                    _v('d_port', 50.0),
                    _v('d_outer', 120.0),
                    _v('L_grain', 400.0),
                )).classes('w-full q-mb-sm')
            except Exception:
                pass

            metrics = [
                ('Oxidizer Flux G_ox', f"{pt['G_ox']:.1f}",       'kg/m²/s'),
                ('Regression Rate',    f"{pt['rdot_mms']:.3f}",   'mm/s'),
                ('Fuel Mass Flow',     f"{pt['m_dot_fuel']:.4f}", 'kg/s'),
                ('Total Mass Flow',    f"{pt['m_dot_tot']:.4f}",  'kg/s'),
                ('O/F Ratio',          f"{pt['OF']:.3f}",         '—'),
                ('Chamber Pressure',   f"{pt['Pc_MPa']:.3f}",     'MPa'),
                ('Thrust Coeff. Cf',   f"{Cf:.4f}",               '—'),
                ('Thrust',             f"{pt['F_N']:.1f}",        'N'),
                ('Specific Impulse',   f"{pt['Isp_s']:.1f}",      's'),
            ]
            with ui.grid(columns=3).classes('w-full q-gutter-xs'):
                for label, val, unit in metrics:
                    with ui.card().classes('q-pa-sm wb-subpanel'):
                        ui.label(label).classes('text-caption text-grey')
                        ui.label(f'{val}').classes('text-weight-bold text-h6')
                        ui.label(unit).classes('text-caption text-grey')

    def _run_simulation(chart_holder, Cf: float):
        try:
            sim = ep.burn_simulation(
                m_ox_total    = _v('m_ox_total', 2.0),
                m_dot_ox      = _v('m_dot_ox', 0.5),
                d_port_init_mm= _v('d_port', 50.0),
                d_outer_mm    = _v('d_outer', 120.0),
                L_grain_mm    = _v('L_grain', 400.0),
                rho_fuel      = _v('rho', 920.0),
                a             = _v('a', 0.116),
                n             = _v('n_reg', 0.347),
                cstar         = _v('cstar', 1550.0) * _v('eta_cstar', 0.95),
                d_throat_mm   = _v('d_throat', 30.0),
                Cf            = Cf,
                dt            = 0.05,
            )
        except Exception as exc:
            chart_holder.clear()
            with chart_holder:
                ui.label(f'シミュレーションエラー: {exc}').classes('text-negative')
            return

        _render_sim_results(chart_holder, sim)

    def _render_sim_results(chart_holder, sim: dict):
        chart_holder.clear()
        with chart_holder:
            # Summary row
            with ui.row().classes('q-gutter-xl q-mb-sm'):
                for label, val, unit in [
                    ('Burn Time',      f"{sim['burn_time']:.2f}",      's'),
                    ('Total Impulse',  f"{sim['total_impulse']:.1f}",  'N·s'),
                    ('Avg Thrust',     f"{sim['avg_thrust']:.1f}",     'N'),
                    ('Avg Isp',        f"{sim['avg_Isp']:.1f}",        's'),
                ]:
                    with ui.column():
                        ui.label(label).classes('text-caption text-grey')
                        ui.label(f'{val} {unit}').classes('text-weight-bold')

            if not sim['times']:
                ui.label('燃焼データなし').classes('text-grey')
                return

            # Chart
            with ui.pyplot(figsize=(9, 4)) as p:
                fig = p.fig
                fig.patch.set_facecolor('#121212')

                ax1 = fig.add_subplot(211)
                ax1.set_facecolor('#1a1a2e')
                ax1.plot(sim['times'], sim['thrusts'], color='#42a5f5', linewidth=2)
                ax1.set_ylabel('Thrust [N]', color='#90a4ae')
                ax1.tick_params(colors='#90a4ae')
                ax1.grid(True, alpha=0.2, color='#444')
                for spine in ax1.spines.values():
                    spine.set_edgecolor('#333')

                ax2 = fig.add_subplot(212, sharex=ax1)
                ax2.set_facecolor('#1a1a2e')
                ax2.plot(sim['times'], sim['OFs'],  color='#ef5350', linewidth=2, label='O/F')
                ax2.plot(sim['times'], sim['Pcs'],  color='#66bb6a', linewidth=2, label='Pc [MPa]')
                ax2.set_xlabel('Time [s]', color='#90a4ae')
                ax2.set_ylabel('O/F  /  Pc [MPa]', color='#90a4ae')
                ax2.tick_params(colors='#90a4ae')
                ax2.grid(True, alpha=0.2, color='#444')
                ax2.legend(facecolor='#1a1a2e', edgecolor='#333', labelcolor='#90a4ae', fontsize=8)
                for spine in ax2.spines.values():
                    spine.set_edgecolor('#333')

                fig.tight_layout(pad=0.5)

    # ── layout ────────────────────────────────────────────────────────────────
    with ui.row().classes('items-center q-pa-md q-gutter-sm'):
        ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/tools')).props('flat round')
        ui.label('Hybrid Engine Performance Calculator').classes('text-h6')
        ui.space()
        with ui.row().classes('q-gutter-xs'):
            ui.button('Barrowman', on_click=lambda: ui.navigate.to('/tools/barrowman')).props('flat dense').classes('text-grey')
            ui.button('Mass',      on_click=lambda: ui.navigate.to('/tools/mass')).props('flat dense').classes('text-grey')

    with ui.row().classes('w-full no-wrap q-px-md q-gutter-md'):
        # ── Left: parameters ──────────────────────────────────────────────────
        with ui.column().classes('q-gutter-sm').style('min-width:440px; max-width:580px'):

            # Fuel
            with ui.card().classes('w-full'):
                ui.label('Fuel').classes('text-subtitle2 q-mb-xs')
                fuel_sel = ui.select(
                    _FUEL_KEYS, value=_FUEL_KEYS[0], label='Fuel preset',
                    on_change=lambda e: _apply_fuel_preset(e.value),
                ).classes('w-full')
                with ui.grid(columns=3).classes('w-full q-mt-xs'):
                    _el['rho']   = ui.number('Density ρ [kg/m³]', value=920,   min=1,   on_change=lambda _: recalc()).props('dense')
                    _el['a']     = (ui.number('Reg. coeff. a', value=0.116, min=0, step=0.001, format='%.4f',
                                             on_change=lambda _: recalc())
                                   .props('dense')
                                   .tooltip('r_dot [mm/s] = a × G_ox^n   (G_ox in kg/m²/s)'))
                    _el['n_reg'] = (ui.number('Reg. exp. n',   value=0.347, min=0, max=1, step=0.01, format='%.3f',
                                             on_change=lambda _: recalc())
                                   .props('dense'))

            # Grain geometry
            with ui.card().classes('w-full'):
                ui.label('Fuel Grain').classes('text-subtitle2 q-mb-xs')
                with ui.grid(columns=3).classes('w-full'):
                    _el['d_port']  = ui.number('Port Ø d_i [mm]',  value=50,  min=1,  on_change=lambda _: recalc()).props('dense')
                    _el['d_outer'] = ui.number('Outer Ø d_o [mm]', value=120, min=1,  on_change=lambda _: recalc()).props('dense')
                    _el['L_grain'] = ui.number('Length L [mm]',     value=400, min=1,  on_change=lambda _: recalc()).props('dense')

            # Oxidizer
            with ui.card().classes('w-full'):
                ui.label('Oxidizer').classes('text-subtitle2 q-mb-xs')
                with ui.row().classes('q-gutter-md'):
                    _el['m_dot_ox']   = ui.number('Mass flow ṁ_ox [kg/s]', value=0.50, min=0.001, step=0.01, format='%.3f',
                                                   on_change=lambda _: recalc()).props('dense')
                    _el['m_ox_total'] = ui.number('Total ox. mass [kg]',    value=2.0,  min=0.01,
                                                   on_change=lambda _: recalc()).props('dense').tooltip('Used only in burn simulation')

            # Nozzle & thermodynamics
            with ui.card().classes('w-full'):
                ui.label('Nozzle & Thermodynamics').classes('text-subtitle2 q-mb-xs')
                with ui.grid(columns=3).classes('w-full'):
                    _el['d_throat']   = ui.number('Throat Ø d_t [mm]',   value=30,   min=1,   on_change=lambda _: recalc()).props('dense')
                    _el['cstar']      = ui.number('c* ideal [m/s]',       value=1550, min=100, on_change=lambda _: recalc()).props('dense')
                    _el['eta_cstar']  = (ui.number('c* efficiency η',     value=0.95, min=0.1, max=1.0, step=0.01, format='%.2f',
                                                    on_change=lambda _: recalc())
                                        .props('dense')
                                        .tooltip('c*_eff = η × c*_ideal'))

                ui.separator().classes('q-my-xs')
                ui.label('Thrust Coefficient Cf').classes('text-caption text-grey')
                with ui.row().classes('items-center q-gutter-sm'):
                    _el['cf_mode'] = ui.radio(
                        {'compute': 'Compute from ε & γ', 'manual': 'Manual input'},
                        value='compute', on_change=lambda _: recalc(),
                    ).props('inline dense')

                with ui.grid(columns=4).classes('w-full q-mt-xs'):
                    _el['eps']       = ui.number('Expansion ratio ε',  value=4.0,  min=1.0, step=0.5, format='%.1f',
                                                  on_change=lambda _: recalc()).props('dense')
                    _el['gamma']     = ui.number('Specific heat ratio γ', value=1.25, min=1.0, max=1.7, step=0.01, format='%.2f',
                                                  on_change=lambda _: recalc()).props('dense')
                    _el['Pa']        = ui.number('Ambient P_a [Pa]',   value=101325, min=0,
                                                  on_change=lambda _: recalc()).props('dense')
                    _el['Cf_manual'] = ui.number('Cf (manual)',         value=1.50, min=0.5, max=2.5, step=0.01, format='%.2f',
                                                  on_change=lambda _: recalc()).props('dense')

            # Burn simulation toggle
            with ui.card().classes('w-full'):
                ui.label('Burn Simulation').classes('text-subtitle2')
                _el['run_sim'] = ui.switch(
                    'Run burn simulation (Euler integration)',
                    on_change=lambda _: recalc(),
                )
                ui.label('Integrates port growth over time assuming constant ṁ_ox.').classes('text-caption text-grey')

        # ── Right: results ────────────────────────────────────────────────────
        with ui.column().classes('flex-grow q-gutter-sm'):
            with ui.card().classes('w-full'):
                ui.label('Steady-State Operating Point').classes('text-subtitle2 q-mb-xs')
                _el['result_panel'] = ui.column().classes('w-full')

            with ui.card().classes('w-full'):
                ui.label('Burn Simulation Results').classes('text-subtitle2 q-mb-xs')
                _el['chart_holder'] = ui.column().classes('w-full')
                ui.label('Enable simulation toggle on the left to run.').classes('text-caption text-grey')

    # ── initialise ────────────────────────────────────────────────────────────
    recalc()
