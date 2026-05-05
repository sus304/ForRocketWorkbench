from gui_tool.gui_calc_base import BaseCalcThread
from runner_tool.runner_area import run_area
from post_tool.post_area import post_area
from path_define import runner_area_directory


class RunAreaThread(BaseCalcThread):
    def __init__(self, work_dir, solver_config_json_name, area_config_json_name, use_max_thread):
        super().__init__(work_dir, solver_config_json_name)
        self.area_config_json_name = area_config_json_name
        self.use_max_thread = use_max_thread

    def _calc_type(self): return 'area'
    def _result_dir(self): return runner_area_directory
    def _print_extra_config(self): print('Wind Configuration: ' + self.area_config_json_name)
    def _run_solver(self): run_area(self.solver_config_json_name, self.area_config_json_name, self.use_max_thread)
    def _run_post(self): post_area(self._result_dir())
