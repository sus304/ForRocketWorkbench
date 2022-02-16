import os
import json
import shutil
from copy import deepcopy
import numpy as np

from runner_tool.json_api import get_stage_config, get_stage_config_file_name
from runner_tool.json_api import get_rocket_param, get_rocket_param_file_name
from runner_tool.json_api import get_engine_param, get_engine_param_file_name
from runner_tool.json_api import get_soe, get_soe_file_name

from runner_tool.solver_control import copy_solver_binary, clean_solver_binary
from runner_tool.runner_multi import run_multi

from runner_tool.dispersion_rocket_generator import RocketDispersionConfig
from runner_tool.dispersion_engine_generator import EngineDispersionConfig
from runner_tool.dispersion_soe_generator import SoeDispersionConfig
from runner_tool.dispersion_wind_generator import WindDispersionConfig
from runner_tool.dispersion_solver_generator import SolverDispersionConfig

from path_define import runner_dispersion_directory


class DispersionCaseConfig:
    '''
    計算ケース情報をまとめるクラス
    '''
    def __init__(self, num, solver_config_file_name):
        self.case_num = num
        self.solver_config_file_name = solver_config_file_name



def run_dispersion(solver_config_json_file_name, dispersion_config_json_file_name, max_thread_run=False):
    # 作業ディレクトリを作成
    work_dir = './'+runner_dispersion_directory
    if os.path.exists(work_dir):
        workdir_org = work_dir
        i = 1
        while os.path.exists(work_dir):
            work_dir = workdir_org + '_%02d' % (i)
            i = i + 1
    os.mkdir(work_dir)

    # オリジナルパラメータファイル読み込み
    solver_config = json.load(open(solver_config_json_file_name))
    stage_config = get_stage_config(solver_config, 1)  # 1段のみ対応
    rocket_param = get_rocket_param(stage_config)
    engine_param = get_engine_param(stage_config)
    soe = get_soe(stage_config)

    # dispersion設定ファイル群取得
    dispersion_config = json.load(open(dispersion_config_json_file_name))
    case_count = dispersion_config.get('Case Count')

    dsp_wind_param = json.load(open(dispersion_config.get('Wind Parameter File')))
    dsp_solver_param = json.load(open(dispersion_config.get('Solver Parameter File')))
    dsp_rocket_param = json.load(open(dispersion_config.get('Rocket Parameter File')))
    dsp_engine_param = json.load(open(dispersion_config.get('Engine Parameter File')))
    dsp_soe_param = json.load(open(dispersion_config.get('SOE Parameter File')))

    rocket_dsp_config = RocketDispersionConfig(dsp_rocket_param)
    soe_dsp_config = SoeDispersionConfig(dsp_soe_param)
    engine_dsp_config = EngineDispersionConfig(dsp_engine_param)
    wind_dsp_config = WindDispersionConfig(dsp_wind_param)
    solver_dsp_config = SolverDispersionConfig(dsp_solver_param)


    # 計算ディレクトリを作成
    calc_dir = 'cases'
    os.mkdir(work_dir+'/'+calc_dir)

    # ディレクトリ構成
    # root/
    #    |- runner_tool/
    #    |- post_tool/
    #    |- runner.py
    #    |- post.py
    #    |- *.json
    #    |- *.csv
    #    |- work_trajectory/
    #    |- work_area/
    #    |- work_dispersion/
    #               |- cases/
    #                      |- ForRocket.exe
    #                      |- *.json
    #                      |- *_flight_log.csv
    #               |- ellipse_3sigma_impact_point.kml
    #               |- ellipse_2sigma_impact_point.kml
    #               |- impact_points.kml
    #               |- summary.txt
    #               |- case_list.csv



    # 引数のケース数でパラメータファイルを作成
    # 項目を書き換えて別名保存
    # 各ケースで全設定ファイルを作成する
    dsp_case_list = []
    for case_num in range(case_count):
        solver_config_case = deepcopy(solver_config)
        stage_config_case = deepcopy(stage_config)
        rocket_param_case = deepcopy(rocket_param)
        engine_param_case = deepcopy(engine_param)
        soe_case = deepcopy(soe)

        # Rocket
        if rocket_dsp_config.is_enable_dispersion():
            rocket_param_case = rocket_dsp_config.generate_json_dict(rocket_param_case, work_dir+'/'+calc_dir+'/', case_num)
            case_rocket_file_name = str(case_num)+'_'+get_rocket_param_file_name(stage_config_case)
            with open(work_dir+'/'+calc_dir+'/'+case_rocket_file_name, 'w') as f:
                json.dump(rocket_param_case, f, indent=4)      
            stage_config_case['Rocket Configuration File Path'] = case_rocket_file_name
        else:
            shutil.copy2(get_rocket_param_file_name(stage_config_case), work_dir+'/'+calc_dir)
            stage_config_case['Rocket Configuration File Path'] = get_rocket_param_file_name(stage_config_case)

        # Engine
        if engine_dsp_config.is_enable_dispersion():
            engine_param_case = engine_dsp_config.generate_json_dict(engine_param_case, work_dir+'/'+calc_dir+'/', case_num)
            case_engine_file_name = str(case_num)+'_'+get_engine_param_file_name(stage_config_case)
            with open(work_dir+'/'+calc_dir+'/'+case_engine_file_name, 'w') as f:
                json.dump(engine_param_case, f, indent=4)      
            stage_config_case['Engine Configuration File Path'] = case_engine_file_name
        else:
            shutil.copy2(get_engine_param_file_name(stage_config_case), work_dir+'/'+calc_dir+'/')
            stage_config_case['Engine Configuration File Path'] = get_engine_param_file_name(stage_config_case)

        # SOE
        if soe_dsp_config.is_enable_dispersion():
            soe_case = soe_dsp_config.generate_json_dict(soe_case)
            case_soe_file_name = str(case_num)+'_'+get_soe_file_name(stage_config_case)
            with open(work_dir+'/'+calc_dir+'/'+case_soe_file_name, 'w') as f:
                json.dump(soe_case, f, indent=4)      
            stage_config_case['Sequence of Event File Path'] = case_soe_file_name
        else:
            shutil.copy2(get_soe_file_name(stage_config_case), work_dir+'/'+calc_dir+'/')
            stage_config_case['Sequence of Event File Path'] = get_soe_file_name(stage_config_case)

        # Stage
        case_stage_file_name = str(case_num)+'_'+get_stage_config_file_name(solver_config_case, 1)
        with open(work_dir+'/'+calc_dir+'/'+case_stage_file_name, 'w') as f:
            json.dump(stage_config_case, f, indent=4)      
        solver_config_case['Stage1 Config File List'] = case_stage_file_name

        # Wind
        case_wind_file_name = wind_dsp_config.generate_wind_file(work_dir+'/'+calc_dir+'/', case_num)
        solver_config_case['Wind Condition']['Wind File Path'] = case_wind_file_name
        solver_config_case['Wind Condition']['Enable Wind'] = True
        
        # Solver
        solver_config_case['Model ID'] = str(case_num)+'_'+solver_config.get('Model ID')
        case_solver_file_name = str(case_num)+'_'+solver_config_json_file_name
        with open(work_dir+'/'+calc_dir+'/'+case_solver_file_name, 'w') as f:
            json.dump(solver_config_case, f, indent=4)
                       

        case = DispersionCaseConfig(case_num, case_solver_file_name)
        dsp_case_list.append(case)

    copy_solver_binary(work_dir+'/'+calc_dir+'/')


    # 計算ケースリストの出力
    case_num_array = []
    case_solver_config_file_name_list = []
    for case in dsp_case_list:
        case_num_array.append(case.case_num)
        case_solver_config_file_name_list.append(case.solver_config_file_name)
    case_data = case_num_array
    np.savetxt(work_dir+'/'+calc_dir+'/'+'case_list.csv', case_data, delimiter=',', header='case', fmt=['%d'], comments='')
    
    ## 実行部 ############################################################
    os.chdir(work_dir)
    os.chdir(calc_dir)

    run_multi(case_solver_config_file_name_list, max_thread_run)
    
    print('Work Directory: '+work_dir)

    os.chdir('../')
    os.chdir('../')
    clean_solver_binary(work_dir+'/'+calc_dir+'/')
    ##############################################################

