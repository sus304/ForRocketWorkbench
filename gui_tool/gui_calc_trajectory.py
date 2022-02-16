import os
import shutil
import datetime
import json

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QFileDialog

from runner_tool.solver_control import print_solver_version_string
from runner_tool.runner_trajectroy import run_trajectroy
from post_tool.post_trajectory import post_trajectory

from path_define import runner_trajectory_directory

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

        # パラシュートが有効なら内部で自動的に両方動く
        run_trajectroy(self.solver_config_json_name)

        print('Post processing ...')

        # Runner&Postが想定しているディレクトリ構成
        # root(work_dir=workspace)/
        #   |- runner_tool/ 
        #   |- post_tool/
        #   |- runner.py
        #   |- post.py
        #   |- ForRocket.exe
        #   |- jsons
        #   |- work_trajectory/
        #   |               |- result_[model name]/たくさんリザルト
        #   |               |- result_[model name ballistic]/たくさんリザルト
        #   |               |- *_flight_log.csv
        #   |- work_area/たくさんリザルト
        #   |- work_dispersion/たくさんリザルト

        post_trajectory(runner_trajectory_directory)

        print('Complete post process.')
        print('Result packing ...')

        result_zip_name ='result_'+model_name+'_trajectory_'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        shutil.make_archive(result_zip_name, 'zip', base_dir=runner_trajectory_directory)

        print('Result: ' + result_zip_name+'.zip')
        print('Complete result packing.')
        
        fname = QFileDialog.getSaveFileName(None, 'Export result files', os.path.expanduser('~') + '/Desktop/'+result_zip_name+'.zip', '*.zip')
        if fname[0]:
            shutil.copy(result_zip_name+'.zip', fname[0])

        print(fname[0])

        print('ALL Complete trajectory.')

        os.chdir('../')

        self.finished.emit()


