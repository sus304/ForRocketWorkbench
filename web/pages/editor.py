import json

from nicegui import ui

from web.pages.shared import build_header
from web.services.project_service import (
    scan_projects, load_json, save_json, create_project,
)

_EDITABLE_FILES = [
    'config_solver.json',
    'param_list_stage1.json',
    'param_rocket.json',
    'param_engine.json',
    'sequence_of_event.json',
    'config_area.json',
    'config_montecarlo.json',
    'config_sensitivity.json',
]

_FILE_LABELS = {
    'config_solver.json':       'Solver Config',
    'param_list_stage1.json':   'Stage-1 Config',
    'param_rocket.json':        'Rocket Parameters',
    'param_engine.json':        'Engine Parameters',
    'sequence_of_event.json':   'Sequence of Events',
    'config_area.json':         'Area Config',
    'config_montecarlo.json':   'MonteCarlo Config',
    'config_sensitivity.json':  'Sensitivity Config',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_btn(proj, fname, collect_fn):
    def _do():
        try:
            save_json(proj, fname, collect_fn())
            ui.notify('Saved.', type='positive')
        except Exception as e:
            ui.notify(f'Save failed: {e}', type='negative')
    ui.button('Save', on_click=_do).props('color=primary icon=save')


def _file_or_const(data, enable_key, file_obj_key, file_path_key,
                   const_obj_key, const_val_key, section_label, const_label,
                   default_const=0.0, const_fmt='%.4f'):
    """Render a 'Use File / Constant' toggle section. Returns (switch, file_input, const_input)."""
    file_obj  = data.get(file_obj_key, {})
    const_obj = data.get(const_obj_key, {})
    ui.label(section_label).classes('text-caption text-grey q-mb-xs')
    sw = ui.switch('Use File', value=data.get(enable_key, False))
    fi = (ui.input('File Path', value=file_obj.get(file_path_key, ''))
          .classes('w-full')
          .bind_visibility_from(sw, 'value'))
    ci = (ui.number(const_label, value=const_obj.get(const_val_key, default_const),
                    format=const_fmt)
          .bind_visibility_from(sw, 'value', backward=lambda v: not v))
    return sw, fi, ci


# ── Form builders ─────────────────────────────────────────────────────────────

def _build_solver_form(data: dict, container):
    lc = data.get('Launch Condition', {})
    wc = data.get('Wind Condition', {})

    with container:
        with ui.row().classes('w-full q-gutter-md'):
            with ui.card().classes('flex-grow'):
                ui.label('Basic').classes('text-subtitle2')
                model_id     = ui.input('Model ID',       value=data.get('Model ID', '')).classes('w-full')
                datetime_val = ui.input('Launch DateTime', value=data.get('Launch DateTime', '')).classes('w-full')
                datetime_val.tooltip('Format: YYYY/MM/DD HH:MM:SS.s')

            with ui.card().classes('flex-grow'):
                ui.label('Wind').classes('text-subtitle2')
                enable_wind = ui.switch('Enable Wind', value=wc.get('Enable Wind', False))
                wind_file   = ui.input('Wind File Path', value=wc.get('Wind File Path', '')).classes('w-full')

        with ui.card().classes('w-full'):
            ui.label('Launch Condition').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                lat       = ui.number('Latitude [deg]',   value=lc.get('Latitude [deg]', 0.0),            format='%.6f')
                lon       = ui.number('Longitude [deg]',  value=lc.get('Longitude [deg]', 0.0),           format='%.6f')
                height    = ui.number('Height [m]',       value=lc.get('Height for WGS84 [m]', 0.0),      format='%.2f')
                azimuth   = ui.number('Azimuth [deg]',    value=lc.get('Azimuth [deg]', 0.0),             format='%.2f')
                elevation = ui.number('Elevation [deg]',  value=lc.get('Elevation [deg]', 85.0),          format='%.2f')
                moving_wind = ui.switch('Moving Eqv. Wind', value=lc.get('Moving equivalent wind mode', False))

        with ui.card().classes('w-full'):
            ui.label('Initial Velocity [m/s]').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                v_n = ui.number('North', value=lc.get('North Velocity [m/s]', 0.0), format='%.4f')
                v_e = ui.number('East',  value=lc.get('East Velocity [m/s]',  0.0), format='%.4f')
                v_d = ui.number('Down',  value=lc.get('Down Velocity [m/s]',  0.0), format='%.4f')

        with ui.card().classes('w-full'):
            ui.label('Initial Angular Velocity [deg/s]').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                w_y = ui.number('Yaw',   value=lc.get('Yaw Angular Velocity [deg/s]',   0.0), format='%.4f')
                w_p = ui.number('Pitch', value=lc.get('Pitch Angular Velocity [deg/s]', 0.0), format='%.4f')
                w_r = ui.number('Roll',  value=lc.get('Roll Angular Velocity [deg/s]',  0.0), format='%.4f')

    def collect() -> dict:
        r = dict(data)
        r['Model ID']       = model_id.value
        r['Launch DateTime'] = datetime_val.value
        r['Launch Condition'] = {
            **lc,
            'Latitude [deg]': lat.value, 'Longitude [deg]': lon.value,
            'Height for WGS84 [m]': height.value,
            'Azimuth [deg]': azimuth.value, 'Elevation [deg]': elevation.value,
            'North Velocity [m/s]': v_n.value, 'East Velocity [m/s]': v_e.value,
            'Down Velocity [m/s]': v_d.value,
            'Yaw Angular Velocity [deg/s]': w_y.value,
            'Pitch Angular Velocity [deg/s]': w_p.value,
            'Roll Angular Velocity [deg/s]': w_r.value,
            'Moving equivalent wind mode': moving_wind.value,
        }
        r['Wind Condition'] = {'Enable Wind': enable_wind.value, 'Wind File Path': wind_file.value}
        return r

    return collect


def _build_stage_form(data: dict, container):
    with container:
        with ui.card().classes('w-full'):
            ui.label('Stage-1 Configuration File Paths').classes('text-subtitle2')
            ui.label('各ファイルはプロジェクトフォルダからの相対パス').classes('text-caption text-grey q-mb-xs')
            with ui.column().classes('w-full q-gutter-sm'):
                rocket = ui.input('Rocket Configuration File Path',
                                  value=data.get('Rocket Configuration File Path', 'param_rocket.json')).classes('w-full')
                engine = ui.input('Engine Configuration File Path',
                                  value=data.get('Engine Configuration File Path', 'param_engine.json')).classes('w-full')
                soe    = ui.input('Sequence of Event File Path',
                                  value=data.get('Sequence of Event File Path', 'sequence_of_event.json')).classes('w-full')

    def collect() -> dict:
        return {
            'Rocket Configuration File Path':  rocket.value,
            'Engine Configuration File Path':  engine.value,
            'Sequence of Event File Path':     soe.value,
        }

    return collect


def _build_rocket_form(data: dict, container):
    mass   = data.get('Mass', {})
    gj     = data.get('Gas Jet', {})
    pa     = data.get('Program Attitude', {})
    xcg_c  = data.get('Constant X-C.G.', {})
    # v4.3.0+ keeps the lateral CG offset in a dedicated "C.G. Offset" block;
    # fall back to the legacy nested keys under "Constant X-C.G." for old files.
    cg_off = data.get('C.G. Offset', xcg_c)
    poi_c  = data.get('Constant Product of Inertia', {})
    poi_f  = data.get('Product of Inertia File', {})

    with container:
        # ── Basic ─────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Basic').classes('text-subtitle2')
            with ui.grid(columns=2).classes('w-full'):
                diameter = ui.number('Diameter [mm]', value=data.get('Diameter [mm]', 200), format='%.1f')
                length   = ui.number('Length [mm]',   value=data.get('Length [mm]',   3500), format='%.1f')

        # ── Mass ──────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Mass').classes('text-subtitle2')
            with ui.grid(columns=2).classes('w-full'):
                mass_inert = ui.number('Inert [kg]',      value=mass.get('Inert [kg]',      40.0),  format='%.4f')
                mass_prop  = ui.number('Propellant [kg]', value=mass.get('Propellant [kg]', 25.0),  format='%.4f')

        # ── Gas Jet ────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Gas Jet').classes('text-subtitle2')
            en_gj = ui.switch('Enable Gas Jet', value=data.get('Enable Gas Jet', False))
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_gj, 'value'):
                gj_moment   = ui.number('Rolling Moment [N·m]', value=gj.get('Rolling Moment [N.m]', 0.0), format='%.4f')
                gj_duration = ui.number('Duration [s]',         value=gj.get('Duration [s]',          0.0), format='%.4f')

        # ── Program Attitude ───────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Program Attitude').classes('text-subtitle2')
            en_pa = ui.switch('Enable Program Attitude', value=data.get('Enable Program Attitude', False))
            with ui.column().classes('w-full q-gutter-xs').bind_visibility_from(en_pa, 'value'):
                pa_mode = ui.select(['Angle', 'Rate', 'Quaternion'],
                                    value=pa.get('Mode', 'Angle'), label='Mode')
                with ui.row().classes('q-gutter-md'):
                    pa_yaw   = ui.switch('Enable Yaw',   value=pa.get('Enable Yaw',   False))
                    pa_pitch = ui.switch('Enable Pitch', value=pa.get('Enable Pitch', False))
                    pa_roll  = ui.switch('Enable Roll',  value=pa.get('Enable Roll',  False))
                pa_file = ui.input('File Path', value=pa.get('File Path', '')).classes('w-full')

        # ── X-C.G. ────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('X-C.G. from Body Tail').classes('text-subtitle2')
            en_xcg, xcg_file, xcg_const = _file_or_const(
                data, 'Enable X-C.G. File',
                'X-C.G. File',     'X-C.G. File Path',
                'Constant X-C.G.', 'Constant X-C.G. from BodyTail [mm]',
                'X-C.G.', 'Constant [mm]', 1800.0, '%.2f',
            )
            # Lateral CG offset is an inert-value constant (ForRocket derives the
            # full-vehicle time history internally) — editable in both X-C.G. modes.
            with ui.grid(columns=2).classes('w-full'):
                cg_off_y = ui.number('y-C.G. Offset [mm]', value=cg_off.get('y-C.G. Offset [mm]', 0.0), format='%.4f')
                cg_off_z = ui.number('z-C.G. Offset [mm]', value=cg_off.get('z-C.G. Offset [mm]', 0.0), format='%.4f')

        # ── M.I. ──────────────────────────────────────────────────────────
        mi_c = data.get('Constant M.I.', {})
        mi_f = data.get('M.I. File', {})
        with ui.card().classes('w-full'):
            ui.label('Moment of Inertia').classes('text-subtitle2')
            en_mi   = ui.switch('Use File', value=data.get('Enable M.I. File', False))
            mi_file = (ui.input('File Path', value=mi_f.get('M.I. File Path', ''))
                       .classes('w-full').bind_visibility_from(en_mi, 'value'))
            with ui.grid(columns=3).classes('w-full').bind_visibility_from(en_mi, 'value', backward=lambda v: not v):
                mi_yaw   = ui.number('Yaw [kg·m²]',   value=mi_c.get('Yaw Axis [kg-m2]',   120.0), format='%.4f')
                mi_pitch = ui.number('Pitch [kg·m²]', value=mi_c.get('Pitch Axis [kg-m2]', 120.0), format='%.4f')
                mi_roll  = ui.number('Roll [kg·m²]',  value=mi_c.get('Roll Axis [kg-m2]',    0.5), format='%.4f')

        # ── Product of Inertia ─────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Product of Inertia').classes('text-subtitle2')
            poi_mode = ui.select(
                ['Disabled', 'Constant', 'File'],
                value=('File' if data.get('Enable Product of Inertia File', False)
                       else ('Constant' if data.get('Enable Product of Inertia', False) else 'Disabled')),
                label='Mode',
            )
            with ui.grid(columns=3).classes('w-full').bind_visibility_from(poi_mode, 'value', backward=lambda v: v == 'Constant'):
                poi_ixy = ui.number('Ixy [kg·m²]', value=poi_c.get('Ixy [kg-m2]', 0.0), format='%.6f')
                poi_ixz = ui.number('Ixz [kg·m²]', value=poi_c.get('Ixz [kg-m2]', 0.0), format='%.6f')
                poi_iyz = ui.number('Iyz [kg·m²]', value=poi_c.get('Iyz [kg-m2]', 0.0), format='%.6f')
            with ui.column().classes('w-full q-gutter-xs').bind_visibility_from(poi_mode, 'value', backward=lambda v: v == 'File'):
                poi_f_ixy = ui.input('Ixy File Path', value=poi_f.get('Ixy File Path', '')).classes('w-full')
                poi_f_ixz = ui.input('Ixz File Path', value=poi_f.get('Ixz File Path', '')).classes('w-full')
                poi_f_iyz = ui.input('Iyz File Path', value=poi_f.get('Iyz File Path', '')).classes('w-full')

        # ── X-C.P. ────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('X-C.P. from Body Tail').classes('text-subtitle2')
            en_xcp, xcp_file, xcp_const = _file_or_const(
                data, 'Enable X-C.P. File',
                'X-C.P. File',     'X-C.P. File Path',
                'Constant X-C.P.', 'Constant X-C.P. from BodyTail [mm]',
                'X-C.P.', 'Constant [mm]', 1400.0, '%.2f',
            )

        # ── Thrust Loading Point ───────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Thrust Loading Point').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                thr_pt   = ui.number('X from Body Tail [mm]', value=data.get('X-ThrustLoadingPoint from BodyTail [mm]', 0.0), format='%.2f')
                thr_pt_y = ui.number('y-Offset [mm]',         value=data.get('y-ThrustLoadingPoint Offset [mm]', 0.0),        format='%.4f')
                thr_pt_z = ui.number('z-Offset [mm]',         value=data.get('z-ThrustLoadingPoint Offset [mm]', 0.0),        format='%.4f')

        # ── CA ────────────────────────────────────────────────────────────
        ca_f = data.get('CA File', {})
        ca_c = data.get('Constant CA', {})
        with ui.card().classes('w-full'):
            ui.label('Axial Force Coefficient CA').classes('text-subtitle2')
            en_ca = ui.switch('Use File', value=data.get('Enable CA File', False))
            with ui.column().classes('w-full').bind_visibility_from(en_ca, 'value'):
                ca_path    = ui.input('CA File Path',        value=ca_f.get('CA File Path',        '')).classes('w-full')
                ca_bo_path = ui.input('BurnOut CA File Path', value=ca_f.get('BurnOut CA File Path', '')).classes('w-full')
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_ca, 'value', backward=lambda v: not v):
                ca_val    = ui.number('Constant CA [-]',         value=ca_c.get('Constant CA [-]',         0.5), format='%.4f')
                ca_bo_val = ui.number('Constant BurnOut CA [-]', value=ca_c.get('Constant BurnOut CA [-]', 0.5), format='%.4f')

        # ── CNα ───────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Normal Force Coefficient CNα').classes('text-subtitle2')
            en_cna, cna_file, cna_const = _file_or_const(
                data, 'Enable CNa File',
                'CNa File',     'CNa File Path',
                'Constant CNa', 'Constant CNa [1/rad]',
                'CNα', 'Constant CNα [1/rad]', 5.0, '%.4f',
            )

        # ── Fin Cant & Cld ─────────────────────────────────────────────────
        cld_f = data.get('Cld File', {})
        cld_c = data.get('Constant Cld', {})
        with ui.card().classes('w-full'):
            ui.label('Roll Force Coefficient Cld / Fin Cant').classes('text-subtitle2')
            fin_cant = ui.number('Fin Cant Angle [deg]',
                                 value=data.get('Fin Cant Angle [deg]', 0.0), format='%.4f')
            en_cld, cld_file, cld_const = _file_or_const(
                data, 'Enable Cld File',
                'Cld File',     'Cld File Path',
                'Constant Cld', 'Constant Cld [1/rad]',
                'Cld', 'Constant Cld [1/rad]', 0.0, '%.4f',
            )

        # ── Clp ───────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Roll Damping Coefficient Clp').classes('text-subtitle2')
            en_clp, clp_file, clp_const = _file_or_const(
                data, 'Enable Clp File',
                'Clp File',     'Clp File Path',
                'Constant Clp', 'Constant Clp [-]',
                'Clp', 'Constant Clp [-]', -0.02, '%.4f',
            )

        # ── Cmq ───────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Pitch Damping Coefficient Cmq').classes('text-subtitle2')
            en_cmq, cmq_file, cmq_const = _file_or_const(
                data, 'Enable Cmq File',
                'Cmq File',     'Cmq File Path',
                'Constant Cmq', 'Constant Cmq [-]',
                'Cmq', 'Constant Cmq [-]', -2.0, '%.4f',
            )

        # ── Cnr ───────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Yaw Damping Coefficient Cnr').classes('text-subtitle2')
            en_cnr, cnr_file, cnr_const = _file_or_const(
                data, 'Enable Cnr File',
                'Cnr File',     'Cnr File Path',
                'Constant Cnr', 'Constant Cnr [-]',
                'Cnr', 'Constant Cnr [-]', -2.0, '%.4f',
            )

    def collect() -> dict:
        r = dict(data)
        r['Diameter [mm]'] = diameter.value
        r['Length [mm]']   = length.value
        r['Mass'] = {'Inert [kg]': mass_inert.value, 'Propellant [kg]': mass_prop.value}
        r['Enable Gas Jet'] = en_gj.value
        r['Gas Jet'] = {'Rolling Moment [N.m]': gj_moment.value, 'Duration [s]': gj_duration.value}
        r['Enable Program Attitude'] = en_pa.value
        r['Program Attitude'] = {
            'Mode': pa_mode.value, 'Enable Yaw': pa_yaw.value,
            'Enable Pitch': pa_pitch.value, 'Enable Roll': pa_roll.value,
            'File Path': pa_file.value,
        }
        r['Enable X-C.G. File'] = en_xcg.value
        r['X-C.G. File']     = {'X-C.G. File Path': xcg_file.value}
        r['Constant X-C.G.'] = {'Constant X-C.G. from BodyTail [mm]': xcg_const.value}
        r['C.G. Offset'] = {
            'y-C.G. Offset [mm]': cg_off_y.value,
            'z-C.G. Offset [mm]': cg_off_z.value,
        }
        r['Enable M.I. File'] = en_mi.value
        r['M.I. File']    = {'M.I. File Path': mi_file.value}
        r['Constant M.I.'] = {
            'Yaw Axis [kg-m2]':   mi_yaw.value,
            'Pitch Axis [kg-m2]': mi_pitch.value,
            'Roll Axis [kg-m2]':  mi_roll.value,
        }
        r['Enable Product of Inertia']      = (poi_mode.value == 'Constant')
        r['Enable Product of Inertia File'] = (poi_mode.value == 'File')
        r['Constant Product of Inertia'] = {
            'Ixy [kg-m2]': poi_ixy.value,
            'Ixz [kg-m2]': poi_ixz.value,
            'Iyz [kg-m2]': poi_iyz.value,
        }
        r['Product of Inertia File'] = {
            'Ixy File Path': poi_f_ixy.value,
            'Ixz File Path': poi_f_ixz.value,
            'Iyz File Path': poi_f_iyz.value,
        }
        r['Enable X-C.P. File'] = en_xcp.value
        r['X-C.P. File']     = {'X-C.P. File Path': xcp_file.value}
        r['Constant X-C.P.'] = {'Constant X-C.P. from BodyTail [mm]': xcp_const.value}
        r['X-ThrustLoadingPoint from BodyTail [mm]'] = thr_pt.value
        r['y-ThrustLoadingPoint Offset [mm]'] = thr_pt_y.value
        r['z-ThrustLoadingPoint Offset [mm]'] = thr_pt_z.value
        r['Enable CA File'] = en_ca.value
        r['CA File'] = {'CA File Path': ca_path.value, 'BurnOut CA File Path': ca_bo_path.value}
        r['Constant CA'] = {'Constant CA [-]': ca_val.value, 'Constant BurnOut CA [-]': ca_bo_val.value}
        r['Enable CNa File'] = en_cna.value
        r['CNa File']     = {'CNa File Path': cna_file.value}
        r['Constant CNa'] = {'Constant CNa [1/rad]': cna_const.value}
        r['Fin Cant Angle [deg]'] = fin_cant.value
        r['Enable Cld File'] = en_cld.value
        r['Cld File']     = {'Cld File Path': cld_file.value}
        r['Constant Cld'] = {'Constant Cld [1/rad]': cld_const.value}
        r['Enable Clp File'] = en_clp.value
        r['Clp File']     = {'Clp File Path': clp_file.value}
        r['Constant Clp'] = {'Constant Clp [-]': clp_const.value}
        r['Enable Cmq File'] = en_cmq.value
        r['Cmq File']     = {'Cmq File Path': cmq_file.value}
        r['Constant Cmq'] = {'Constant Cmq [-]': cmq_const.value}
        r['Enable Cnr File'] = en_cnr.value
        r['Cnr File']     = {'Cnr File Path': cnr_file.value}
        r['Constant Cnr'] = {'Constant Cnr [-]': cnr_const.value}
        return r

    return collect


def _build_engine_form(data: dict, container):
    tf = data.get('Thrust File', {})
    ct = data.get('Constant Thrust', {})
    ma = data.get('Engine Miss-Alignment', {})

    with container:
        with ui.card().classes('w-full'):
            ui.label('Nozzle').classes('text-subtitle2')
            nozzle_d = ui.number('Nozzle Exit Diameter [mm]',
                                 value=data.get('Nozzle Exit Diameter [mm]', 150.0), format='%.2f')

        with ui.card().classes('w-full'):
            ui.label('Thrust').classes('text-subtitle2')
            en_tf = ui.switch('Enable Thrust File', value=data.get('Enable Thrust File', False))
            tf_path = (ui.input('Thrust at vacuum File Path',
                                value=tf.get('Thrust at vacuum File Path', ''))
                       .classes('w-full')
                       .bind_visibility_from(en_tf, 'value'))
            with ui.grid(columns=3).classes('w-full').bind_visibility_from(en_tf, 'value', backward=lambda v: not v):
                ct_thrust   = ui.number('Thrust at vacuum [N]',          value=ct.get('Thrust at vacuum [N]', 8000.0),          format='%.2f')
                ct_mdot     = ui.number('Mass Flow Rate [kg/s]',          value=ct.get('Propellant Mass Flow Rate [kg/s]', 1.67), format='%.4f')
                ct_duration = ui.number('Burn Duration [s]',              value=ct.get('Burn Duration [sec]', 15.0),             format='%.3f')

        with ui.card().classes('w-full'):
            ui.label('Engine Miss-Alignment').classes('text-subtitle2')
            en_miss = ui.switch('Enable Engine Miss Alignment', value=data.get('Enable Engine Miss Alignment', False))
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_miss, 'value'):
                miss_y = ui.number('y-Axis Angle [deg]', value=ma.get('y-Axis Angle [deg]', 0.0), format='%.4f')
                miss_z = ui.number('z-Axis Angle [deg]', value=ma.get('z-Axis Angle [deg]', 0.0), format='%.4f')

    def collect() -> dict:
        r = dict(data)
        r['Nozzle Exit Diameter [mm]'] = nozzle_d.value
        r['Enable Thrust File'] = en_tf.value
        r['Thrust File']    = {'Thrust at vacuum File Path': tf_path.value}
        r['Constant Thrust'] = {
            'Thrust at vacuum [N]': ct_thrust.value,
            'Propellant Mass Flow Rate [kg/s]': ct_mdot.value,
            'Burn Duration [sec]': ct_duration.value,
        }
        r['Enable Engine Miss Alignment'] = en_miss.value
        r['Engine Miss-Alignment'] = {
            'y-Axis Angle [deg]': miss_y.value,
            'z-Axis Angle [deg]': miss_z.value,
        }
        return r

    return collect


def _build_soe_form(data: dict, container):
    rail   = data.get('Rail Launcher', {})
    cutoff = data.get('Cutoff', {})
    sep    = data.get('Upper Stage', {})
    despin = data.get('Despin', {})
    fair   = data.get('Fairing', {})
    para   = data.get('Parachute', {})
    para2  = data.get('Secondary Parachute', {})

    with container:
        # ── Timing basics ─────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Flight Timing').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                t_start  = ui.number('Flight Start Time [s]',    value=data.get('Flight Start Time [s]',    0.0), format='%.3f')
                t_ignite = ui.number('Engine Ignition Time [s]', value=data.get('Engine Ignittion Time [s]', 0.0), format='%.3f')
                t_end    = ui.number('Flight End Time [s]',      value=data.get('Flight End Time [s]',    500.0), format='%.3f')
                dt       = ui.number('Time Step [s]',            value=data.get('Time Step [s]',            0.1), format='%.4f')
                en_auto  = ui.switch('Auto Terminate SubOrbital', value=data.get('Enable Auto Terminate SubOrbital Flight', True))

        # ── Adaptive Solver Tolerance (v4.4.0+) ───────────────────────────
        # 適応ステップ積分器の許容誤差（v4.4.0 で導入された任意キー）。
        # Abs は姿勢(クォータニオン等の小振幅状態)の精度を支配し、Rel は ECI 位置
        # (~6.4e6 m)の精度と計算速度を支配する。既定 Abs=1e-8/Rel=1e-6 は、v4.4.0 の
        # 高速化(~60x)を保ちつつ姿勢精度のロバスト性を確保するバランス点。
        # Rel を厳しくするほど高精度だが大幅に低速、Abs を緩めると姿勢が発散しやすい。
        with ui.card().classes('w-full'):
            ui.label('Adaptive Solver Tolerance').classes('text-subtitle2')
            with ui.grid(columns=2).classes('w-full'):
                tol_abs = ui.number('Solver Tolerance Abs', value=data.get('Solver Tolerance Abs', 1.0e-8), format='%.1e')
                tol_rel = ui.number('Solver Tolerance Rel', value=data.get('Solver Tolerance Rel', 1.0e-6), format='%.1e')

        # ── Rail Launcher ─────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Rail Launcher').classes('text-subtitle2')
            en_rail  = ui.switch('Enable Rail-Launcher', value=data.get('Enable Rail-Launcher Launch', True))
            rail_len = (ui.number('Length [m]', value=rail.get('Length [m]', 5.0), format='%.3f')
                        .bind_visibility_from(en_rail, 'value'))

        # ── Engine Cutoff ─────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Engine Cutoff').classes('text-subtitle2')
            en_cut    = ui.switch('Enable Engine Cutoff', value=data.get('Enable Engine Cutoff', False))
            cutoff_t  = (ui.number('Cutoff Time [s]', value=cutoff.get('Cutoff Time [s]', 0.0), format='%.3f')
                         .bind_visibility_from(en_cut, 'value'))

        # ── Stage Separation ──────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Stage Separation').classes('text-subtitle2')
            en_sep    = ui.switch('Enable Stage Separation', value=data.get('Enable Stage Separation', False))
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_sep, 'value'):
                sep_t    = ui.number('Separation Time [s]', value=sep.get('Stage Separation Time [s]', 0.0), format='%.3f')
                sep_mass = ui.number('Upper Stage Mass [kg]', value=sep.get('Upper Stage Mass [kg]', 0.0),   format='%.4f')

        # ── Despin ────────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Despin Control').classes('text-subtitle2')
            en_despin = ui.switch('Enable Despin', value=data.get('Enable Despin Control', False))
            despin_t  = (ui.number('Despin Time [s]', value=despin.get('Time [s]', 0.0), format='%.3f')
                         .bind_visibility_from(en_despin, 'value'))

        # ── Fairing ───────────────────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Fairing Jettison').classes('text-subtitle2')
            en_fair = ui.switch('Enable Fairing Jettison', value=data.get('Enable Fairing Jettson', False))
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_fair, 'value'):
                fair_t    = ui.number('Jettison Time [s]', value=fair.get('Jettson Time [s]', 0.0),  format='%.3f')
                fair_mass = ui.number('Mass [kg]',         value=fair.get('Mass [kg]', 0.0),         format='%.4f')

        # ── Parachute (Primary) ───────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Parachute (Primary)').classes('text-subtitle2')
            en_para      = ui.switch('Enable Parachute Open', value=data.get('Enable Parachute Open', True))
            with ui.column().classes('w-full').bind_visibility_from(en_para, 'value'):
                with ui.grid(columns=3).classes('w-full'):
                    para_t    = ui.number('Open Time [s]',       value=para.get('Open Time [s]', 0.0),          format='%.3f')
                    para_cds  = ui.number('Cd·S [m²]',           value=para.get('Drag Factor Cd*S [m2]', 3.0),   format='%.4f')
                    en_forced = ui.switch('Force Open at Apogee', value=para.get('Enable Forced Apogee Open', True))

        # ── Parachute (Secondary) ─────────────────────────────────────────
        with ui.card().classes('w-full'):
            ui.label('Parachute (Secondary)').classes('text-subtitle2')
            en_para2 = ui.switch('Enable Secondary Parachute', value=data.get('Enable Secondary Parachute Open', False))
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_para2, 'value'):
                para2_t   = ui.number('Open Time [s]', value=para2.get('Open Time [s]', 0.0),         format='%.3f')
                para2_cds = ui.number('Cd·S [m²]',    value=para2.get('Drag Factor Cd*S [m2]', 0.0), format='%.4f')

    def collect() -> dict:
        r = dict(data)
        r['Flight Start Time [s]']    = t_start.value
        r['Engine Ignittion Time [s]'] = t_ignite.value
        r['Enable Rail-Launcher Launch'] = en_rail.value
        r['Rail Launcher'] = {'Length [m]': rail_len.value}
        r['Enable Engine Cutoff'] = en_cut.value
        r['Cutoff'] = {'Cutoff Time [s]': cutoff_t.value}
        r['Enable Stage Separation'] = en_sep.value
        r['Upper Stage'] = {
            'Stage Separation Time [s]': sep_t.value,
            'Upper Stage Mass [kg]': sep_mass.value,
        }
        r['Enable Despin Control'] = en_despin.value
        r['Despin'] = {'Time [s]': despin_t.value}
        r['Enable Fairing Jettson'] = en_fair.value
        r['Fairing'] = {'Jettson Time [s]': fair_t.value, 'Mass [kg]': fair_mass.value}
        r['Enable Parachute Open'] = en_para.value
        r['Parachute'] = {
            'Open Time [s]': para_t.value,
            'Drag Factor Cd*S [m2]': para_cds.value,
            'Enable Forced Apogee Open': en_forced.value,
        }
        r['Enable Secondary Parachute Open'] = en_para2.value
        r['Secondary Parachute'] = {
            'Open Time [s]': para2_t.value,
            'Drag Factor Cd*S [m2]': para2_cds.value,
        }
        r['Flight End Time [s]'] = t_end.value
        r['Time Step [s]']        = dt.value
        r['Solver Tolerance Abs'] = tol_abs.value
        r['Solver Tolerance Rel'] = tol_rel.value
        r['Enable Auto Terminate SubOrbital Flight'] = en_auto.value
        return r

    return collect


# ── JSON fallback editor ───────────────────────────────────────────────────────

def _build_json_editor(proj, fname, data):
    json_text = json.dumps(data, indent=4, ensure_ascii=False) if data is not None else '{}'
    json_area = ui.textarea(value=json_text).classes('w-full').style(
        'font-family:monospace; min-height:500px;'
    )
    with ui.row().classes('q-mt-sm q-gutter-sm'):
        def save_json_text():
            try:
                parsed = json.loads(json_area.value)
                save_json(proj, fname, parsed)
                ui.notify('Saved.', type='positive')
            except json.JSONDecodeError as e:
                ui.notify(f'JSON parse error: {e}', type='negative')

        ui.button('Save', on_click=save_json_text).props('color=primary icon=save')
        ui.button('Reformat', on_click=lambda: (
            json_area.set_value(
                json.dumps(json.loads(json_area.value), indent=4, ensure_ascii=False)
            )
        )).props('flat icon=format_align_left')


# ── Routing ────────────────────────────────────────────────────────────────────

_FORM_BUILDERS = {
    'config_solver.json':     _build_solver_form,
    'param_list_stage1.json': _build_stage_form,
    'param_rocket.json':      _build_rocket_form,
    'param_engine.json':      _build_engine_form,
    'sequence_of_event.json': _build_soe_form,
}


# ── Page ──────────────────────────────────────────────────────────────────────

@ui.page('/editor')
def editor_page():
    ui.navigate.to('/calculate')
