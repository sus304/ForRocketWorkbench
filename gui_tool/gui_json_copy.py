import os
import shutil
import json

from PyQt5 import QtWidgets

def get_jsons_path(solver_config_json_path):
    solver_config = json.load(open(solver_config_json_path, mode='r'))
    configs_dir = os.path.dirname(solver_config_json_path) + '/'

    stage_config_path = configs_dir + solver_config.get('Stage1 Config File List')
    stage_config = json.load(open(stage_config_path, mode='r'))

    rocket_param_path = configs_dir + stage_config.get('Rocket Configuration File Path')
    engine_param_path = configs_dir + stage_config.get('Engine Configuration File Path')
    soe_path = configs_dir + stage_config.get('Sequence of Event File Path')
    return stage_config_path, rocket_param_path, engine_param_path, soe_path

def _file_copy_by_param(param_path, enable_item, file_block_item, path_item, work_dir):
    param = json.load(open(param_path, mode='r'))
    if param.get(enable_item):
        path = os.path.dirname(param_path) + '/' + param.get(file_block_item).get(path_item)
        name = os.path.basename(path)
        shutil.copy2(path, work_dir+'/'+name)

def copy_jsons(work_dir,
            solver_config_json_path,
            stage_config_json_path,
            rocket_param_json_path,
            engine_param_json_path,
            soe_json_path,
        ):
    shutil.copy2('ForRocket.exe', work_dir)

    shutil.copy2(solver_config_json_path, work_dir)
    shutil.copy2(stage_config_json_path, work_dir)
    shutil.copy2(rocket_param_json_path, work_dir)
    shutil.copy2(engine_param_json_path, work_dir)
    shutil.copy2(soe_json_path, work_dir)

    solver_config = json.load(open(solver_config_json_path, mode='r'))
    if solver_config.get('Wind Condition').get('Enable Wind'):
        path = os.path.dirname(solver_config_json_path) + '/' + solver_config.get('Wind Condition').get('Wind File Path')
        name = os.path.basename(path)
        shutil.copy2(path, work_dir+'/'+name)
    
    # from rocket config
    _file_copy_by_param(rocket_param_json_path, 'Enable Program Attitude', 'Program Attitude File', 'Program Attitude File Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable X-C.G. File', 'X-C.G. File', 'X-C.G. File Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable M.I. File', 'M.I. File', 'M.I. File Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable X-C.P. File', 'X-C.P. File', 'X-C.P. File Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable CA File', 'CA File', 'CA File Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable CA File', 'CA File', 'BurnOut CA File Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable CNa File', 'CNa File', 'CNa File Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable Cld File', 'Cld File', 'CldFile Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable Clp File', 'Clp File', 'Clp File Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable Cmq File', 'Cmq File', 'Cmq File Path', work_dir)
    _file_copy_by_param(rocket_param_json_path, 'Enable Cnr File', 'Cnr File', 'Cnr File Path', work_dir)

    # from engine config
    _file_copy_by_param(engine_param_json_path, 'Enable Thrust File', 'Thrust File', 'Thrust at vacuum File Path', work_dir)

    return os.path.basename(solver_config_json_path)


def copy_area_json(work_dir, area_config_json_path):
    shutil.copy2(area_config_json_path, work_dir)

    return os.path.basename(area_config_json_path)
