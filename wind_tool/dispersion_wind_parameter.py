import numpy as np
from scipy import stats

class DispersionWindParameter:
    def __init__(self):
        self.pressure = 0.0
        self.altitude = 0.0
        self.mean_uv = 0.0
        self.mean_u = 0.0
        self.mean_v = 0.0

        self.cov_mat = 0.0
        self.var_u = 0.0
        self.var_v = 0.0
        self.std_u = 0.0
        self.std_v = 0.0
        self.cov_uv = 0.0

        self.corr = 0.0

        self.rv = 0.0

    def create_by_df(self, df_alt):
        self.pressure = df_alt['pressure'].mean()
        self.altitude = df_alt['height'].mean()

        df_uv = df_alt[['u_wind', 'v_wind']]

        self.mean_uv = np.array(df_uv.mean())
        self.mean_u = df_uv.mean()['u_wind']
        self.mean_v = df_uv.mean()['v_wind']

        self.cov_mat = df_uv.cov()
        self.var_u = self.cov_mat['u_wind']['u_wind']
        self.var_v = self.cov_mat['v_wind']['v_wind']
        self.std_u = np.sqrt(self.var_u)
        self.std_v = np.sqrt(self.var_v)
        self.cov_uv = self.cov_mat['u_wind']['v_wind']

        self.corr = self.cov_uv / (self.std_u * self.std_v)

        self.rv = stats.multivariate_normal(self.mean_uv, self.cov_mat)

    def create_by_json(self, json_dict):
        self.pressure = json_dict.get('pressure')
        self.altitude = json_dict.get('altitude')
        u = json_dict.get('u')
        self.mean_u = u.get('mean')
        self.std_u = u.get('standard deviation')
        v = json_dict.get('v')
        self.mean_v = v.get('mean')
        self.std_v = v.get('standard deviation')
        self.corr = json_dict.get('correlation coefficient')

        self.mean_uv = np.array([self.mean_u, self.mean_v])

        self.var_u = self.std_u ** 2
        self.var_v = self.std_v ** 2
        self.cov_uv = self.corr * (self.std_u * self.std_v)
        self.cov_mat = np.array([[self.var_u, self.cov_uv], [self.cov_uv, self.var_v]])

        self.rv = stats.multivariate_normal(self.mean_uv, self.cov_mat)

    def export_to_json(self):
        json_dict = {
            'pressure': self.pressure,
            'altitude': self.altitude,
            'u': {
                'mean': self.mean_u,
                'standard deviation': self.std_u,
            },
            'v': {
                'mean': self.mean_v,
                'standard deviation': self.std_v,
            },
            'correlation coefficient': self.corr
        }
        return json_dict

    def get_wind_average(self):
        return self.mean_uv

    def get_wind_on_ellipse(self, azimuth_deg, p=0.954):
        # azimuthは北から時計回り
        # 楕円計算が東から反時計まわりなので変換
        # 風向と軸の符号が逆になるので180度まわす
        azimuth = azimuth_deg
        if azimuth_deg < 0:
            # 正へ救出
            azimuth = 360.0 - azimuth_deg
        if azimuth_deg >= 360.0:
            azimuth = azimuth_deg - 360.0

        if 0 <= azimuth < 90.0:
            azimuth = 90.0 - azimuth + 180.0
        elif 270.0 < azimuth <= 360.0:
            azimuth = 360.0 - azimuth + 90.0 + 180.0
        else:
            azimuth = 360.0 - azimuth + 90.0 - 180.0
        phi = np.deg2rad(azimuth)

        r = np.sqrt((-2.0 * (1.0 - self.corr**2) * np.log(1.0 - p)) / (1.0 - 2.0 * self.corr * np.sin(phi) * np.cos(phi)))
        u = self.mean_u + self.std_u * r * np.cos(phi)
        v = self.mean_v + self.std_v * r * np.sin(phi)
        return np.array([u, v])

    def get_wind_random(self):
        return stats.multivariate_normal.rvs(self.mean_uv, self.cov_mat)