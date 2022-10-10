import os
import shutil
import datetime
import json

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QFileDialog

from runner_tool.solver_control import print_solver_version_string
from runner_tool.runner_montecarlo import run_montecarlo
from post_tool.post_montecarlo import post_montecarlo

from path_define import runner_montecarlo_directory

class RunMontecarloThread(QObject):
    finished = pyqtSignal()

    def __init__(self, work_dir, solver_config_json_name, montecarlo_config_json_name, use_max_thread):
        super().__init__()

        self.work_dir = work_dir
        self.solver_config_json_name = solver_config_json_name
        self.montecarlo_config_json_name = montecarlo_config_json_name
        self.use_max_thread = use_max_thread

    def run(self):
        os.chdir(self.work_dir)

        model_name = json.load(open(self.solver_config_json_name, mode='r')).get('Model ID')

        print_solver_version_string()
        print('Model Name: ' + model_name)
        print('Solver Configration: ' + self.solver_config_json_name)
        print('Montecarlo Configration: ' + self.montecarlo_config_json_name)
        print('Runner start ...')

        run_montecarlo(self.solver_config_json_name, self.montecarlo_config_json_name, self.use_max_thread)

        print('Post processing ...')

        # ディレクトリ構成
        # workspace/
        #    |- *.json
        #    |- *.csv
        #    |- ForRocket.exe
        #    |- work_trajectory/
        #    |- work_area/
        #    |- work_montecarlo/
        #               |- cases/
        #                      |- ForRocket.exe
        #                      |- *.json
        #                      |- *_flight_log.csv
        #               |- ellipse_3sigma_impact_point.kml
        #               |- ellipse_2sigma_impact_point.kml
        #               |- impact_points.kml
        #               |- summary.txt

        post_montecarlo(runner_montecarlo_directory, max_thread_run=self.use_max_thread)

        print('Complete post process.')
        print('Result packing ...')

        result_zip_name ='result_'+model_name+'_montecarlo_'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        shutil.make_archive(result_zip_name, 'zip',  base_dir=runner_montecarlo_directory)

        print('Result: ' + result_zip_name+'.zip')
        print('Complete result packing.')

        fname = QFileDialog.getSaveFileName(None, 'Export result files', os.path.expanduser('~') + '/Desktop/'+result_zip_name+'.zip', '*.zip')
        if fname[0]:
            shutil.copy(result_zip_name+'.zip', fname[0])

        print(fname[0])

        print('ALL Complete montecarlo.')

        os.chdir('../')

        self.finished.emit()
