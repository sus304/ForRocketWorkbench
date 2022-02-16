# 1条件計算ランナー

import os
import json

from runner_tool.json_api import get_stage_config, get_stage_config_file_name
from runner_tool.json_api import get_soe, get_soe_file_name
from runner_tool.json_api import is_enable_parachute, is_enable_secondary_parachute
from runner_tool.ballistic_generator import generate_ballistic_config_json_file_path

from runner_tool.solver_control import run_solver

def run_single(solver_config_json_file_name):
    solver_config = json.load(open(solver_config_json_file_name))

    # 減速有無のフラグ
    enable_decent = False

    # パラシュートが有効の場合は弾道計算のために無効版のsolver,stage,sor.jsonを生成
    stage_config = get_stage_config(solver_config, 1)  # 1段のみ対応
    soe = get_soe(stage_config)

    if is_enable_parachute(soe):
        enable_decent = True

        soe['Enable Parachute Open'] = False
        if is_enable_secondary_parachute(soe):
            soe['Enable Secondary Parachute Open'] = False
        
        # soe.json,stage.jsonを別名保存
        soe_file_path_ballistic = generate_ballistic_config_json_file_path(get_soe_file_name(stage_config))
        stage_config['Sequence of Event File Path'] = soe_file_path_ballistic
        
        stage_config_file_path_ballistic = generate_ballistic_config_json_file_path(get_stage_config_file_name(solver_config, 1))
        solver_config['Stage1 Config File List'] = stage_config_file_path_ballistic

        if not os.path.exists(soe_file_path_ballistic):
            with open(soe_file_path_ballistic, 'w') as f:
                json.dump(soe, f, indent=4)
        if not os.path.exists(stage_config_file_path_ballistic):
            with open(stage_config_file_path_ballistic, 'w') as f:
                json.dump(stage_config, f, indent=4)
        
        # Model IDを無効版に変更
        solver_config['Model ID'] = solver_config.get('Model ID') + '_ballistic'
        # jsonを別名保存
        solver_config_file_path_ballistic = generate_ballistic_config_json_file_path(solver_config_json_file_name)
        with open(solver_config_file_path_ballistic, 'w') as f:
            json.dump(solver_config, f, indent=4)


    ## 実行部 ############################################################

    if enable_decent:
        run_solver(solver_config_file_path_ballistic)

    run_solver(solver_config_json_file_name)

    ##############################################################

    
