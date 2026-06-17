"""Config Editor + Calculation Launcher — merged workspace page."""
import json

from fastapi import Request
from nicegui import ui

from web.pages.shared import build_header
from web.services.calc_service import current_job, start_calculation, cancel_calculation
from web.services.project_service import (
    scan_projects, get_project_files, load_json, save_json, create_project,
)

# ── Constants ──────────────────────────────────────────────────────────────────

_MODE_LABELS = {
    'trajectory':  'Trajectory',
    'area':        'Area',
    'montecarlo':  'MonteCarlo',
    'sensitivity': 'Sensitivity',
}
_REQUIRED_FILES = {
    'trajectory':  ['config_solver.json', 'param_list_stage1.json', 'param_rocket.json',
                    'param_engine.json', 'sequence_of_event.json'],
    'area':        ['config_solver.json', 'param_list_stage1.json', 'param_rocket.json',
                    'param_engine.json', 'sequence_of_event.json', 'config_area.json'],
    'montecarlo':  ['config_solver.json', 'param_list_stage1.json', 'param_rocket.json',
                    'param_engine.json', 'sequence_of_event.json', 'config_montecarlo.json'],
    'sensitivity': ['config_solver.json', 'param_list_stage1.json', 'param_rocket.json',
                    'param_engine.json', 'sequence_of_event.json', 'config_sensitivity.json'],
}
_EDITABLE_FILES = [
    'config_solver.json', 'param_list_stage1.json', 'param_rocket.json',
    'param_engine.json', 'sequence_of_event.json',
    'config_area.json', 'config_montecarlo.json', 'config_sensitivity.json',
]
_FILE_LABELS = {
    'config_solver.json':      'Solver Config',
    'param_list_stage1.json':  'Stage-1 Config',
    'param_rocket.json':       'Rocket Parameters',
    'param_engine.json':       'Engine Parameters',
    'sequence_of_event.json':  'Sequence of Events',
    'config_area.json':        'Area Config',
    'config_montecarlo.json':  'MonteCarlo Config',
    'config_sensitivity.json': 'Sensitivity Config',
}


# ── Editor helpers ─────────────────────────────────────────────────────────────

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


# ── Form builders ──────────────────────────────────────────────────────────────

def _build_solver_form(data: dict, container):
    lc = data.get('Launch Condition', {})
    wc = data.get('Wind Condition', {})

    with container:
        with ui.row().classes('w-full q-gutter-md'):
            with ui.card().classes('flex-grow'):
                ui.label('Basic').classes('text-subtitle2')
                model_id     = ui.input('Model ID',        value=data.get('Model ID', '')).classes('w-full')
                datetime_val = ui.input('Launch DateTime', value=data.get('Launch DateTime', '')).classes('w-full')
                datetime_val.tooltip('Format: YYYY/MM/DD HH:MM:SS.s')

            with ui.card().classes('flex-grow'):
                ui.label('Wind').classes('text-subtitle2')
                enable_wind = ui.switch('Enable Wind', value=wc.get('Enable Wind', False))
                wind_file   = ui.input('Wind File Path', value=wc.get('Wind File Path', '')).classes('w-full')

        with ui.card().classes('w-full'):
            ui.label('Launch Condition').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                lat        = ui.number('Latitude [deg]',  value=lc.get('Latitude [deg]', 0.0),           format='%.6f')
                lon        = ui.number('Longitude [deg]', value=lc.get('Longitude [deg]', 0.0),          format='%.6f')
                height     = ui.number('Height [m]',      value=lc.get('Height for WGS84 [m]', 0.0),     format='%.2f')
                azimuth    = ui.number('Azimuth [deg]',   value=lc.get('Azimuth [deg]', 0.0),            format='%.2f')
                elevation  = ui.number('Elevation [deg]', value=lc.get('Elevation [deg]', 85.0),         format='%.2f')
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
        r['Model ID']        = model_id.value
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
            'Rocket Configuration File Path': rocket.value,
            'Engine Configuration File Path': engine.value,
            'Sequence of Event File Path':    soe.value,
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
        with ui.card().classes('w-full'):
            ui.label('Basic').classes('text-subtitle2')
            with ui.grid(columns=2).classes('w-full'):
                diameter = ui.number('Diameter [mm]', value=data.get('Diameter [mm]', 200), format='%.1f')
                length   = ui.number('Length [mm]',   value=data.get('Length [mm]',   3500), format='%.1f')

        with ui.card().classes('w-full'):
            ui.label('Mass').classes('text-subtitle2')
            with ui.grid(columns=2).classes('w-full'):
                mass_inert = ui.number('Inert [kg]',      value=mass.get('Inert [kg]',      40.0), format='%.4f')
                mass_prop  = ui.number('Propellant [kg]', value=mass.get('Propellant [kg]', 25.0), format='%.4f')

        with ui.card().classes('w-full'):
            ui.label('Gas Jet').classes('text-subtitle2')
            en_gj = ui.switch('Enable Gas Jet', value=data.get('Enable Gas Jet', False))
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_gj, 'value'):
                gj_moment   = ui.number('Rolling Moment [N·m]', value=gj.get('Rolling Moment [N.m]', 0.0), format='%.4f')
                gj_duration = ui.number('Duration [s]',         value=gj.get('Duration [s]',          0.0), format='%.4f')

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

        with ui.card().classes('w-full'):
            ui.label('X-C.G. from Body Tail').classes('text-subtitle2')
            en_xcg, xcg_file, xcg_const = _file_or_const(
                data, 'Enable X-C.G. File',
                'X-C.G. File',     'X-C.G. File Path',
                'Constant X-C.G.', 'Constant X-C.G. from BodyTail [mm]',
                'X-C.G.', 'Constant [mm]', 1800.0, '%.2f',
            )
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_xcg, 'value', backward=lambda v: not v):
                cg_off_y = ui.number('y-C.G. Offset [mm]', value=cg_off.get('y-C.G. Offset [mm]', 0.0), format='%.4f')
                cg_off_z = ui.number('z-C.G. Offset [mm]', value=cg_off.get('z-C.G. Offset [mm]', 0.0), format='%.4f')

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

        with ui.card().classes('w-full'):
            ui.label('X-C.P. from Body Tail').classes('text-subtitle2')
            en_xcp, xcp_file, xcp_const = _file_or_const(
                data, 'Enable X-C.P. File',
                'X-C.P. File',     'X-C.P. File Path',
                'Constant X-C.P.', 'Constant X-C.P. from BodyTail [mm]',
                'X-C.P.', 'Constant [mm]', 1400.0, '%.2f',
            )

        with ui.card().classes('w-full'):
            ui.label('Thrust Loading Point').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                thr_pt   = ui.number('X from Body Tail [mm]',  value=data.get('X-ThrustLoadingPoint from BodyTail [mm]', 0.0), format='%.2f')
                thr_pt_y = ui.number('y-Offset [mm]',          value=data.get('y-ThrustLoadingPoint Offset [mm]', 0.0),        format='%.4f')
                thr_pt_z = ui.number('z-Offset [mm]',          value=data.get('z-ThrustLoadingPoint Offset [mm]', 0.0),        format='%.4f')

        ca_f = data.get('CA File', {})
        ca_c = data.get('Constant CA', {})
        with ui.card().classes('w-full'):
            ui.label('Axial Force Coefficient CA').classes('text-subtitle2')
            en_ca = ui.switch('Use File', value=data.get('Enable CA File', False))
            with ui.column().classes('w-full').bind_visibility_from(en_ca, 'value'):
                ca_path    = ui.input('CA File Path',         value=ca_f.get('CA File Path',        '')).classes('w-full')
                ca_bo_path = ui.input('BurnOut CA File Path', value=ca_f.get('BurnOut CA File Path', '')).classes('w-full')
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_ca, 'value', backward=lambda v: not v):
                ca_val    = ui.number('Constant CA [-]',         value=ca_c.get('Constant CA [-]',         0.5), format='%.4f')
                ca_bo_val = ui.number('Constant BurnOut CA [-]', value=ca_c.get('Constant BurnOut CA [-]', 0.5), format='%.4f')

        with ui.card().classes('w-full'):
            ui.label('Normal Force Coefficient CNα').classes('text-subtitle2')
            en_cna, cna_file, cna_const = _file_or_const(
                data, 'Enable CNa File',
                'CNa File',     'CNa File Path',
                'Constant CNa', 'Constant CNa [1/rad]',
                'CNα', 'Constant CNα [1/rad]', 5.0, '%.4f',
            )

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

        with ui.card().classes('w-full'):
            ui.label('Roll Damping Coefficient Clp').classes('text-subtitle2')
            en_clp, clp_file, clp_const = _file_or_const(
                data, 'Enable Clp File',
                'Clp File',     'Clp File Path',
                'Constant Clp', 'Constant Clp [-]',
                'Clp', 'Constant Clp [-]', -0.02, '%.4f',
            )

        with ui.card().classes('w-full'):
            ui.label('Pitch Damping Coefficient Cmq').classes('text-subtitle2')
            en_cmq, cmq_file, cmq_const = _file_or_const(
                data, 'Enable Cmq File',
                'Cmq File',     'Cmq File Path',
                'Constant Cmq', 'Constant Cmq [-]',
                'Cmq', 'Constant Cmq [-]', -2.0, '%.4f',
            )

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
                ct_thrust   = ui.number('Thrust at vacuum [N]',  value=ct.get('Thrust at vacuum [N]', 8000.0),              format='%.2f')
                ct_mdot     = ui.number('Mass Flow Rate [kg/s]', value=ct.get('Propellant Mass Flow Rate [kg/s]', 1.67),     format='%.4f')
                ct_duration = ui.number('Burn Duration [s]',     value=ct.get('Burn Duration [sec]', 15.0),                 format='%.3f')

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
        with ui.card().classes('w-full'):
            ui.label('Flight Timing').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                t_start  = ui.number('Flight Start Time [s]',    value=data.get('Flight Start Time [s]',    0.0),   format='%.3f')
                t_ignite = ui.number('Engine Ignition Time [s]', value=data.get('Engine Ignittion Time [s]', 0.0),  format='%.3f')
                t_end    = ui.number('Flight End Time [s]',      value=data.get('Flight End Time [s]',    500.0),   format='%.3f')
                dt       = ui.number('Time Step [s]',            value=data.get('Time Step [s]',            0.1),   format='%.4f')
                en_auto  = ui.switch('Auto Terminate SubOrbital', value=data.get('Enable Auto Terminate SubOrbital Flight', True))

        # Adaptive Solver Tolerance (v4.4.0+): 適応ステップ積分器の許容誤差。
        # Abs は姿勢(小振幅状態)精度、Rel は ECI 位置精度と計算速度を支配。
        # 既定 Abs=1e-8/Rel=1e-6 は高速化と姿勢ロバスト性のバランス点。
        with ui.card().classes('w-full'):
            ui.label('Adaptive Solver Tolerance').classes('text-subtitle2')
            with ui.grid(columns=2).classes('w-full'):
                tol_abs = ui.number('Solver Tolerance Abs', value=data.get('Solver Tolerance Abs', 1.0e-8), format='%.1e')
                tol_rel = ui.number('Solver Tolerance Rel', value=data.get('Solver Tolerance Rel', 1.0e-6), format='%.1e')

        with ui.card().classes('w-full'):
            ui.label('Rail Launcher').classes('text-subtitle2')
            en_rail  = ui.switch('Enable Rail-Launcher', value=data.get('Enable Rail-Launcher Launch', True))
            rail_len = (ui.number('Length [m]', value=rail.get('Length [m]', 5.0), format='%.3f')
                        .bind_visibility_from(en_rail, 'value'))

        with ui.card().classes('w-full'):
            ui.label('Engine Cutoff').classes('text-subtitle2')
            en_cut   = ui.switch('Enable Engine Cutoff', value=data.get('Enable Engine Cutoff', False))
            cutoff_t = (ui.number('Cutoff Time [s]', value=cutoff.get('Cutoff Time [s]', 0.0), format='%.3f')
                        .bind_visibility_from(en_cut, 'value'))

        with ui.card().classes('w-full'):
            ui.label('Stage Separation').classes('text-subtitle2')
            en_sep = ui.switch('Enable Stage Separation', value=data.get('Enable Stage Separation', False))
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_sep, 'value'):
                sep_t    = ui.number('Separation Time [s]',   value=sep.get('Stage Separation Time [s]', 0.0), format='%.3f')
                sep_mass = ui.number('Upper Stage Mass [kg]', value=sep.get('Upper Stage Mass [kg]', 0.0),     format='%.4f')

        with ui.card().classes('w-full'):
            ui.label('Despin Control').classes('text-subtitle2')
            en_despin = ui.switch('Enable Despin', value=data.get('Enable Despin Control', False))
            despin_t  = (ui.number('Despin Time [s]', value=despin.get('Time [s]', 0.0), format='%.3f')
                         .bind_visibility_from(en_despin, 'value'))

        with ui.card().classes('w-full'):
            ui.label('Fairing Jettison').classes('text-subtitle2')
            en_fair = ui.switch('Enable Fairing Jettison', value=data.get('Enable Fairing Jettson', False))
            with ui.grid(columns=2).classes('w-full').bind_visibility_from(en_fair, 'value'):
                fair_t    = ui.number('Jettison Time [s]', value=fair.get('Jettson Time [s]', 0.0), format='%.3f')
                fair_mass = ui.number('Mass [kg]',         value=fair.get('Mass [kg]', 0.0),        format='%.4f')

        with ui.card().classes('w-full'):
            ui.label('Parachute (Primary)').classes('text-subtitle2')
            en_para = ui.switch('Enable Parachute Open', value=data.get('Enable Parachute Open', True))
            with ui.column().classes('w-full').bind_visibility_from(en_para, 'value'):
                with ui.grid(columns=3).classes('w-full'):
                    para_t    = ui.number('Open Time [s]',       value=para.get('Open Time [s]', 0.0),         format='%.3f')
                    para_cds  = ui.number('Cd·S [m²]',           value=para.get('Drag Factor Cd*S [m2]', 3.0), format='%.4f')
                    en_forced = ui.switch('Force Open at Apogee', value=para.get('Enable Forced Apogee Open', True))

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
        r['Upper Stage'] = {'Stage Separation Time [s]': sep_t.value, 'Upper Stage Mass [kg]': sep_mass.value}
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


_MC_ERROR_PARAMS_DEF = [
    # (key, default_unit, is_wind_special)
    ('Wind',                          None,  True),
    ('Launcher Azimuth',              'deg', False),
    ('Launcher Elevation',            'deg', False),
    ('CA',                            '%',   False),
    ('Propellant Mass',               '%',   False),
    ('Thrust',                        '%',   False),
    ('XCG',                           'm',   False),
    ('MOI',                           '%',   False),
    ('Primary Parachute Drag',        '%',   False),
    ('Primary Parachute Open Time',   's',   False),
    ('Secondary Parachute Drag',      '%',   False),
    ('Secondary Parachute Open Time', 's',   False),
    ('Mass Inert',                    '%',   False),
    ('CNa',                           '%',   False),
    ('XCP',                           '%',   False),
    ('Clp',                           '%',   False),
    ('Cmq',                           '%',   False),
    ('Cnr',                           '%',   False),
    ('Cld',                           '%',   False),
    ('Fin Cant Angle',                'deg', False),
    ('Gas Jet Moment',                '%',   False),
    ('Gas Jet Duration',              '%',   False),
    ('Engine Miss-Alignment Y',       'deg', False),
    ('Engine Miss-Alignment Z',       'deg', False),
    ('CG Offset Y',                   'mm',  False),
    ('CG Offset Z',                   'mm',  False),
    ('Thrust Point Offset Y',         'mm',  False),
    ('Thrust Point Offset Z',         'mm',  False),
    ('POI Ixy',                       '%',   False),
    ('POI Ixz',                       '%',   False),
    ('POI Iyz',                       '%',   False),
]

# (parameter name, default Variation Unit). Mirrors the runner's supported
# scalar sensitivity parameters (runner_montecarlo._SCALAR_PARAM_REGISTRY) plus
# Thrust / CA. Keep in sync with runner_tool/runner_sensitivity.py.
_SENS_PARAM_DEFS = [
    ('Thrust',                        '%'),
    ('CA',                            '%'),
    ('Launcher Azimuth',              'deg'),
    ('Launcher Elevation',            'deg'),
    ('Propellant Mass',               '%'),
    ('Mass Inert',                    '%'),
    ('CNa',                           '%'),
    ('XCP',                           '%'),
    ('Cld',                           '%'),
    ('Clp',                           '%'),
    ('Cmq',                           '%'),
    ('Cnr',                           '%'),
    ('Fin Cant Angle',                'deg'),
    ('Engine Miss-Alignment Y',       'deg'),
    ('Engine Miss-Alignment Z',       'deg'),
    ('Gas Jet Moment',                '%'),
    ('Gas Jet Duration',              '%'),
    ('CG Offset Y',                   'mm'),
    ('CG Offset Z',                   'mm'),
    ('Thrust Point Offset Y',         'mm'),
    ('Thrust Point Offset Z',         'mm'),
    ('POI Ixy',                       '%'),
    ('POI Ixz',                       '%'),
    ('POI Iyz',                       '%'),
    ('Primary Parachute Drag',        '%'),
    ('Primary Parachute Open Time',   's'),
    ('Secondary Parachute Drag',      '%'),
    ('Secondary Parachute Open Time', 's'),
]
_SENS_PARAM_NAMES = [n for n, _ in _SENS_PARAM_DEFS]
_SENS_PARAM_UNIT  = dict(_SENS_PARAM_DEFS)
_SENS_UNITS = ['%', 'deg', 's', 'm', 'kg', 'N', 'mm', '-']
_SENS_METHODS = {'two_point': 'Two Point', 'linear_fit': 'Linear Fit (all points)'}
# POI components are %-only when the rocket runs in Product-of-Inertia file mode.
_SENS_POI_PARAMS = {'POI Ixy', 'POI Ixz', 'POI Iyz'}


def _parse_num_list(text: str) -> list:
    parts = [p.strip() for p in text.replace(';', ',').split(',') if p.strip()]
    result = []
    for p in parts:
        try:
            result.append(float(p) if '.' in p else int(p))
        except ValueError:
            pass
    return result


def _opts_with(value, base: list) -> list:
    """Return base options with `value` prepended if it isn't already present.

    ui.select raises ValueError when its initial value is outside `options`, so
    any custom/composite value loaded from a config must be merged in first.
    """
    opts = list(base)
    if value and value not in opts:
        opts = [value] + opts
    return opts


def _build_area_form(data: dict, container):
    lw = data.get('Law Wind', {})
    with container:
        with ui.card().classes('w-full'):
            ui.label('Law Wind (Power Law Model)').classes('text-subtitle2')
            with ui.grid(columns=2).classes('w-full'):
                wind_coeff = ui.number('Wind Characteristic Coefficient',
                                       value=lw.get('Wind Characteristic Coefficient', 0.143), format='%.4f')
                ref_height = ui.number('Reference Height [m]',
                                       value=lw.get('Reference Height [m]', 10.0), format='%.2f')
        with ui.card().classes('w-full'):
            ui.label('Wind Speed Range').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                spd_lo   = ui.number('Lower Limit [m/s]', value=lw.get('Reference Wind Speed Lower Limit [m/s]', 2.0),  format='%.2f')
                spd_hi   = ui.number('Upper Limit [m/s]', value=lw.get('Reference Wind Speed Upper Limit [m/s]', 10.0), format='%.2f')
                spd_step = ui.number('Step [m/s]',        value=lw.get('Reference Wind Speed Step [m/s]', 2.0),          format='%.2f')
        with ui.card().classes('w-full'):
            ui.label('Wind Direction Range').classes('text-subtitle2')
            with ui.grid(columns=3).classes('w-full'):
                dir_lo   = ui.number('Lower Limit [deg]', value=lw.get('Wind Direction Lower Limit [deg]', 0.0),   format='%.1f')
                dir_hi   = ui.number('Upper Limit [deg]', value=lw.get('Wind Direction Upper Limit [deg]', 350.0), format='%.1f')
                dir_step = ui.number('Step [deg]',        value=lw.get('Wind Direction Step [deg]', 10.0),          format='%.1f')
        case_lbl = ui.label('').classes('text-caption text-grey q-mt-xs')

        def _upd_cases():
            try:
                ns = max(1, round((spd_hi.value - spd_lo.value) / spd_step.value) + 1)
                nd = max(1, round((dir_hi.value - dir_lo.value) / dir_step.value) + 1)
                case_lbl.set_text(f'Estimated cases: {ns} speeds × {nd} directions = {ns * nd}')
            except Exception:
                pass

        for el in [spd_lo, spd_hi, spd_step, dir_lo, dir_hi, dir_step]:
            el.on('update:modelValue', lambda _: _upd_cases())
        _upd_cases()

    def collect() -> dict:
        return {'Law Wind': {
            'Wind Characteristic Coefficient':        wind_coeff.value,
            'Reference Height [m]':                   ref_height.value,
            'Reference Wind Speed Lower Limit [m/s]': spd_lo.value,
            'Reference Wind Speed Upper Limit [m/s]': spd_hi.value,
            'Reference Wind Speed Step [m/s]':        spd_step.value,
            'Wind Direction Lower Limit [deg]':       dir_lo.value,
            'Wind Direction Upper Limit [deg]':       dir_hi.value,
            'Wind Direction Step [deg]':              dir_step.value,
        }}

    return collect


def _build_montecarlo_form(data: dict, container):
    ep = data.get('Error Parameters', {})
    row_els: dict[str, dict] = {}

    with container:
        with ui.card().classes('w-full'):
            ui.label('Monte Carlo Settings').classes('text-subtitle2')
            case_count = ui.number('Case Count', value=data.get('MonteCarlo Case Count', 300),
                                   min=1, step=100, format='%.0f')
            output_all_logs = ui.switch('Output all case logs',
                                        value=data.get('Output All Case Logs', True))
            ui.label('Off = statistics only (per-case flight logs are discarded to save time/disk)') \
                .classes('text-caption text-grey')

        with ui.card().classes('w-full'):
            ui.label('Error Parameters').classes('text-subtitle2')
            with ui.row().classes('items-center text-caption text-grey q-mb-xs no-wrap').style('gap:8px'):
                ui.label('En.').style('min-width:40px')
                ui.label('Parameter').style('min-width:210px')
                ui.label('Unit').style('min-width:52px')
                ui.label('3σ Low').style('min-width:90px')
                ui.label('3σ High').style('min-width:90px')

            for key, default_unit, is_wind in _MC_ERROR_PARAMS_DEF:
                p   = ep.get(key, {})
                els = {}
                with ui.row().classes('items-center no-wrap').style('gap:8px'):
                    els['enable'] = ui.switch(value=p.get('Enable', False)).props('dense').style('min-width:40px')
                    ui.label(key).style('min-width:210px').classes('text-caption')
                    if is_wind:
                        els['zip_path'] = (
                            ui.input('winds.zip path', value=p.get('Wind Files Zip Path', ''))
                            .style('min-width:240px').props('dense outlined')
                            .bind_visibility_from(els['enable'], 'value')
                        )
                    else:
                        els['unit'] = (ui.input(value=p.get('Error Unit', default_unit or '%'))
                                       .style('width:52px').props('dense outlined'))
                        els['lo']   = (ui.number(value=p.get('Error 3sigma Low', 5.0),  format='%.2f', step=1, min=0)
                                       .style('width:90px').props('dense outlined'))
                        els['hi']   = (ui.number(value=p.get('Error 3sigma High', 5.0), format='%.2f', step=1, min=0)
                                       .style('width:90px').props('dense outlined'))
                row_els[key] = els

    def collect() -> dict:
        ep_out = {}
        for key, _, is_wind in _MC_ERROR_PARAMS_DEF:
            els = row_els.get(key, {})
            if is_wind:
                ep_out[key] = {
                    'Enable':             els['enable'].value if 'enable' in els else False,
                    'Wind Files Zip Path': els['zip_path'].value if 'zip_path' in els else '',
                }
            else:
                ep_out[key] = {
                    'Enable':          els['enable'].value if 'enable' in els else False,
                    'Error Unit':      els['unit'].value   if 'unit'   in els else '%',
                    'Error 3sigma Low':  els['lo'].value   if 'lo'     in els else 0.0,
                    'Error 3sigma High': els['hi'].value   if 'hi'     in els else 0.0,
                }
        return {
            'MonteCarlo Case Count': int(case_count.value or 300),
            'Output All Case Logs': bool(output_all_logs.value),
            'Error Parameters': ep_out,
        }

    return collect


def _build_sensitivity_form(data: dict, container, proj=None):
    sc = data.get('Sensitivity Calculation', {})

    def _copy_param(p):
        q = dict(p)
        if 'Effects' in q:
            q['Effects'] = [dict(e) for e in (q.get('Effects') or [])]
        return q

    # Working copy — edits are buffered here and only written to disk on Save.
    params_data = [_copy_param(p) for p in data.get('Sensitivity Parameters', [])]

    # File-mode flags: Thrust/CA/POI accept only "%" when their file mode is on
    # (runner_sensitivity._get_nominal raises otherwise). Read the sibling configs
    # directly — these are plain JSON keys, no heavy import needed.
    rocket = (load_json(proj, 'param_rocket.json') or {}) if proj else {}
    engine = (load_json(proj, 'param_engine.json') or {}) if proj else {}
    thrust_fm = bool(engine.get('Enable Thrust File'))
    ca_fm     = bool(rocket.get('Enable CA File'))
    poi_fm    = bool(rocket.get('Enable Product of Inertia File'))

    param_rows = []
    param_list_area = None
    method_sel = total_lbl = warn_lbl = None
    state = {'building': False}

    def _to_float(v, default=1.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def _filemode_bad(pname_set, unit):
        if unit == '%':
            return []
        bad = []
        for pn in pname_set:
            if (pn == 'Thrust' and thrust_fm) or (pn == 'CA' and ca_fm) \
                    or (pn in _SENS_POI_PARAMS and poi_fm):
                bad.append(pn)
        return bad

    # ── widgets → working copy ──────────────────────────────────────────────
    def _sync():
        for row, p in zip(param_rows, params_data):
            p['Name'] = row['name'].value
            p['Variation Unit'] = row['unit'].value
            p['Variations'] = _parse_num_list(row['variations'].value)
            ref = [v for v in (row['ref_lo'].value, row['ref_hi'].value) if v is not None]
            if len(ref) >= 2:
                p['Reference Variations'] = ref
            if row['mode'] == 'coupled':
                p['Effects'] = [
                    {'Parameter': er['param'].value, 'Scale': _to_float(er['scale'].value)}
                    for er in row['effects']
                ]
            else:
                p.pop('Effects', None)

    def _update_total():
        n = sum(len(p.get('Variations') or []) for p in params_data)
        total_lbl.set_text(f'Estimated cases: 1 (nominal) + {n} = {n + 1}')

    def _validate():
        msgs = []
        names = [p.get('Name') or '(unnamed)' for p in params_data]
        for p in params_data:
            nm = p.get('Name') or '(unnamed)'
            unit = p.get('Variation Unit', '%')
            vars_ = p.get('Variations') or []
            if 'Effects' in p:
                effs = p.get('Effects') or []
                if not effs:
                    msgs.append(f'"{nm}": coupled parameter has no Effects')
                pset = {e.get('Parameter') for e in effs if e.get('Parameter')}
            else:
                pset = {nm}
                if nm and nm not in _SENS_PARAM_NAMES:
                    msgs.append(f'"{nm}": unknown parameter (runner may reject)')
            if len(vars_) < 2:
                msgs.append(f'"{nm}": needs at least 2 Variations')
            for b in _filemode_bad(pset, unit):
                msgs.append(f'"{nm}": {b} is in file mode → Unit must be "%" (got "{unit}")')
        for d in sorted({n for n in names if names.count(n) > 1}):
            msgs.append(f'duplicate name "{d}"')
        if msgs:
            warn_lbl.set_text('⚠ ' + '   •   '.join(msgs))
            warn_lbl.set_visibility(True)
        else:
            warn_lbl.set_visibility(False)

    def _refresh():
        if state['building']:
            return
        _sync()
        _update_total()
        _validate()

    def _init_row_ui(row):
        """Refresh chips, case count and Reference dropdown options from Variations."""
        vals = _parse_num_list(row['variations'].value)
        row['chips_area'].clear()
        with row['chips_area']:
            if vals:
                for v in vals:
                    ui.chip(str(v)).props('dense outline square color=primary')
            else:
                ui.label('(no values)').classes('text-caption text-grey')
        row['count_lbl'].set_text(f'{len(vals)} case(s)')
        # Reference options = the variation values plus a nominal (0) point, so a one-sided
        # reference like nominal→+10% can be built. nominal is always run as case 0.
        ref_vals = sorted(set(vals) | {0.0})
        ref_opts = {v: ('nominal (0)' if v == 0 else str(v)) for v in ref_vals}
        for key, default in (('ref_lo', ref_vals[0]),
                             ('ref_hi', ref_vals[-1])):
            sel = row[key]
            sel.options = ref_opts
            if sel.value not in ref_opts:
                sel.value = default
            sel.update()

    # ── event handlers ──────────────────────────────────────────────────────
    def _on_vars(row):
        if state['building']:
            return
        state['building'] = True
        _init_row_ui(row)
        state['building'] = False
        _refresh()

    def _on_name(row):
        if state['building']:
            return
        nm = row['name'].value
        if nm in _SENS_PARAM_UNIT:
            row['unit'].value = _SENS_PARAM_UNIT[nm]
        _refresh()

    def _add_param(coupled):
        _sync()
        if coupled:
            params_data.append({
                'Name': 'New Coupled Parameter', 'Variation Unit': '%',
                'Variations': [-10, -5, 5, 10], 'Reference Variations': [-10, 10],
                'Effects': [{'Parameter': _SENS_PARAM_NAMES[0], 'Scale': 1.0}],
            })
        else:
            first = _SENS_PARAM_NAMES[0]
            params_data.append({
                'Name': first, 'Variation Unit': _SENS_PARAM_UNIT[first],
                'Variations': [-10, -5, 5, 10], 'Reference Variations': [-10, 10],
            })
        _rebuild()

    def _remove_param(idx):
        _sync()
        params_data.pop(idx)
        _rebuild()

    def _toggle_mode(idx, mode):
        _sync()
        p = params_data[idx]
        if mode == 'coupled':
            p.setdefault('Effects', [{'Parameter': _SENS_PARAM_NAMES[0], 'Scale': 1.0}])
        else:
            p.pop('Effects', None)
        _rebuild()

    def _add_effect(idx):
        _sync()
        params_data[idx].setdefault('Effects', []).append(
            {'Parameter': _SENS_PARAM_NAMES[0], 'Scale': 1.0})
        _rebuild()

    def _remove_effect(idx, eidx):
        _sync()
        (params_data[idx].get('Effects') or []).pop(eidx)
        _rebuild()

    # ── (re)build the parameter cards ─────────────────────────────────────────
    def _rebuild():
        state['building'] = True
        param_list_area.clear()
        param_rows.clear()
        with param_list_area:
            for i, p in enumerate(params_data):
                coupled = 'Effects' in p
                row = {'mode': 'coupled' if coupled else 'single'}
                with ui.card().classes('w-full q-pa-sm'):
                    with ui.row().classes('items-center no-wrap w-full q-gutter-sm'):
                        ui.label(f'#{i + 1}').classes('text-caption text-grey')
                        ui.toggle({'single': 'Single', 'coupled': 'Coupled'}, value=row['mode'],
                                  on_change=lambda e, idx=i: _toggle_mode(idx, e.value)) \
                            .props('dense no-caps')
                        ui.space()
                        ui.button(icon='delete', on_click=lambda idx=i: _remove_param(idx)) \
                            .props('flat round dense color=negative')

                    with ui.row().classes('items-center no-wrap w-full q-gutter-sm'):
                        if coupled:
                            row['name'] = ui.input('Label', value=p.get('Name', '')) \
                                .style('min-width:240px').props('dense')
                            row['name'].on_value_change(lambda: _refresh())
                        else:
                            cur = p.get('Name', _SENS_PARAM_NAMES[0])
                            row['name'] = ui.select(
                                options=_opts_with(cur, _SENS_PARAM_NAMES), value=cur,
                                label='Parameter', with_input=True, new_value_mode='add-unique',
                            ).style('min-width:240px')
                            row['name'].on_value_change(lambda r=row: _on_name(r))
                        cu = p.get('Variation Unit', '%')
                        row['unit'] = ui.select(options=_opts_with(cu, _SENS_UNITS), value=cu,
                                                label='Unit').style('width:90px')
                        row['unit'].on_value_change(lambda: _refresh())

                    row['effects'] = []
                    if coupled:
                        with ui.card().classes('w-full q-pa-xs bg-grey-1'):
                            ui.label('Effects — these parameters move together each variation '
                                     '(new = base ± variation × Scale)').classes('text-caption text-grey')
                            for j, eff in enumerate(p.get('Effects') or []):
                                with ui.row().classes('items-center no-wrap q-gutter-sm'):
                                    ecur = eff.get('Parameter', _SENS_PARAM_NAMES[0])
                                    esel = ui.select(options=_opts_with(ecur, _SENS_PARAM_NAMES),
                                                     value=ecur, label='Parameter',
                                                     with_input=True).style('min-width:220px')
                                    escale = ui.number('Scale', value=_to_float(eff.get('Scale', 1.0))) \
                                        .style('width:110px').props('dense')
                                    esel.on_value_change(lambda: _refresh())
                                    escale.on_value_change(lambda: _refresh())
                                    ui.button(icon='delete',
                                              on_click=lambda idx=i, ej=j: _remove_effect(idx, ej)) \
                                        .props('flat round dense color=negative')
                                    row['effects'].append({'param': esel, 'scale': escale})
                            ui.button('+ add effect', on_click=lambda idx=i: _add_effect(idx)) \
                                .props('flat dense color=primary icon=add')

                    row['variations'] = ui.input('Variations (comma-separated)',
                                                 value=', '.join(str(v) for v in p.get('Variations', []))) \
                        .classes('w-full').props('dense')
                    row['variations'].tooltip('e.g. -10, -5, 5, 10 — every value becomes one case')
                    row['variations'].on_value_change(lambda r=row: _on_vars(r))
                    with ui.row().classes('items-center no-wrap w-full q-gutter-xs'):
                        row['chips_area'] = ui.row().classes('items-center q-gutter-xs')
                        ui.space()
                        row['count_lbl'] = ui.label('').classes('text-caption text-grey')

                    with ui.row().classes('items-center no-wrap q-gutter-sm') as ref_row:
                        ui.label('Reference (two-point):').classes('text-caption')
                        row['ref_lo'] = ui.select(options=[], label='Low').style('width:110px')
                        row['ref_hi'] = ui.select(options=[], label='High').style('width:110px')
                    ref_row.bind_visibility_from(method_sel, 'value',
                                                 backward=lambda v: v == 'two_point')
                    row['ref_lo'].on_value_change(lambda: _refresh())
                    row['ref_hi'].on_value_change(lambda: _refresh())

                param_rows.append(row)
                _init_row_ui(row)
                rv = p.get('Reference Variations') or []
                if len(rv) >= 2:
                    if rv[0] in (row['ref_lo'].options or []):
                        row['ref_lo'].value = rv[0]
                    if rv[1] in (row['ref_hi'].options or []):
                        row['ref_hi'].value = rv[1]
                    row['ref_lo'].update()
                    row['ref_hi'].update()
        state['building'] = False
        _update_total()
        _validate()

    with container:
        with ui.card().classes('w-full'):
            ui.label('Sensitivity Calculation Settings').classes('text-subtitle2')
            method_val = sc.get('Method', 'two_point')
            if method_val not in _SENS_METHODS:
                method_val = 'two_point'
            method_sel = ui.select(options=_SENS_METHODS, value=method_val, label='Method') \
                .style('min-width:240px')
            ui.label('two_point: ΔApogee / ΔParam between the chosen Low/High reference pair') \
                .classes('text-caption text-grey')
            ui.label('linear_fit: least-squares slope through all variation points') \
                .classes('text-caption text-grey')
            total_lbl = ui.label('').classes('text-caption text-grey q-mt-xs')

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center w-full q-gutter-sm'):
                ui.label('Sensitivity Parameters').classes('text-subtitle2')
                ui.space()
                ui.button('+ Single', on_click=lambda: _add_param(False)) \
                    .props('flat dense color=primary icon=add') \
                    .tooltip('One-at-a-time: vary a single parameter')
                ui.button('+ Coupled', on_click=lambda: _add_param(True)) \
                    .props('flat dense color=secondary icon=add') \
                    .tooltip('Vary several parameters together (Effects)')
            param_list_area = ui.column().classes('w-full q-gutter-sm')
            warn_lbl = ui.label('').classes('text-caption text-orange q-mt-xs')
            _rebuild()

    def collect() -> dict:
        _sync()
        result = []
        for p in params_data:
            name = p.get('Name')
            variations = p.get('Variations') or []
            if not (name and variations):
                continue
            entry = _copy_param(p)
            if len(entry.get('Reference Variations') or []) < 2:
                entry['Reference Variations'] = variations[:2]
            result.append(entry)
        return {
            'Sensitivity Calculation': {'Method': method_sel.value},
            'Sensitivity Parameters':  result,
        }

    return collect


def _build_json_editor(proj, fname, data):
    json_text = json.dumps(data, indent=4, ensure_ascii=False) if data is not None else '{}'
    json_area = ui.textarea(value=json_text).classes('w-full').style(
        'font-family:monospace; min-height:400px;'
    )
    with ui.row().classes('q-mt-sm q-gutter-sm'):
        def _save_json_text():
            try:
                parsed = json.loads(json_area.value)
                save_json(proj, fname, parsed)
                ui.notify('Saved.', type='positive')
            except json.JSONDecodeError as e:
                ui.notify(f'JSON parse error: {e}', type='negative')
        ui.button('Save', on_click=_save_json_text).props('color=primary icon=save')
        ui.button('Reformat', on_click=lambda: (
            json_area.set_value(
                json.dumps(json.loads(json_area.value), indent=4, ensure_ascii=False)
            )
        )).props('flat icon=format_align_left')


_FORM_BUILDERS = {
    'config_solver.json':      _build_solver_form,
    'param_list_stage1.json':  _build_stage_form,
    'param_rocket.json':       _build_rocket_form,
    'param_engine.json':       _build_engine_form,
    'sequence_of_event.json':  _build_soe_form,
    'config_area.json':        _build_area_form,
    'config_montecarlo.json':  _build_montecarlo_form,
    'config_sensitivity.json': _build_sensitivity_form,
}


# ── Page ───────────────────────────────────────────────────────────────────────

@ui.page('/calculate')
def calculate_page(request: Request):
    build_header('Calculate')

    project_names   = scan_projects()
    project_from_url = request.query_params.get('project', '')
    open_new        = request.query_params.get('new', '') == '1'
    initial_proj    = (project_from_url if project_from_url in project_names
                       else (project_names[0] if project_names else ''))

    # ── New project dialog ────────────────────────────────────────────────────
    with ui.dialog() as new_project_dialog, ui.card():
        ui.label('Create New Project').classes('text-h6')
        new_name_input = ui.input('Project Name').classes('w-full')
        with ui.row().classes('q-mt-sm'):
            ui.button('Create', on_click=lambda: _do_create()).props('color=primary')
            ui.button('Cancel', on_click=new_project_dialog.close).props('flat')

    def _do_create():
        name = new_name_input.value.strip()
        if not name:
            ui.notify('Name cannot be empty.', type='warning')
            return
        ok, err = create_project(name)
        if ok:
            ui.notify(f'Project "{name}" created.', type='positive')
            new_project_dialog.close()
            ui.navigate.reload()
        else:
            ui.notify(err, type='negative')

    # ── Top bar: shared project selector ─────────────────────────────────────
    with ui.row().classes('items-center q-px-md q-pt-sm q-pb-xs q-gutter-sm'):
        project_select = ui.select(
            options=project_names, value=initial_proj, label='Project',
        ).style('min-width:200px')
        ui.space()
        ui.button('+ New Project', on_click=lambda: new_project_dialog.open()).props('flat icon=add')

    # ── Main two-column layout ────────────────────────────────────────────────
    with ui.row().classes('w-full no-wrap q-px-md q-pb-md').style('gap:16px; align-items:flex-start'):

        # ── Left: Config Editor ───────────────────────────────────────────────
        with ui.column().classes('flex-grow').style('min-width:0'):
            with ui.row().classes('items-center q-gutter-sm q-mb-xs'):
                ui.label('Config Editor').classes('text-subtitle1')
                file_options = {f: _FILE_LABELS.get(f, f) for f in _EDITABLE_FILES}
                file_select  = ui.select(
                    options=file_options, value=_EDITABLE_FILES[0], label='File',
                ).style('min-width:220px')

            editor_area = ui.column().classes('w-full')

            def render_editor():
                editor_area.clear()
                proj  = project_select.value
                fname = file_select.value
                if not proj or not fname:
                    return
                data    = load_json(proj, fname)
                builder = _FORM_BUILDERS.get(fname)
                with editor_area:
                    if builder and data is not None:
                        with ui.tabs() as tabs:
                            form_tab = ui.tab('Form')
                            json_tab = ui.tab('JSON')
                        with ui.tab_panels(tabs, value=form_tab).classes('w-full'):
                            with ui.tab_panel(form_tab):
                                form_con   = ui.column().classes('w-full q-gutter-sm')
                                if builder is _build_sensitivity_form:
                                    # needs the project to read sibling configs (file-mode checks)
                                    collect_fn = builder(data or {}, form_con, proj)
                                else:
                                    collect_fn = builder(data or {}, form_con)
                                _save_btn(proj, fname, collect_fn)
                            with ui.tab_panel(json_tab):
                                _build_json_editor(proj, fname, data)
                    else:
                        _build_json_editor(proj, fname, data)

            project_select.on('update:modelValue', lambda _: render_editor())
            file_select.on('update:modelValue',    lambda _: render_editor())
            render_editor()

        # ── Right: Run Controls (sticky) ─────────────────────────────────────
        with ui.card().style(
            'width:300px; min-width:300px; flex-shrink:0; '
            'position:sticky; top:64px; overflow-y:auto; max-height:calc(100vh - 72px)'
        ):
            ui.label('Run Calculation').classes('text-subtitle2 q-mb-xs')

            ui.label('Mode').classes('text-caption text-grey q-mb-xs')
            mode_radio = ui.radio(
                options={k: v for k, v in _MODE_LABELS.items()},
                value='trajectory',
            ).props('dense')

            max_thread_check = ui.checkbox(
                'Max CPU threads  (Area / MC / Sensitivity)'
            ).classes('q-mt-xs')

            ui.separator().classes('q-my-sm')
            ui.label('Project Files').classes('text-caption text-grey')
            file_container = ui.column().classes('q-gutter-xs')

            def refresh_files():
                proj = project_select.value or ''
                mode = mode_radio.value or 'trajectory'
                file_container.clear()
                if not proj:
                    return
                files    = get_project_files(proj)
                required = set(_REQUIRED_FILES.get(mode, []))
                with file_container:
                    for fn, exists in files.items():
                        is_req = fn in required
                        if not is_req and not exists:
                            continue
                        color  = 'positive' if exists else ('negative' if is_req else 'grey')
                        icon   = '✓' if exists else ('✗' if is_req else '–')
                        suffix = '' if is_req else ' (opt.)'
                        ui.label(f'{icon} {fn}{suffix}').classes(f'text-{color} text-caption')

            project_select.on('update:modelValue', lambda _: refresh_files())
            mode_radio.on('update:modelValue',     lambda _: refresh_files())
            refresh_files()

            ui.separator().classes('q-my-sm')

            with ui.row().classes('q-gutter-sm items-center'):
                run_btn    = ui.button('Run', icon='play_arrow', on_click=lambda: _on_run()).props('color=primary')
                cancel_btn = ui.button('Cancel', on_click=cancel_calculation).props('color=negative flat dense')
                cancel_btn.set_visibility(False)

            progress_area = ui.column().classes('q-mt-sm')
            progress_area.set_visibility(False)
            with progress_area:
                progress_label = ui.label('').classes('text-caption text-grey')
                progress_bar   = ui.linear_progress(value=0).props('instant-feedback color=primary')

            result_area = ui.column().classes('q-mt-sm')

            def _on_run():
                proj = project_select.value
                mode = mode_radio.value
                if not proj:
                    ui.notify('Please select a project.', type='warning')
                    return
                if current_job().status == 'running':
                    ui.notify('A calculation is already running.', type='warning')
                    return
                run_btn.set_visibility(False)
                cancel_btn.set_visibility(True)
                progress_area.set_visibility(True)
                result_area.clear()
                start_calculation(proj, mode, max_thread_check.value)

            _st = {'status': current_job().status}

            def _refresh_progress():
                job    = current_job()
                status = job.status
                if status in ('running', 'cancelling'):
                    progress_label.set_text(
                        f'Step {job.step}/4: {job.step_label}'
                        + (' (cancelling…)' if status == 'cancelling' else '')
                    )
                    progress_bar.set_value(job.progress)
                elif status != _st['status']:
                    _st['status'] = status
                    if status == 'completed':
                        run_btn.set_visibility(True)
                        cancel_btn.set_visibility(False)
                        progress_label.set_text('Completed.')
                        progress_bar.set_value(1.0)
                        result_area.clear()
                        _cid = job.calc_id
                        with result_area:
                            ui.notify('Calculation completed!', type='positive')
                            ui.button(
                                'View Results',
                                on_click=lambda cid=_cid: ui.navigate.to(f'/result/{cid}'),
                            ).props('color=positive icon=open_in_new').classes('w-full q-mb-xs')

                    elif status == 'failed':
                        run_btn.set_visibility(True)
                        cancel_btn.set_visibility(False)
                        progress_label.set_text(f'Failed: {job.error}')
                        ui.notify(f'Calculation failed: {job.error}', type='negative')
                    elif status == 'cancelled':
                        run_btn.set_visibility(True)
                        cancel_btn.set_visibility(False)
                        progress_label.set_text('Cancelled.')

            ui.timer(0.5, _refresh_progress)

    if open_new:
        ui.timer(0.3, lambda: new_project_dialog.open(), once=True)
