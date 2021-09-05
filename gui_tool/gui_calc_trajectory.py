import os
import shutil
import datetime
import json
import glob

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QFileDialog

from runner_tool.ballistic_generator import generate_ballistic_config_json_file_path
from runner_tool.runner_solver import print_solver_version_string
from runner_tool.runner_trajectroy import run_trajectroy
from post_tool.post_trajectory import post_trajectory

class RunTrajectoryThread(QObject):
    finished = pyqtSignal()

    def __init__(self, work_dir, solver_config_json_name):
        super().__init__()

        self.work_dir = work_dir
        self.solver_config_json_name = solver_config_json_name


    def run(self):
        # runner start
        os.chdir(self.work_dir)

        model_name = json.load(open(self.solver_config_json_name, mode='r')).get('Model ID')

        print_solver_version_string()
        print('Model Name: ' + model_name)
        print('Solver Configration: ' + self.solver_config_json_name)
        print('Calculating ...')

        # パラシュートが有効なら内部で自動的に両方動く
        run_trajectroy(self.solver_config_json_name)

        print('Complete calculate.')
        print('Post processing ...')
        
        # ディレクトリ内の*_flight_log.csvをリストアップする
        log_file_list = glob.glob('*_flight_log.csv')
        if len(log_file_list) > 1:
            result_dir = 'results'
            os.mkdir(result_dir)
            for file in log_file_list:
                result_dir_t = post_trajectory(file)
                case_name = file.rsplit('_flight_log.csv', 1)[0]
                shutil.make_archive(case_name, 'zip', base_dir=result_dir_t)
                shutil.copy(case_name+'.zip', result_dir)
        else:
            result_dir = post_trajectory(log_file_list[0])

        print('Complete post process.')
        print('Result packing ...')

        result_zip_name ='result_'+model_name+'_trajectory_'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        shutil.make_archive(result_zip_name, 'zip', base_dir=result_dir)
        print('Result: ' + result_zip_name+'.zip')
        print('Complete result packing.')
        
        fname = QFileDialog.getSaveFileName(None, 'Export result files', os.path.expanduser('~') + '/Desktop/'+result_zip_name+'.zip', '*.zip')
        if fname[0]:
            shutil.copy(result_zip_name+'.zip', fname[0])

        print(fname[0])

        print('ALL Complete trajectory.')

        os.chdir('../')

        self.finished.emit()


