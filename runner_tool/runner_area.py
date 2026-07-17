import os
import json
import numpy as np

from path_define import runner_area_directory, make_unique_work_dir

from runner_tool.json_api import copy_config_files
from runner_tool.runner_multi import run_multi

from runner_tool.area_wind_generator import AreaWindGenerator
from runner_tool.law_wind import make_law_wind


class AreaCaseConfig:
    def __init__(self, num, wind_speed, wind_direction, solver_config_file_name):
        self.case_num = num
        self.wind_speed = wind_speed
        self.wind_direction = wind_direction
        self.solver_config_file_name = solver_config_file_name


def run_area(solver_config_json_file_name, area_config_json_file_name, max_thread_run=False, work_dir=None):
    # work_dir may be pre-created by the compute service (see run_trajectory); default self-creates.
    if work_dir is None:
        work_dir = make_unique_work_dir(runner_area_directory)

    with open(area_config_json_file_name) as f:
        area_config = json.load(f)
    wind_config = AreaWindGenerator(area_config)

    with open(solver_config_json_file_name) as f:
        solver_config = json.load(f)
    model_id_original = solver_config.get('Model ID')

    wind_case_list = []
    case_num = 0
    for i_vel in range(len(wind_config.wind_speed_array)):
        for j_dir in range(len(wind_config.wind_direction_array)):
            alt_array, u_array, v_array = make_law_wind(
                wind_config.height_wind_reference,
                wind_config.wind_speed_array[i_vel],
                wind_config.wind_direction_array[j_dir],
                wind_config.wind_exponatial,
            )
            wind_file_name = 'wind_' + str(case_num) + '.csv'
            np.savetxt(work_dir + '/' + wind_file_name,
                       np.c_[alt_array, u_array, v_array],
                       delimiter=',', header='alt[m],u[m/s],v[m/s]', fmt='%0.4f', comments='')

            solver_config['Model ID'] = model_id_original + '_wind' + str(case_num)
            solver_config['Wind Condition']['Enable Wind'] = True
            solver_config['Wind Condition']['Wind File Path'] = wind_file_name
            sep = solver_config_json_file_name.rsplit('.json', 1)
            case_solver_config_file_name = sep[0] + '_' + str(case_num) + '.json'
            with open(work_dir + '/' + case_solver_config_file_name, 'w') as f:
                json.dump(solver_config, f, indent=4)

            case = AreaCaseConfig(case_num, wind_config.wind_speed_array[i_vel],
                                  wind_config.wind_direction_array[j_dir],
                                  case_solver_config_file_name)
            wind_case_list.append(case)
            case_num += 1

    copy_config_files(solver_config, work_dir)

    case_data = np.c_[
        [c.case_num for c in wind_case_list],
        [c.wind_speed for c in wind_case_list],
        [c.wind_direction for c in wind_case_list],
    ]
    np.savetxt(work_dir + '/wind_case_list.csv', case_data,
               delimiter=',', header='case,speed[m/s],direction[deg]',
               fmt=['%d', '%0.4f', '%0.4f'], comments='')

    case_solver_config_file_name_list = [c.solver_config_file_name for c in wind_case_list]

    work_dir_abs = os.path.abspath(work_dir)
    run_multi(work_dir_abs, case_solver_config_file_name_list, max_thread_run)

    print('Work Directory: ' + work_dir)
