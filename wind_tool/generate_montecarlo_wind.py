import numpy as np
import pandas as pd
from scipy.stats import multivariate_normal
from scipy.spatial import distance


def generate_montecarlo_2sigma_winds(base_wind_csv_path, diff_wind_csv_path, num_case):
    '''
    ベース風に予報/実績差の2sigmaを足し合わせて、モンテカルロ用にnum_case個の2sigma予報/実績差風を生成する
    '''
    df_base = pd.read_csv(base_wind_csv_path)

    alt_array = df_base['alt'].to_list()
    u_base_array = df_base['u_mean']
    v_base_array = df_base['v_mean']

    df_diff = pd.read_csv(diff_wind_csv_path)

    du_mean_array = df_diff['du_mean']
    dv_mean_array = df_diff['dv_mean']
    du_var_array = df_diff['du_sigma2']
    dv_var_array = df_diff['dv_sigma2']
    duv_var_array = df_diff['duv_sigma2']
    du_std_array = np.sqrt(du_var_array)
    dv_std_array = np.sqrt(dv_var_array)

    alt_case_list = []
    u_case_list = []
    v_case_list = []

    for i_case in range(num_case):
        u_case_array = np.copy(u_base_array)
        v_case_array = np.copy(v_base_array)

        if num_case > 0:
            for i in range(len(alt_array)):
                covariance = [[0,0],[0,0]]
                covariance[0][0] = du_var_array[i]
                covariance[1][1] = dv_var_array[i]
                covariance[0][1] = duv_var_array[i]
                covariance[1][0] = duv_var_array[i]

                dudv = [0, 0]
                md = 999
                while True:
                    # ランダム[du, dv]
                    dudv = multivariate_normal.rvs(mean=[du_mean_array[i], dv_mean_array[i]], cov=covariance)

                    cov_i = np.linalg.pinv(covariance)
                    md = distance.mahalanobis([du_mean_array[i], dv_mean_array[i]], dudv, cov_i)
                    if md <= 2:  # 2sigma 以上は棄却
                        break
                u_case_array[i] += dudv[0]
                v_case_array[i] += dudv[1]

        alt_case_list.append(alt_array)
        u_case_list.append(u_case_array)
        v_case_list.append(v_case_array)

    return alt_case_list, u_case_list, v_case_list





if __name__ == '__main__':
    mean_csv_path = 'C:/cygwin64/home/sus304/ForRocketProject/wind/WindGPV/MSM/statistic/noshiro_sea2sea_2017-2021y_9-10m_9-15h/wind_statistic_data.csv'
    est_act_diff_csv_path = 'C:/cygwin64/home/sus304/ForRocketProject/wind/WindGPV/MSM/statistic/noshiro_sea2sea_2017-2021y_9-10m_9-15h/wind_estimate_error_12h.csv'

    generate_montecarlo_2sigma_winds(mean_csv_path, est_act_diff_csv_path, 10000)









