from gui_tool.gui_calc_base import BaseCalcThread
from runner_tool.runner_trajectory import run_trajectory
from post_tool.post_trajectory import post_trajectory
from path_define import runner_trajectory_directory


class RunTrajectoryThread(BaseCalcThread):
    def _calc_type(self): return 'trajectory'
    def _result_dir(self): return runner_trajectory_directory
    def _run_solver(self): run_trajectory(self.solver_config_json_name)
    def _run_post(self): post_trajectory(self._result_dir())
