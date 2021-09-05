import os

from numpy import result_type
from runner_tool.runner_trajectroy import run_trajectroy
import shutil
import datetime
import json

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QFileDialog

from runner_tool.runner_solver import print_solver_version_string
from runner_tool.runner_area import run_area
from post_tool.post_area import post_area

class RunAreaThread(QObject):
    finished = pyqtSignal()

    def __init__(self, work_dir, solver_config_json_name, area_config_json_name, use_max_thread):
        super().__init__()

        self.work_dir = work_dir
        self.solver_config_json_name = solver_config_json_name
        self.area_config_json_name = area_config_json_name
        self.use_max_thread = use_max_thread

    def run(self):
        # runner start
        os.chdir(self.work_dir)

        model_name = json.load(open(self.solver_config_json_name, mode='r')).get('Model ID')

        print_solver_version_string()
        print('Model Name: ' + model_name)
        print('Solver Configration: ' + self.solver_config_json_name)
        print('Wind Configration: ' + self.area_config_json_name)
        print('Runner start ...')

        run_area(self.solver_config_json_name, self.area_config_json_name, self.use_max_thread)

        print('Post processing ...')

        result_dir = 'work_area'
        post_area(result_dir)

        print('Complete post process.')
        print('Result packing ...')

        os.remove(result_dir+'/ForRocket.exe')
        result_zip_name ='result_'+model_name+'_area_'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        shutil.make_archive(result_zip_name, 'zip',  base_dir=result_dir)
        print('Result: ' + result_zip_name+'.zip')
        print('Complete result packing.')
        
        fname = QFileDialog.getSaveFileName(None, 'Export result files', os.path.expanduser('~') + '/Desktop/'+result_zip_name+'.zip', '*.zip')
        if fname[0]:
            shutil.copy(result_zip_name+'.zip', fname[0])
        
        print(fname[0])

        print('ALL Complete area.')

        os.chdir('../')

        self.finished.emit()



