import json
import shutil

from path_define import runner_trajectory_directory, chdir, make_unique_work_dir

from runner_tool.json_api import copy_config_files
from runner_tool.runner_single import run_single
from runner_tool.solver_control import copy_solver_binary, clean_solver_binary


def run_trajectory(solver_config_json_file_name, work_dir=None):
    # work_dir may be pre-created by the caller (the compute service, which needs to know
    # the run's directory at start-up to persist it); default None keeps legacy behaviour.
    if work_dir is None:
        work_dir = make_unique_work_dir(runner_trajectory_directory)

    shutil.copy2(solver_config_json_file_name, work_dir)
    with open(solver_config_json_file_name) as f:
        solver_config = json.load(f)
    if solver_config.get('Wind Condition').get('Enable Wind'):
        shutil.copy2(solver_config.get('Wind Condition').get('Wind File Path'), work_dir)
    copy_config_files(solver_config, work_dir)
    copy_solver_binary(work_dir)

    print('\rCalculating ...', end='')
    with chdir(work_dir):
        run_single(solver_config_json_file_name)
    print('\rComplete calculate.\n', end='')

    print('Work Directory: ' + work_dir)
    clean_solver_binary(work_dir)
