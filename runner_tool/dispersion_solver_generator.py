
from runner_tool.json_api import get_azimuth, set_azimuth
from runner_tool.json_api import get_elevation, set_elevation

from runner_tool.dispersion_error_item import ErrorSourceItem

class SolverDispersionConfig:
    def __init__(self, solver_dispersion_param):
        self.azimuth = ErrorSourceItem(solver_dispersion_param, 'Azimuth [deg]')
        self.elevation = ErrorSourceItem(solver_dispersion_param, 'Elevation [deg]')

    def is_enable_dispersion():
        # 風は無条件で有効にしているのでsolverも有効
        return True

    def generate_json_dict(self, solver):
        if self.azimuth.is_enable():
            azi = self.azimuth.get_random_value(get_azimuth(solver))
            solver = set_azimuth(solver, azi)
        
        if self.elevation.is_enable():
            elv = self.elevation.get_random_value(get_elevation(solver))
            solver = set_elevation(solver, elv)
        
        return solver



