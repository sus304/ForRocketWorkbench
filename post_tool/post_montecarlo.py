import os
import glob
import numpy as np
from tqdm import tqdm

import multiprocessing
from multiprocessing import Pool

from post_tool.post_df import csv2df
from post_tool.post_summary import post_summary_for_montecarlo, post_3sigma_summary
from post_tool.post_ellipse import get_ellipse_points
from post_tool.post_kml import dump_trajectory_kml
from post_tool.post_kml import dump_montecarlo_points_kml, dump_montecarlo_envelop_kml

# ディレクトリ構成
# root/
#    |- runner_tool/
#    |- post_tool/
#    |- runner.py
#    |- post.py
#    |- *.json
#    |- *.csv
#    |- work_trajectory/
#    |- work_area/
#    |- work_montecarlo/
#               |- cases/
#                      |- *.json
#                      |- *_flight_log.csv
#                      |- *_summary.txt
#                      |- *_trajectory.kml
#               |- impact_3sigma_envelop.kml
#               |- impact_points.kml
#               |- summary.txt
#               |- case_result_table.csv

def _3sigma_impact_ellipse(latlons):
    pass

def post_montecarlo(montecarlo_work_dir, montecarlo_calc_dir='cases/', max_thread_run=False):
    os.chdir(montecarlo_work_dir)
    os.chdir(montecarlo_calc_dir)

    # ディレクトリ内の*_flight_log.csvをリストアップする
    log_file_list = glob.glob('*_flight_log.csv')

    exist_decent = False

    # stage毎に振り分け
    # 弾道と減速を振り分け
    # Stage1のみ対応
    stage1_log_file_list = []
    stage1_ballistic_log_file_list = []
    stage2_log_file_list = []
    stage3_log_file_list = []
    for file in tqdm(log_file_list):
        if '_stage1_' in file:
            if '_ballistic_' in file:
                stage1_ballistic_log_file_list.append(file)
            else:
                stage1_log_file_list.append(file)
        elif '_stage2_' in file:
            stage2_log_file_list.append(file)
        elif '_stage3_' in file:
            stage3_log_file_list.append(file)
    # stage1_log_file_list
    # stage1_ballistic_log_file_list
    if len(stage1_ballistic_log_file_list) > 0:
        exist_decent = True


    # 着水点、高度を抽出して出力
    case_number_list = []
    maxQ_Q_list = []
    max_mach_list = []
    time_apogee_list = []
    altitude_list = []
    vel_apogee_list = []
    impact_points_latlon = []
    downrange_impact_list = []
    for log_file in tqdm(stage1_log_file_list):
        case_number = log_file.split('_', 1)[0]
        df, _, _ = csv2df(log_file)
        dump_trajectory_kml(df, case_number)  # 軌道kml出力
        dynamic_pressure_maxq, mach_maxmach, time_apogee, altitude_apogee, vel_apogee, latlon_landing, downrange_landing = post_summary_for_montecarlo(df, case_number)  # summary出力
        case_number_list.append(int(case_number))
        maxQ_Q_list.append(dynamic_pressure_maxq)
        max_mach_list.append(mach_maxmach)
        time_apogee_list.append(time_apogee)
        altitude_list.append(altitude_apogee)
        vel_apogee_list.append(vel_apogee)
        impact_points_latlon.append(latlon_landing)
        downrange_impact_list.append(downrange_landing)


    if exist_decent:
        ballistic_case_number_list = []
        ballistic_maxQ_Q_list = []
        ballistic_max_mach_list = []
        ballistic_time_apogee_list = []
        ballistic_altitude_list = []
        ballistic_vel_apogee_list = []
        ballistic_impact_points_latlon = []
        ballistic_downrange_impact_list = []
        for log_file in tqdm(stage1_ballistic_log_file_list):
            case_number = log_file.split('_', 1)[0]
            df, _, _ = csv2df(log_file)
            dump_trajectory_kml(df, case_number+'_ballistic')  # 軌道kml出力
            dynamic_pressure_maxq, mach_maxmach, time_apogee, altitude_apogee, vel_apogee, latlon_landing, downrange_landing = post_summary_for_montecarlo(df, case_number+'_ballistic')  # summary出力
            ballistic_case_number_list.append(int(case_number))
            ballistic_maxQ_Q_list.append(dynamic_pressure_maxq)
            ballistic_max_mach_list.append(mach_maxmach)
            ballistic_time_apogee_list.append(time_apogee)
            ballistic_altitude_list.append(altitude_apogee)
            ballistic_vel_apogee_list.append(vel_apogee)
            ballistic_impact_points_latlon.append(latlon_landing)
            ballistic_downrange_impact_list.append(downrange_landing)

    # flight_log.csvが重いので削除
    # for log_file in log_file_list:
        # os.remove(log_file)

    os.chdir('../')  # work_montecarloに戻る


    if exist_decent:
        # impact_3sigma_envelop.kml
        envelope_point_llh, ellipse_llh = get_ellipse_points(impact_points_latlon)
        dump_montecarlo_envelop_kml(envelope_point_llh, 'decent')
        dump_montecarlo_envelop_kml(ellipse_llh, 'decent_ellipse')
        ballistic_envelope_point_llh, ballistic_ellipse_llh = get_ellipse_points(ballistic_impact_points_latlon)
        dump_montecarlo_envelop_kml(ballistic_envelope_point_llh, 'ballistic')
        dump_montecarlo_envelop_kml(ballistic_ellipse_llh, 'ballistic_ellipse')

        # impact_points.kml
        dump_montecarlo_points_kml(impact_points_latlon, case_number_list, 'decent')
        dump_montecarlo_points_kml(ballistic_impact_points_latlon, ballistic_case_number_list, 'ballistic')

        # case_result_table.csv
        lat_list = []
        lon_list = []
        for i in range(len(case_number_list)):
            lat_list.append(impact_points_latlon[i][0])
            lon_list.append(impact_points_latlon[i][1])
        output = np.c_[case_number_list, maxQ_Q_list, max_mach_list, time_apogee_list, altitude_list, vel_apogee_list, downrange_impact_list, lat_list, lon_list]
        header_str = 'case,maxQ,mach,time_apogee,altitude_apogee,vel_apogee,downrange_impact,lat_impact,lon_impact'
        np.savetxt('decent_result_table.csv', output, fmt=['%d', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f'], delimiter=',', header=header_str, comments='')
        lat_list = []
        lon_list = []
        for i in range(len(case_number_list)):
            lat_list.append(ballistic_impact_points_latlon[i][0])
            lon_list.append(ballistic_impact_points_latlon[i][1])
        output = np.c_[ballistic_case_number_list, ballistic_maxQ_Q_list, ballistic_max_mach_list, ballistic_time_apogee_list, ballistic_altitude_list, ballistic_vel_apogee_list, ballistic_downrange_impact_list, lat_list, lon_list]
        header_str = 'case,maxQ,mach,time_apogee,altitude_apogee,vel_apogee,downrange_impact,lat_impact,lon_impact'
        np.savetxt('ballistic_result_table.csv', output, fmt=['%d', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f'], delimiter=',', header=header_str, comments='')

        # summary.txt
        post_3sigma_summary(case_number_list, maxQ_Q_list, max_mach_list, time_apogee_list, altitude_list, vel_apogee_list, downrange_impact_list, 'decent')
        post_3sigma_summary(ballistic_case_number_list, ballistic_maxQ_Q_list, ballistic_max_mach_list, ballistic_time_apogee_list, ballistic_altitude_list, ballistic_vel_apogee_list, ballistic_downrange_impact_list, 'ballistic')
    else:
        # impact_3sigma_envelop.kml
        envelope_point_llh, ellipse_llh = get_ellipse_points(impact_points_latlon)
        dump_montecarlo_envelop_kml(envelope_point_llh, '')
        dump_montecarlo_envelop_kml(ellipse_llh, 'ellipse')

        # impact_points.kml
        dump_montecarlo_points_kml(impact_points_latlon, case_number_list, '')

        # case_result_table.csv
        lat_list = []
        lon_list = []
        for i in range(len(case_number_list)):
            lat_list.append(impact_points_latlon[i][0])
            lon_list.append(impact_points_latlon[i][1])
        output = np.c_[case_number_list, maxQ_Q_list, max_mach_list, time_apogee_list, altitude_list, vel_apogee_list, downrange_impact_list, lat_list, lon_list]
        header_str = 'case,maxQ,mach,time_apogee,altitude_apogee,vel_apogee,downrange_impact,lat_impact,lon_impact'
        np.savetxt('result_table.csv', output, fmt=['%d', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f', '%0.6f'], delimiter=',', header=header_str, comments='')

        # summary.txt
        post_3sigma_summary(case_number_list, maxQ_Q_list, max_mach_list, time_apogee_list, altitude_list, vel_apogee_list, downrange_impact_list, '')


    os.chdir('../')  # 実行ディレクトリへ


