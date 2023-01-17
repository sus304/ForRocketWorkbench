import os
import shutil
import glob

from post_tool.post_df import csv2df
from post_tool.post_summary import post_summary
from post_tool.post_graph import plot_graph
from post_tool.post_kml import dump_trajectory_kml

def post_trajectory(trajectory_work_dir):
    os.chdir(trajectory_work_dir)

    # ディレクトリ内の*_flight_log.csvをリストアップする
    log_file_list = glob.glob('*_flight_log.csv')

    for result_csv_file_name in log_file_list:
        # ポスト処理ファイルを出力するディレクトリを作成
        model_name = os.path.basename(result_csv_file_name).rsplit('_flight_log.csv', 1)[0]
        result_dir = 'result_' + model_name
        os.mkdir(result_dir)

        # Post
        shutil.copy(result_csv_file_name, result_dir)

        df_all, df_burning, df_coasting = csv2df(result_csv_file_name)
        plot_graph(df_all, df_burning, df_coasting, result_dir+'/')
        dump_trajectory_kml(df_all, result_dir+'/')
        summary_txt, _ = post_summary(df_all, result_dir+'/')

    os.chdir('../')

