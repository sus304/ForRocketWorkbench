# 1条件計算ランナー

import os
import json
import shutil

from path_define import runner_trajectory_directory

from runner_tool.json_api import copy_config_files
from runner_tool.runner_single import run_single
from runner_tool.solver_control import copy_solver_binary, clean_solver_binary

def run_trajectroy(solver_config_json_file_name):
    # 作業ディレクトリを作成
    work_dir = './' + runner_trajectory_directory
    if os.path.exists(work_dir):
        workdir_org = work_dir
        i = 1
        while os.path.exists(work_dir):
            work_dir = workdir_org + '_%02d' % (i)
            i = i + 1
    os.mkdir(work_dir)


    # ソルバ,設定ファイルのコピー
    shutil.copy2(solver_config_json_file_name, work_dir)
    solver_config = json.load(open(solver_config_json_file_name))
    if solver_config.get('Wind Condition').get('Enable Wind'):
        shutil.copy2(solver_config.get('Wind Condition').get('Wind File Path'), work_dir)
    copy_config_files(solver_config, work_dir)
    copy_solver_binary(work_dir)


    ## 実行部 ############################################################
    os.chdir(work_dir)
    print('\rCalculating ...', end='')

    run_single(solver_config_json_file_name)

    print('\rComplete calculate.\n', end='')
    
    print('Work Directory: '+work_dir)

    os.chdir('../')
    clean_solver_binary(work_dir)
    ##############################################################

    
