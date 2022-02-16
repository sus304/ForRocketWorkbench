import os
import glob
import numpy as np
from tqdm import tqdm

from post_tool.post_df import csv2df
from post_tool.post_summary import post_summary
from post_tool.post_ellipse import get_ellipse_points
from post_tool.post_kml import dump_trajectory_kml
from post_tool.post_kml import dump_dispersion_points_kml, dump_dispersion_ellipse_kml

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
#    |- work_dispersion/
#               |- cases/
#                      |- ForRocket.exe
#                      |- *.json
#                      |- *_flight_log.csv
#               |- ellipse_3sigma_impact_point.kml
#               |- ellipse_2sigma_impact_point.kml
#               |- impact_points.kml
#               |- summary.txt
#               |- case_list.csv

def post_dispersion(dispersion_work_dir, dispersion_calc_dir='cases/'):
    os.chdir(dispersion_work_dir)
    os.chdir(dispersion_calc_dir)

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


    # 着水点を抽出して出力
    # TODO: 高度とかの情報もまとめる
    impact_points_latlon = []
    for log_file in tqdm(stage1_log_file_list):
        case_number = log_file.split('_', 1)[0]
        df, _, _ = csv2df(log_file)
        dump_trajectory_kml(df, case_number)  # 軌道kml出力
        _, latlon = post_summary(df, case_number)  # summary出力
        impact_points_latlon.append(latlon)
    ellipse_points_latlon = get_ellipse_points(impact_points_latlon)

    
    if exist_decent:
        ballistic_impact_points_latlon = []
        for log_file in tqdm(stage1_ballistic_log_file_list):
            case_number = log_file.split('_', 1)[0]
            df, _, _ = csv2df(log_file)
            dump_trajectory_kml(df, case_number+'_ballistic')  # 軌道kml出力
            _, latlon = post_summary(df, case_number+'_ballistic')  # summary出力
            ballistic_impact_points_latlon.append(latlon)
        ballistic_ellipse_points_latlon = get_ellipse_points(ballistic_impact_points_latlon)

    # flight_log.csvが重いので削除
    for log_file in log_file_list:
        os.remove(log_file)

    os.chdir('../')  # work_dispersionに戻る

    if exist_decent:
        dump_dispersion_points_kml(impact_points_latlon, 'decent')
        dump_dispersion_ellipse_kml(ellipse_points_latlon, 'decent')

        dump_dispersion_points_kml(ballistic_impact_points_latlon, 'ballistic')
        dump_dispersion_ellipse_kml(ballistic_ellipse_points_latlon, 'ballistic')
    else:
        dump_dispersion_points_kml(impact_points_latlon, 'ballistic')
        dump_dispersion_ellipse_kml(ellipse_points_latlon, 'ballistic')


    os.chdir('../')  # 実行ディレクトリへ


