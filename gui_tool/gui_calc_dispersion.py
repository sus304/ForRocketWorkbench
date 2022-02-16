import os
import shutil
import datetime
import json

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QFileDialog

from runner_tool.solver_control import print_solver_version_string
from runner_tool.runner_dispersion import run_dispersion
from post_tool.post_dispersion import post_dispersion

from path_define import runner_dispersion_directory

class RunDispersionThread(QObject):
    finished = pyqtSignal()

    def __init__(self, work_dir, solver_config_json_name, dispersion_config_json_name, use_max_thread):
        super().__init__()

        self.work_dir = work_dir
        self.solver_config_json_name = solver_config_json_name
        self.dispersion_config_json_name = dispersion_config_json_name
        self.use_max_thread = use_max_thread

    def run(self):
        os.chdir(self.work_dir)

        model_name = json.load(open(self.solver_config_json_name, mode='r')).get('Model ID')

        print_solver_version_string()
        print('Model Name: ' + model_name)
        print('Solver Configration: ' + self.solver_config_json_name)
        print('Dispersion Configration: ' + self.dispersion_config_json_name)
        print('Runner start ...')

        run_dispersion(self.solver_config_json_name, self.dispersion_config_json_name, self.use_max_thread)

        print('Post processing ...')

        # ディレクトリ構成
        # workspace/
        #    |- *.json
        #    |- *.csv
        #    |- ForRocket.exe
        #    |- work_trajectory/
        #    |- work_area/
        #    |- work_dispersion/
        #               |- cases/
        #                      |- ForRocket.exe
        #                      |- *.json
        #                      |- *_flight_log.csv
        #               |- ellipse_3sigma_impact_point.kml
        #               |- ellipse_2sigma_impact_point.kml
        #               |- impact_points.kml
        #               |- summary.txt

        post_dispersion(runner_dispersion_directory)

        print('Complete post process.')
        print('Result packing ...')

        result_zip_name ='result_'+model_name+'_dispersion_'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        shutil.make_archive(result_zip_name, 'zip',  base_dir=runner_dispersion_directory)
        
        print('Result: ' + result_zip_name+'.zip')
        print('Complete result packing.')
        
        fname = QFileDialog.getSaveFileName(None, 'Export result files', os.path.expanduser('~') + '/Desktop/'+result_zip_name+'.zip', '*.zip')
        if fname[0]:
            shutil.copy(result_zip_name+'.zip', fname[0])
        
        print(fname[0])

        print('ALL Complete dispersion.')

        os.chdir('../')

        self.finished.emit()
