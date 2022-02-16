import numpy as np

from runner_tool.json_api import _file_copy_by_param
from runner_tool.json_api import thrust_file_is_enable
from runner_tool.json_api import get_thrust_file_name, set_thrust_file_name
from runner_tool.json_api import get_constant_thrust, set_constant_thrust
from runner_tool.json_api import get_engine_miss_alignment_y, get_engine_miss_alignment_z
from runner_tool.json_api import set_engine_miss_alignment_y, set_engine_miss_alignment_z

from runner_tool.dispersion_error_item import ErrorSourceItem

class EngineDispersionConfig:
    def __init__(self, engine_dispersion_param):
        self.thrust = ErrorSourceItem(engine_dispersion_param, 'Thrust [N]')
        self.miss_alignment_y = ErrorSourceItem(engine_dispersion_param, 'Engine Miss-Alignment y-Axis Angle [deg]')
        self.miss_alignment_z = ErrorSourceItem(engine_dispersion_param, 'Engine Miss-Alignment z-Axis Angle [deg]')

    def is_enable_dispersion(self):
        return True
        # 必要なcsvをコピーするために無条件True
        # if self.thrust.is_enable(): return True
        # if self.miss_alignment_y.is_enable(): return True
        # if self.miss_alignment_z.is_enable(): return True

    def generate_json_dict(self, engine_param, dst_dir, case_num):
        if self.thrust.is_enable():
            if thrust_file_is_enable(engine_param):
                load_array = np.loadtxt(get_thrust_file_name(engine_param), delimiter=',', skiprows=1)
                f_array = self.thrust.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], f_array, load_array[:,2]]
                save_csv_name = str(case_num)+'_'+get_thrust_file_name(engine_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,F,mdot', comments='')
                engine_param = set_thrust_file_name(engine_param, save_csv_name)
            else:
                f = self.thrust.get_random_value(get_constant_thrust(engine_param))
                engine_param = set_constant_thrust(engine_param, f)
        else:
            _file_copy_by_param(engine_param, 'Enable Thrust File', 'Thrust File', 'Thrust at vacuum File Path', dst_dir)
            

        if self.miss_alignment_y.is_enable():
            y = self.miss_alignment_y.get_random_value(get_engine_miss_alignment_y(engine_param))
            engine_param = set_engine_miss_alignment_y(engine_param, y)
        
        if self.miss_alignment_z.is_enable():
            z = self.miss_alignment_z.get_random_value(get_engine_miss_alignment_z(engine_param))
            engine_param = set_engine_miss_alignment_z(engine_param, z)

        return engine_param


