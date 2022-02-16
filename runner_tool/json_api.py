import json
import os
import shutil

def get_file_name_from_path(file_path):
    return os.path.basename(file_path)

## Solver Config ####################################
def get_azimuth(solver_config):
    return solver_config.get('Launch Condition').get('Azimuth [deg]')
def set_azimuth(solver_config, azimuth):
    solver_config['Launch Condition']['Azimuth [deg]'] = azimuth
    return solver_config

def get_elevation(solver_config):
    return solver_config.get('Launch Condition').get('Elevation [deg]')
def set_elevation(solver_config, elv):
    solver_config['Launch Condition']['Elevation [deg]'] = elv
    return solver_config


## Stage Config ####################################
def get_stage_count(solver_config):
    count_stage = solver_config.get('Number of Stage')
    return count_stage


def get_stage_config_file_path(solver_config, stage_number):
    if stage_number > get_stage_count(solver_config):
        return
    stage_config_file_item = 'Stage'+str(stage_number)+' Config File List'
    stage_config_file_path = solver_config.get(stage_config_file_item)
    return stage_config_file_path

def get_stage_config_file_name(solver_config, stage_number):
    file_path = get_stage_config_file_path(solver_config, stage_number)
    return get_file_name_from_path(file_path)

def get_stage_config(solver_config, stage_number):
    stage_config_file_path = get_stage_config_file_path(solver_config, stage_number)
    stage_config = json.load(open(stage_config_file_path))
    return stage_config


## Rocket Parameter ####################################
def get_rocket_param_file_path(stage_config):
    return stage_config.get('Rocket Configuration File Path')

def get_rocket_param_file_name(stage_config):
    file_path = get_rocket_param_file_path(stage_config)
    return get_file_name_from_path(file_path)

def get_rocket_param(stage_config):
    rocket_param_file_path = get_rocket_param_file_path(stage_config)
    rocket_param = json.load(open(rocket_param_file_path))
    return rocket_param

def get_mass_inert(rocket_param):
    return rocket_param.get('Mass').get('Inert [kg]')
def set_mass_inert(rocket_param, mass):
    rocket_param['Mass']['Inert [kg]'] = mass
    return rocket_param
def get_mass_prop(rocket_param):
    return rocket_param.get('Mass').get('Propellant [kg]')
def set_mass_prop(rocket_param, mass):
    rocket_param['Mass']['Propellant [kg]'] = mass
    return rocket_param

def xcg_file_is_enable(rocket_param):
    return rocket_param.get('Enable X-C.G. File')
def get_xcg_file_name(rocket_param):
    return rocket_param.get('X-C.G. File').get('X-C.G. File Path')
def set_xcg_file_name(rocket_param, file_name):
    rocket_param['X-C.G. File']['X-C.G. File Path'] = file_name
    return rocket_param
def get_constant_xcg(rocket_param):
    return rocket_param.get('Constant X-C.G.').get('Constant X-C.G. from BodyTail [mm]')
def set_constant_xcg(rocket_param, xcg):
    rocket_param['Constant X-C.G.']['Constant X-C.G. from BodyTail [mm]'] = xcg
    return rocket_param

def moi_file_is_enable(rocket_param):
    return rocket_param.get('Enable M.I. File')
def get_moi_file_name(rocket_param):
    return rocket_param.get('M.I. File').get('M.I. File Path')
def set_moi_file_name(rocket_param, file_name):
    rocket_param['M.I. File']['M.I. File Path'] = file_name
    return rocket_param
def get_constant_moi_yaw(rocket_param):
    return rocket_param.get('Constant M.I.').get('Yaw Axis [kg-m2]')
def set_constant_moi_yaw(rocket_param, moi):
    rocket_param['Constant M.I.']['Yaw Axis [kg-m2]'] = moi
    return rocket_param
def get_constant_moi_pitch(rocket_param):
    return rocket_param.get('Constant M.I.').get('Pitch Axis [kg-m2]')
def set_constant_moi_pitch(rocket_param, moi):
    rocket_param['Constant M.I.']['Pitch Axis [kg-m2]'] = moi
    return rocket_param
def get_constant_moi_roll(rocket_param):
    return rocket_param.get('Constant M.I.').get('Roll Axis [kg-m2]')
def set_constant_moi_roll(rocket_param, moi):
    rocket_param['Constant M.I.']['Roll Axis [kg-m2]'] = moi
    return rocket_param

def xcp_file_is_enable(rocket_param):
    return rocket_param.get('Enable X-C.P. File')
def get_xcp_file_name(rocket_param):
    return rocket_param.get('X-C.P. File').get('X-C.P. File Path')
def set_xcp_file_name(rocket_param, file_name):
    rocket_param['X-C.P. File']['X-C.P. File Path'] = file_name
    return rocket_param
def get_constant_xcp(rocket_param):
    return rocket_param.get('Constant X-C.P.').get('Constant X-C.P. from BodyTail [mm]')
def set_constant_xcp(rocket_param, xcp):
    rocket_param['Constant X-C.P.']['Constant X-C.P. from BodyTail [mm]'] = xcp
    return rocket_param

def CA_file_is_enable(rocket_param):
    return rocket_param.get('Enable CA File')
def get_CA_file_name(rocket_param):
    return rocket_param.get('CA File').get('CA File Path')
def set_CA_file_name(rocket_param, file_name):
    rocket_param['CA File']['CA File Path'] = file_name
    return rocket_param
def get_constant_CA(rocket_param):
    return rocket_param.get('Constant CA').get('Constant CA [-]')
def set_constant_CA(rocket_param, CA):
    rocket_param['Constant CA']['Constant CA [-]'] = CA
    return rocket_param
def get_burnoutCA_file_name(rocket_param):
    return rocket_param.get('CA File').get('BurnOut CA File Path')
def set_burnoutCA_file_name(rocket_param, file_name):
    rocket_param['CA File']['BurnOut CA File Path'] = file_name
    return rocket_param
def get_constant_burnoutCA(rocket_param):
    return rocket_param.get('Constant CA').get('Constant BurnOut CA [-]')
def set_constant_burnoutCA(rocket_param, CA):
    rocket_param['Constant CA']['Constant BurnOut CA [-]'] = CA
    return rocket_param

def CNa_file_is_enable(rocket_param):
    return rocket_param.get('Enable CNa File')
def get_CNa_file_name(rocket_param):
    return rocket_param.get('CNa File').get('CNa File Path')
def set_CNa_file_name(rocket_param, file_name):
    rocket_param['CNa File']['CNa File Path'] = file_name
    return rocket_param
def get_constant_CNa(rocket_param):
    return rocket_param.get('Constant CNa').get('Constant CNa [1/rad]')
def set_constant_CNa(rocket_param, CNa):
    rocket_param['Constant CNa']['Constant CNa [1/rad]'] = CNa
    return rocket_param

def get_cant_angle(rocket_param):
    return rocket_param.get('Fin Cant Angle [deg]')
def set_cant_angle(rocket_param, cant_angle):
    rocket_param['Fin Cant Angle [deg]'] = cant_angle
    return rocket_param

def Cld_file_is_enable(rocket_param):
    return rocket_param.get('Enable Cld File')
def get_Cld_file_name(rocket_param):
    return rocket_param.get('Cld File').get('Cld File Path')
def set_Cld_file_name(rocket_param, file_name):
    rocket_param['Cld File']['Cld File Path'] = file_name
    return rocket_param
def get_constant_Cld(rocket_param):
    return rocket_param.get('Constant Cld').get('Constant Cld [1/rad]')
def set_constant_Cld(rocket_param, Cld):
    rocket_param['Constant Cld']['Constant Cld [1/rad]'] = Cld
    return rocket_param

def Clp_file_is_enable(rocket_param):
    return rocket_param.get('Enable Clp File')
def get_Clp_file_name(rocket_param):
    return rocket_param.get('Clp File').get('Clp File Path')
def set_Clp_file_name(rocket_param, file_name):
    rocket_param['Clp File']['Clp File Path'] = file_name
    return rocket_param
def get_constant_Clp(rocket_param):
    return rocket_param.get('Constant Clp').get('Constant Clp [-]')
def set_constant_Clp(rocket_param, Clp):
    rocket_param['Constant Clp']['Constant Clp [-]'] = Clp
    return rocket_param

def Cmq_file_is_enable(rocket_param):
    return rocket_param.get('Enable Cmq File')
def get_Cmq_file_name(rocket_param):
    return rocket_param.get('Cmq File').get('Cmq File Path')
def set_Cmq_file_name(rocket_param, file_name):
    rocket_param['Cmq File']['Cmq File Path'] = file_name
    return rocket_param
def get_constant_Cmq(rocket_param):
    return rocket_param.get('Constant Cmq').get('Constant Cmq [-]')
def set_constant_Cmq(rocket_param, Cmq):
    rocket_param['Constant Cmq']['Constant Cmq [-]'] = Cmq
    return rocket_param

def Cnr_file_is_enable(rocket_param):
    return rocket_param.get('Enable Cnr File')
def get_Cnr_file_name(rocket_param):
    return rocket_param.get('Cnr File').get('Cnr File Path')
def set_Cnr_file_name(rocket_param, file_name):
    rocket_param['Cnr File']['Cnr File Path'] = file_name
    return rocket_param
def get_constant_Cnr(rocket_param):
    return rocket_param.get('Constant Cnr').get('Constant Cnr [-]')
def set_constant_Cnr(rocket_param, Cnr):
    rocket_param['Constant Cnr']['Constant Cnr [-]'] = Cnr
    return rocket_param

## Engine Parameter ####################################
def get_engine_param_file_path(stage_config):
    return stage_config.get('Engine Configuration File Path')

def get_engine_param_file_name(stage_config):
    file_path = get_engine_param_file_path(stage_config)
    return get_file_name_from_path(file_path)

def get_engine_param(stage_config):
    engine_param_file_path = get_engine_param_file_path(stage_config)
    engine_param = json.load(open(engine_param_file_path))
    return engine_param

def thrust_file_is_enable(engine_param):
    return engine_param.get('Enable Thrust File')
def get_thrust_file_name(engine_param):
    return engine_param.get('Thrust File').get('Thrust at vacuum File Path')
def set_thrust_file_name(engine_param, thrust_file_name):
    engine_param = engine_param['Thrust File']['Thrust at vacuum File Path'] = thrust_file_name
    return engine_param
def get_constant_thrust(engine_param):
    return engine_param.get('Constant Thrust').get('Thrust at vacuum [N]')
def set_constant_thrust(engine_param, thrust):
    engine_param = engine_param['Constant Thrust']['Thrust at vacuum [N]'] = thrust
    return engine_param

def get_engine_miss_alignment_y(engine_param):
    return engine_param.get('Engine Miss-Alignment').get('y-Axis Angle [deg]')
def get_engine_miss_alignment_z(engine_param):
    return engine_param.get('Engine Miss-Alignment').get('z-Axis Angle [deg]')
def set_engine_miss_alignment_y(engine_param, y_value):
    engine_param['Engine Miss-Alignment']['y-Axis Angle [deg]'] = y_value
    return engine_param
def set_engine_miss_alignment_z(engine_param, z_value):
    engine_param['Engine Miss-Alignment']['z-Axis Angle [deg]'] = z_value
    return engine_param


## SOE ####################################
def get_soe_file_path(stage_config):
    return stage_config.get('Sequence of Event File Path')

def get_soe_file_name(stage_config):
    file_path = get_soe_file_path(stage_config)
    return get_file_name_from_path(file_path)

def get_soe(stage_config):
    soe_file_path = get_soe_file_path(stage_config)
    soe = json.load(open(soe_file_path))
    return soe


def is_enable_parachute(soe):
    return soe.get('Enable Parachute Open')

def is_enable_secondary_parachute(soe):
    return soe.get('Enable Secondary Parachute Open')

def get_parachute_drag_factor(soe):
    return soe.get('Parachute').get('Drag Factor Cd*S [m2]')
def get_secondary_parachute_drag_factor(soe):
    return soe.get('Secondary Parachute').get('Drag Factor Cd*S [m2]')
def set_parachute_drag_factor(soe, drag_factor_value):
    soe['Parachute']['Drag Factor Cd*S [m2]'] = drag_factor_value
    return soe
def set_secondary_parachute_drag_factor(soe, drag_factor_value):
    soe['Secondary Parachute']['Drag Factor Cd*S [m2]'] = drag_factor_value
    return soe


## Json's Copy #############################
def _file_copy_by_param(param, enable_item, file_block_item, path_item, dst_dir):
    if param.get(enable_item):
        path = param.get(file_block_item).get(path_item)
        shutil.copy2(path, dst_dir+'/')

def copy_config_files(solver_config, dst_dir):
    if not os.path.exists(dst_dir):
        print('Error! Not found destination directory')
        exit()

    for i in range(get_stage_count(solver_config)):
        # from solver config
        stage_config_file_path = get_stage_config_file_path(solver_config, i+1)
        shutil.copy2(stage_config_file_path, dst_dir+'/')

        # from stage_config
        stage_config = get_stage_config(solver_config, i+1)
        rocket_param_file_path = get_rocket_param_file_path(stage_config)
        shutil.copy2(rocket_param_file_path, dst_dir+'/')
        engine_param_file_path = get_engine_param_file_path(stage_config)
        shutil.copy2(engine_param_file_path, dst_dir+'/')
        soe_file_path = get_soe_file_path(stage_config)
        shutil.copy2(soe_file_path, dst_dir+'/')

        # from rocket config
        rocket_param = get_rocket_param(stage_config)
        _file_copy_by_param(rocket_param, 'Enable Program Attitude', 'Program Attitude File', 'Program Attitude File Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable X-C.G. File', 'X-C.G. File', 'X-C.G. File Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable M.I. File', 'M.I. File', 'M.I. File Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable X-C.P. File', 'X-C.P. File', 'X-C.P. File Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable CA File', 'CA File', 'CA File Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable CA File', 'CA File', 'BurnOut CA File Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable CNa File', 'CNa File', 'CNa File Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable Cld File', 'Cld File', 'CldFile Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable Clp File', 'Clp File', 'Clp File Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable Cmq File', 'Cmq File', 'Cmq File Path', dst_dir)
        _file_copy_by_param(rocket_param, 'Enable Cnr File', 'Cnr File', 'Cnr File Path', dst_dir)

        # from engine config
        engine_param = get_engine_param(stage_config)
        _file_copy_by_param(engine_param, 'Enable Thrust File', 'Thrust File', 'Thrust at vacuum File Path', dst_dir)

       
    
