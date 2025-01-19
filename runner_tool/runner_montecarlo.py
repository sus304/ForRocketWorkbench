import os
import json
import shutil
from copy import deepcopy
import numpy as np
from scipy.stats import truncnorm
from concurrent import futures

from runner_tool.json_api import get_stage_config, get_stage_config_file_name, set_constant_burnoutCA
from runner_tool.json_api import get_rocket_param, get_rocket_param_file_name
from runner_tool.json_api import get_engine_param, get_engine_param_file_name
from runner_tool.json_api import get_soe, get_soe_file_name

from runner_tool.json_api import get_elevation, set_elevation
from runner_tool.json_api import CA_file_is_enable
from runner_tool.json_api import get_CA_file_name, set_CA_file_name
from runner_tool.json_api import get_constant_CA, set_constant_CA
from runner_tool.json_api import get_burnoutCA_file_name, set_burnoutCA_file_name
from runner_tool.json_api import thrust_file_is_enable
from runner_tool.json_api import get_thrust_file_name, set_thrust_file_name
from runner_tool.json_api import get_constant_thrust, set_constant_thrust
from runner_tool.json_api import get_mass_prop, set_mass_prop
from runner_tool.json_api import get_parachute_drag_factor, set_parachute_drag_factor
from runner_tool.json_api import get_secondary_parachute_drag_factor, set_secondary_parachute_drag_factor
from runner_tool.json_api import xcg_file_is_enable, get_xcg_file_name, set_xcg_file_name
from runner_tool.json_api import moi_file_is_enable, get_moi_file_name, set_moi_file_name

from runner_tool.solver_control import copy_solver_binary, clean_solver_binary
from runner_tool.runner_multi import run_multi

from wind_tool.generate_montecarlo_wind import generate_montecarlo_2sigma_winds

from path_define import runner_montecarlo_directory

class MontecarloCaseConfig:
    '''
    各ケースの情報をまとめるクラス
    '''
    def __init__(self, case_number, case_solver_config_file_name):
        self.case_num = case_number
        self.solver_config_file_name = case_solver_config_file_name


def run_montecarlo(solver_config_json_file_name, montecarlo_config_json_file_name, max_thread_run=False):
    # 作業ディレクトリを作成
    work_dir = './'+runner_montecarlo_directory
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

    montecarlo_config = json.load(open(montecarlo_config_json_file_name))
    case_count = montecarlo_config.get('MonteCarlo Case Count')
    error_params = montecarlo_config.get('Error Parameters')


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
    #    |- work_montecarlo/
    #               |- cases/
    #                      |- ForRocket.exe
    #                      |- *.json
    #                      |- *_flight_log.csv


    wind_alt_list = []
    wind_u_list = []
    wind_v_list = []
    launcher_elv_list = []
    mach_list = []
    CA_list = []
    prop_mass_list = []
    thrust_list = []
    primary_CdS_list = []
    secondary_CdS_list = []

    if error_params.get('Wind').get('Enable'):
        zipfile_path = error_params.get('Wind').get('Wind Files Zip Path')
        if zipfile_path == '':
            raise ValueError('Wind Files Zip Path is empty')
        if not os.path.exists(zipfile_path):
            raise FileNotFoundError(zipfile_path)
        shutil.unpack_archive(zipfile_path, work_dir+'/')
        winds_dir = os.path.splitext(os.path.basename(zipfile_path))[0]
        wind_files = os.listdir(work_dir+'/'+winds_dir)

        if case_count > len(wind_files):
            # ケース数が風ファイル数より多い場合、風ファイルをランダムにコピーしてcase_countに合わせる
            for i in range(case_count - len(wind_files)):
                wind_file = wind_files[np.random.randint(0, len(wind_files))]
                shutil.copy(work_dir+'/'+winds_dir+'/'+wind_file, work_dir+'/'+winds_dir+'/'+str(i)+'_wind.csv')
        wind_files = os.listdir(work_dir+'/'+winds_dir)
        np.random.shuffle(wind_files)
        # wind_alt_list, wind_u_list, wind_v_list = generate_montecarlo_2sigma_winds(error_params.get('Wind').get('Base Wind File Path'), error_params.get('Wind').get('Estimate Error Wind File Path'), case_count)

    if error_params.get('Launcher Elevation').get('Enable'):
        mean = get_elevation(solver_config)
        std = error_params.get('Launcher Elevation').get('Error 3sigma [deg]') / 3
        launcher_elv_list = truncnorm.rvs(-3, 3, loc=mean, scale=std, size=case_count)
        launcher_elv_list[0] = mean
    else:
        mean = get_elevation(solver_config)
        launcher_elv_list = [mean]*(case_count)

    if error_params.get('CA').get('Enable'):
        if CA_file_is_enable(rocket_param):
            load_array = np.loadtxt(get_CA_file_name(rocket_param), delimiter=',', skiprows=1)
            mach_array = load_array[:,0]
            ca_array = load_array[:,1]

            mean = 1.0
            std = error_params.get('CA').get('Error 3sigma [%]') / 100.0 / 3
            ca_error_list = truncnorm.rvs(-3, 3, loc=mean, scale=std, size=case_count)
            ca_error_list[0] = 1.0
            CA_list = [ca_array]*(case_count)
            for i in range(case_count):
                mach_list.append(mach_array)
                CA_list[i] = CA_list[i] * ca_error_list[i]
        else:
            mean = get_constant_CA(rocket_param)
            std = (mean * error_params.get('CA').get('Error 3sigma [%]') / 100.0) / 3
            CA_list = truncnorm.rvs(-3, 3, loc=mean, scale=std, size=case_count)
            CA_list[0] = mean

    if error_params.get('Propellant Mass').get('Enable'):
        mean = get_mass_prop(rocket_param)
        std = (mean * error_params.get('Propellant Mass').get('Error 3sigma [%]') / 100.0) / 3
        prop_mass_list = truncnorm.rvs(-3, 3, loc=mean, scale=std, size=case_count)
        prop_mass_list[0] = mean
    else:
        mean = get_mass_prop(rocket_param)
        prop_mass_list = [mean]*(case_count)

    if error_params.get('Thrust').get('Enable') and thrust_file_is_enable(engine_param):
        load_array = np.loadtxt(get_thrust_file_name(engine_param), delimiter=',', skiprows=1)
        time_array = load_array[:,0]
        thrust_vac_array = load_array[:,1]
        mdot_p_array = load_array[:,2]

        mean = 0.0
        std = error_params.get('Thrust').get('Error 3sigma [%]') / 100.0 / 3
        thrust_error_list = truncnorm.rvs(-3, 3, loc=mean, scale=std, size=case_count)
        thrust_error_list[0] = 0.0
        thrust_list = [thrust_vac_array]*(case_count)
        for i in range(case_count):
            thrust_list[i] = thrust_list[i] * (thrust_error_list[i] + 1.0)

    if error_params.get('Primary Parachute Drag').get('Enable'):
        mean = get_parachute_drag_factor(soe)
        std = (mean * error_params.get('Primary Parachute Drag').get('Error 3sigma [%]') / 100.0) / 3
        primary_CdS_list = truncnorm.rvs(-3, 3, loc=mean, scale=std, size=case_count)
        primary_CdS_list[0] = mean
    else:
        mean = get_parachute_drag_factor(soe)
        primary_CdS_list = [mean]*(case_count)

    if error_params.get('Secondary Parachute Drag').get('Enable'):
        mean = get_secondary_parachute_drag_factor(soe)
        std = (mean * error_params.get('Secondary Parachute Drag').get('Error 3sigma [%]') / 100.0) / 3
        secondary_CdS_list = truncnorm.rvs(-3, 3, loc=mean, scale=std, size=case_count)
        secondary_CdS_list[0] = mean
    else:
        mean = get_secondary_parachute_drag_factor(soe)
        secondary_CdS_list = [mean]*(case_count)


    montecarlo_case_list = []

    def __run(case_num):
        solver_config_case = deepcopy(solver_config)
        stage_config_case = deepcopy(stage_config)
        rocket_param_case = deepcopy(rocket_param)
        engine_param_case = deepcopy(engine_param)
        soe_case = deepcopy(soe)

        # CA
        if CA_file_is_enable(rocket_param):
            load_array = np.loadtxt(get_CA_file_name(rocket_param), delimiter=',', skiprows=1)
            mach_array = load_array[:,0]
            ca_array = load_array[:,1]

            CA_file_name = str(case_num)+'_CA.csv'
            if error_params.get('CA').get('Enable'):
                np.savetxt(work_dir+'/'+calc_dir+'/'+CA_file_name, np.c_[np.array(mach_list[case_num]), np.array(CA_list[case_num])], delimiter=',', fmt='%0.6f', header='mach,CA', comments='')
            else:
                np.savetxt(work_dir+'/'+calc_dir+'/'+CA_file_name, np.c_[mach_array, ca_array], delimiter=',', fmt='%0.6f', header='mach,CA', comments='')
            rocket_param_case = set_CA_file_name(rocket_param_case, CA_file_name)
            rocket_param_case = set_burnoutCA_file_name(rocket_param_case, CA_file_name)
        else:
            if error_params.get('CA').get('Enable'):
                rocket_param_case = set_constant_CA(rocket_param_case, CA_list[case_num])
                rocket_param_case = set_constant_burnoutCA(rocket_param_case, CA_list[case_num])

        # propmass
        rocket_param_case = set_mass_prop(rocket_param_case, prop_mass_list[case_num])

        # Xcg
        if xcg_file_is_enable(rocket_param):
            load_array = np.loadtxt(get_xcg_file_name(rocket_param), delimiter=',', skiprows=1)
            t_array = load_array[:,0]
            xcg_array = load_array[:,1]

            xcg_file_name = str(case_num)+'_Xcg.csv'
            np.savetxt(work_dir+'/'+calc_dir+'/'+xcg_file_name, np.c_[t_array, xcg_array], delimiter=',', fmt='%0.6f', header='t,Xcg', comments='')
            rocket_param_case = set_xcg_file_name(rocket_param_case, xcg_file_name)

        # MOI
        if moi_file_is_enable(rocket_param):
            load_array = np.loadtxt(get_moi_file_name(rocket_param), delimiter=',', skiprows=1)
            t_array = load_array[:,0]
            yaw_array = load_array[:,1]
            pitch_array = load_array[:,2]
            roll_array = load_array[:,3]

            moi_file_name = str(case_num)+'_MOI.csv'
            np.savetxt(work_dir+'/'+calc_dir+'/'+moi_file_name, np.c_[t_array, yaw_array, pitch_array, roll_array], delimiter=',', fmt='%0.6f', header='t,yaw,pitch,roll', comments='')
            rocket_param_case = set_moi_file_name(rocket_param_case, moi_file_name)

        # thrust
        if thrust_file_is_enable(engine_param):
            load_array = np.loadtxt(get_thrust_file_name(engine_param), delimiter=',', skiprows=1)
            time_array = load_array[:,0]
            thrust_vac_array = load_array[:,1]
            mdot_p_array = load_array[:,2]
            thrust_csv_file_name = str(case_num)+'_thrust.csv'
            if error_params.get('Thrust').get('Enable'):
                np.savetxt(work_dir+'/'+calc_dir+'/'+thrust_csv_file_name, np.c_[time_array, np.array(thrust_list[case_num]), mdot_p_array], delimiter=',', fmt='%0.5f', header='t,f,mdot', comments='')
            else:
                np.savetxt(work_dir+'/'+calc_dir+'/'+thrust_csv_file_name, np.c_[time_array, thrust_vac_array, mdot_p_array], delimiter=',', fmt='%0.5f', header='t,f,mdot', comments='')
            engine_param_case = set_thrust_file_name(engine_param_case, thrust_csv_file_name)


        # CdS
        soe_case = set_parachute_drag_factor(soe_case, primary_CdS_list[case_num])
        # CdS2
        soe_case = set_secondary_parachute_drag_factor(soe_case, secondary_CdS_list[case_num])

        # wind
        wind_file_name = str(case_num)+'_wind.csv'
        if error_params.get('Wind').get('Enable'):
            wind_file_name = wind_files[case_num]
            shutil.copy(work_dir+'/'+winds_dir+'/'+wind_file_name, work_dir+'/'+calc_dir+'/'+wind_file_name)
            # np.savetxt(work_dir+'/'+calc_dir+'/'+wind_file_name, np.c_[np.array(wind_alt_list[case_num]), np.array(wind_u_list[case_num]), np.array(wind_v_list[case_num])], delimiter=',', fmt='%0.5f', header='alt,u,v', comments='')
        else:
            load_array = np.loadtxt(solver_config_case['Wind Condition']['Wind File Path'], delimiter=',', skiprows=1)
            height_array = load_array[:,0]
            u_array = load_array[:,1]
            v_array = load_array[:,2]
            np.savetxt(work_dir+'/'+calc_dir+'/'+wind_file_name, np.c_[height_array, u_array, v_array], delimiter=',', fmt='%0.5f', header='alt,u,v', comments='')
        solver_config_case['Wind Condition']['Wind File Path'] = wind_file_name
        solver_config_case['Wind Condition']['Enable Wind'] = True

        # elv
        solver_config_case = set_elevation(solver_config_case, launcher_elv_list[case_num])

        rocket_param_file_name = str(case_num)+'_rocket_param.json'
        engine_param_file_name = str(case_num)+'_engine_param.json'
        soe_file_name = str(case_num)+'_soe.json'
        stage_config_file_name = str(case_num)+'_stage_config.json'
        solver_config_file_name = str(case_num)+'_solver_config.json'

        with open(work_dir+'/'+calc_dir+'/'+rocket_param_file_name, 'w') as f:
            json.dump(rocket_param_case, f, indent=4)
        stage_config_case['Rocket Configuration File Path'] = rocket_param_file_name

        with open(work_dir+'/'+calc_dir+'/'+engine_param_file_name, 'w') as f:
            json.dump(engine_param_case, f, indent=4)
        stage_config_case['Engine Configuration File Path'] = engine_param_file_name

        with open(work_dir+'/'+calc_dir+'/'+soe_file_name, 'w') as f:
            json.dump(soe_case, f, indent=4)
        stage_config_case['Sequence of Event File Path'] = soe_file_name

        with open(work_dir+'/'+calc_dir+'/'+stage_config_file_name, 'w') as f:
            json.dump(stage_config_case, f, indent=4)
        solver_config_case['Stage1 Config File List'] = stage_config_file_name

        solver_config_case['Model ID'] = str(case_num)+'_'+solver_config.get('Model ID')
        with open(work_dir+'/'+calc_dir+'/'+solver_config_file_name, 'w') as f:
            json.dump(solver_config_case, f, indent=4)

        case = MontecarloCaseConfig(case_num, solver_config_file_name)
        montecarlo_case_list.append(case)

    future_list = []
    with futures.ThreadPoolExecutor(max_workers=6) as executor:
        for i in range(case_count):
            future = executor.submit(__run, i)
            future_list.append(future)
        _ = futures.as_completed(fs=future_list)

    copy_solver_binary(work_dir+'/'+calc_dir+'/')

    case_num_array = []
    case_solver_config_file_name_list = []
    for case in montecarlo_case_list:
        case_num_array.append(case.case_num)
        case_solver_config_file_name_list.append(case.solver_config_file_name)

    ## 実行部 ############################################################
    os.chdir(work_dir)
    os.chdir(calc_dir)

    run_multi(case_solver_config_file_name_list, max_thread_run)

    print('Work Directory: '+work_dir)

    os.chdir('../')
    os.chdir('../')
    clean_solver_binary(work_dir+'/'+calc_dir+'/')
    ##############################################################


