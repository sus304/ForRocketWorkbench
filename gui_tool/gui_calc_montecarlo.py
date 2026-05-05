from gui_tool.gui_calc_base import BaseCalcThread
from runner_tool.runner_montecarlo import run_montecarlo
from post_tool.post_montecarlo import post_montecarlo
from path_define import runner_montecarlo_directory


class RunMontecarloThread(BaseCalcThread):
    def __init__(self, work_dir, solver_config_json_name, montecarlo_config_json_name, use_max_thread):
        super().__init__(work_dir, solver_config_json_name)
        self.montecarlo_config_json_name = montecarlo_config_json_name
        self.use_max_thread = use_max_thread

    def _calc_type(self): return 'montecarlo'
    def _result_dir(self): return runner_montecarlo_directory
    def _print_extra_config(self): print('Montecarlo Configuration: ' + self.montecarlo_config_json_name)
    def _run_solver(self): run_montecarlo(self.solver_config_json_name, self.montecarlo_config_json_name, self.use_max_thread)
    def _run_post(self): post_montecarlo(self._result_dir(), max_thread_run=self.use_max_thread)
