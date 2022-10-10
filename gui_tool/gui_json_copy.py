import os
import shutil
import json

def auto_suggest_jsons_path(solver_config_json_path):
    '''
    solver.jsonと同じディレクトリで他のjsonファイルパスを生成する
    '''
    solver_config = json.load(open(solver_config_json_path, mode='r'))
    configs_dir = os.path.dirname(solver_config_json_path) + '/'

    stage_config_path = configs_dir + solver_config.get('Stage1 Config File List')
    stage_config = json.load(open(stage_config_path, mode='r'))

    rocket_param_path = configs_dir + stage_config.get('Rocket Configuration File Path')
    engine_param_path = configs_dir + stage_config.get('Engine Configuration File Path')
    soe_path = configs_dir + stage_config.get('Sequence of Event File Path')
    return stage_config_path, rocket_param_path, engine_param_path, soe_path


def _file_copy_by_param_file(param_path, enable_item, file_block_item, path_item, work_dir):
    param = json.load(open(param_path, mode='r'))
    if param.get(enable_item):
        path = os.path.dirname(param_path) + '/' + param.get(file_block_item).get(path_item)
        shutil.copy2(path, work_dir+'/')

def import_jsons(work_dir,
            solver_config_json_path,
            stage_config_json_path,
            rocket_param_json_path,
            engine_param_json_path,
            soe_json_path,
        ):

    shutil.copy2(solver_config_json_path, work_dir)
    shutil.copy2(stage_config_json_path, work_dir)
    shutil.copy2(rocket_param_json_path, work_dir)
    shutil.copy2(engine_param_json_path, work_dir)
    shutil.copy2(soe_json_path, work_dir)

    solver_config = json.load(open(solver_config_json_path, mode='r'))
    if solver_config.get('Wind Condition').get('Enable Wind'):
        path = os.path.dirname(solver_config_json_path) + '/' + solver_config.get('Wind Condition').get('Wind File Path')
        shutil.copy2(path, work_dir+'/')

    # from rocket config
    _file_copy_by_param_file(rocket_param_json_path, 'Enable Program Attitude', 'Program Attitude File', 'Program Attitude File Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable X-C.G. File', 'X-C.G. File', 'X-C.G. File Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable M.I. File', 'M.I. File', 'M.I. File Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable X-C.P. File', 'X-C.P. File', 'X-C.P. File Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable CA File', 'CA File', 'CA File Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable CA File', 'CA File', 'BurnOut CA File Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable CNa File', 'CNa File', 'CNa File Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable Cld File', 'Cld File', 'CldFile Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable Clp File', 'Clp File', 'Clp File Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable Cmq File', 'Cmq File', 'Cmq File Path', work_dir)
    _file_copy_by_param_file(rocket_param_json_path, 'Enable Cnr File', 'Cnr File', 'Cnr File Path', work_dir)

    # from engine config
    _file_copy_by_param_file(engine_param_json_path, 'Enable Thrust File', 'Thrust File', 'Thrust at vacuum File Path', work_dir)

    return os.path.basename(solver_config_json_path)


def import_area_json(work_dir, area_config_json_path):
    shutil.copy2(area_config_json_path, work_dir)

    return os.path.basename(area_config_json_path)


def import_montecarlo_json(work_dir, montecarlo_config_json_path):
    shutil.copy2(montecarlo_config_json_path, work_dir)
    base_dir = os.path.dirname(montecarlo_config_json_path) + '/'

    mc_config = json.load(open(montecarlo_config_json_path, mode='r'))
    if mc_config.get('Error Parameters').get('Wind').get('Enable'):
        shutil.copy2(base_dir+mc_config.get('Error Parameters').get('Wind').get('Base Wind File Path'), work_dir)
        shutil.copy2(base_dir+mc_config.get('Error Parameters').get('Wind').get('Estimate Error Wind File Path'), work_dir)

    return os.path.basename(montecarlo_config_json_path)


def import_dispersion_json(work_dir, dispersion_config_json_path):
    shutil.copy2(dispersion_config_json_path, work_dir)
    base_dir = os.path.dirname(dispersion_config_json_path) + '/'

    dsp_config = json.load(open(dispersion_config_json_path, mode='r'))
    shutil.copy2(base_dir+dsp_config.get('Wind Parameter File'), work_dir)
    shutil.copy2(base_dir+dsp_config.get('Solver Parameter File'), work_dir)
    shutil.copy2(base_dir+dsp_config.get('Rocket Parameter File'), work_dir)
    shutil.copy2(base_dir+dsp_config.get('Engine Parameter File'), work_dir)
    shutil.copy2(base_dir+dsp_config.get('SOE Parameter File'), work_dir)

    return os.path.basename(dispersion_config_json_path)
