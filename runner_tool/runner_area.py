import os
import json
import numpy as np

from path_define import runner_area_directory

from runner_tool.json_api import copy_config_files
from runner_tool.solver_control import copy_solver_binary, clean_solver_binary
from runner_tool.runner_multi import run_multi

from runner_tool.area_wind_generator import AreaWindGenerator
from runner_tool.law_wind import make_law_wind

class AreaCaseConfig:
    '''
    Area計算ケース情報をまとめるクラス
    '''
    def __init__(self, num, wind_speed, wind_direction, solver_config_file_name):
        self.case_num = num
        self.wind_speed = wind_speed
        self.wind_direction = wind_direction
        self.solver_config_file_name = solver_config_file_name



def run_area(solver_config_json_file_name, aera_config_json_file_name, max_thread_run=False):
    # 作業ディレクトリを作成
    work_dir = './'+runner_area_directory
    if os.path.exists(work_dir):
        workdir_org = work_dir
        i = 1
        while os.path.exists(work_dir):
            work_dir = workdir_org + '_%02d' % (i)
            i = i + 1
    os.mkdir(work_dir)

    # 風設定読み出し
    area_config = json.load(open(aera_config_json_file_name))
    wind_config = AreaWindGenerator(area_config)

    # 風データ生成
    # 風ファイル保存
    # solver.jsonの風項目を書き換えて別名保存
    solver_config = json.load(open(solver_config_json_file_name))
    model_id_original = solver_config.get('Model ID')
    wind_case_list = []
    case_num = 0
    for i_vel in range(len(wind_config.wind_speed_array)):
        for j_dir in range(len(wind_config.wind_direction_array)):
            alt_array, u_array, v_array = make_law_wind(wind_config.height_wind_reference, wind_config.wind_speed_array[i_vel], wind_config.wind_direction_array[j_dir], wind_config.wind_exponatial)
            wind_data = np.c_[alt_array, u_array, v_array]
            wind_file_name = 'wind_'+str(case_num)+'.csv'
            np.savetxt(work_dir+'/'+wind_file_name, wind_data, delimiter=',', header='alt[m],u[m/s],v[m/s]', fmt='%0.4f', comments='')
            
            solver_config['Model ID'] = model_id_original + '_wind' + str(case_num)
            solver_config['Wind Condition']['Enable Wind'] = True
            solver_config['Wind Condition']['Wind File Path'] = wind_file_name
            sep = solver_config_json_file_name.rsplit('.json', 1)
            case_solver_config_file_name = sep[0]+'_'+str(case_num)+'.json'
            with open(work_dir+'/'+case_solver_config_file_name, 'w') as f:
                json.dump(solver_config, f, indent=4)            
            
            case = AreaCaseConfig(case_num, wind_config.wind_speed_array[i_vel], wind_config.wind_direction_array[j_dir], case_solver_config_file_name)
            wind_case_list.append(case)
            case_num += 1

    # ソルバ,solver以外の設定ファイルのコピー
    # オリジナルのsolver.jsonから設定ファイル群は取得する
    copy_config_files(solver_config, work_dir)
    copy_solver_binary(work_dir)

    # 計算ケースリストの出力
    case_num_array = []
    wind_speed_array = []
    wind_dir_array = []
    case_solver_config_file_name_list = []
    for case in wind_case_list:
        case_num_array.append(case.case_num)
        wind_speed_array.append(case.wind_speed)
        wind_dir_array.append(case.wind_direction)
        case_solver_config_file_name_list.append(case.solver_config_file_name)
    case_data = np.c_[case_num_array, wind_speed_array, wind_dir_array]
    np.savetxt(work_dir+'/wind_case_list.csv', case_data, delimiter=',', header='case,speed[m/s],direction[deg]', fmt=['%d', '%0.4f', '%0.4f'], comments='')
    
    ## 実行部 ############################################################
    os.chdir(work_dir)

    run_multi(case_solver_config_file_name_list, max_thread_run)
    
    print('Work Directory: '+work_dir)

    os.chdir('../')
    clean_solver_binary(work_dir)
    ##############################################################
 

