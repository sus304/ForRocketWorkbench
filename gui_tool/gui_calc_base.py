import os
import shutil
import datetime
import json

from PyQt5.QtCore import QObject, pyqtSignal

from runner_tool.solver_control import print_solver_version_string, cancel_current_solver
from path_define import chdir


class _CalcCancelled(Exception):
    pass


class BaseCalcThread(QObject):
    finished = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, work_dir, solver_config_json_name):
        super().__init__()
        self.work_dir = work_dir
        self.solver_config_json_name = solver_config_json_name
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True
        cancel_current_solver()

    def _check_cancel(self):
        if self._cancel_requested:
            raise _CalcCancelled()

    def _calc_type(self):
        raise NotImplementedError

    def _result_dir(self):
        raise NotImplementedError

    def _run_solver(self):
        raise NotImplementedError

    def _run_post(self):
        raise NotImplementedError

    def _print_extra_config(self):
        pass

    def run(self):
        result_zip_path = ''
        try:
            with chdir(self.work_dir):
                with open(self.solver_config_json_name) as f:
                    model_name = json.load(f).get('Model ID')

                print_solver_version_string()
                print('Model Name: ' + model_name)
                print('Solver Configuration: ' + self.solver_config_json_name)
                self._print_extra_config()

                self._check_cancel()
                self.progress.emit(10, 'Running solver ...')
                print('Runner start ...')
                self._run_solver()

                self._check_cancel()
                self.progress.emit(60, 'Post processing ...')
                print('Post processing ...')
                self._run_post()
                print('Complete post process.')

                self._check_cancel()
                self.progress.emit(85, 'Packing results ...')
                print('Result packing ...')
                result_zip_name = (
                    'result_' + model_name + '_' + self._calc_type() + '_'
                    + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                )
                shutil.make_archive(result_zip_name, 'zip', base_dir=self._result_dir())
                result_zip_path = os.path.abspath(result_zip_name + '.zip')
                print('Result: ' + result_zip_name + '.zip')
                print('Complete result packing.')

        except _CalcCancelled:
            print('Calculation cancelled.')
            self.progress.emit(0, 'Cancelled')
            self.finished.emit('')
            return

        self.progress.emit(100, 'Complete')
        print('ALL Complete ' + self._calc_type() + '.')
        self.finished.emit(result_zip_path)
