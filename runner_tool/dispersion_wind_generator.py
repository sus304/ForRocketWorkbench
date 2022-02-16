import numpy as np

from wind_tool.dispersion_wind_parameter import DispersionWindParameter

class WindDispersionConfig:
    def __init__(self, wind_dispersion_param_json):
        # disp_wind.jsonの読み出し
        wind_count = wind_dispersion_param_json.get('item count')

        # Parameterクラスリストを作成
        self.dsp_wind_param_list = []
        for i in range(wind_count):
            wind_at_height_json = wind_dispersion_param_json.get(str(i))
            dsp_wind_param = DispersionWindParameter()
            dsp_wind_param.create_by_json(wind_at_height_json)
            self.dsp_wind_param_list.append(dsp_wind_param)

    def generate_wind_file(self, dst_dir, case_num):
        wind_list = []
        for i in range(len(self.dsp_wind_param_list)):
            random_wind = self.dsp_wind_param_list[i].get_wind_random()
            wind_at_height = [self.dsp_wind_param_list[i].altitude, random_wind[0], random_wind[1]]
            wind_list.append(wind_at_height)

        wind_file_name = str(case_num)+'_wind.csv'
        np.savetxt(dst_dir+wind_file_name, np.array(wind_list), delimiter=',', fmt='%0.5f', header='alt,u,v', comments='')
        return wind_file_name

        