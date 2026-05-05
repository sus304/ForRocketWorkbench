import os
import shutil
import glob

from post_tool.post_df import csv2df
from post_tool.post_summary import post_summary
from post_tool.post_graph import plot_graph
from post_tool.post_kml import dump_trajectory_kml

from path_define import chdir


def post_trajectory(trajectory_work_dir):
    with chdir(trajectory_work_dir):
        log_file_list = glob.glob('*_flight_log.csv')

        for result_csv_file_name in log_file_list:
            model_name = result_csv_file_name.rsplit('_flight_log.csv', 1)[0]
            result_dir = 'result_' + model_name
            os.mkdir(result_dir)

            shutil.copy(result_csv_file_name, result_dir)
            df_all, df_burning, df_coasting = csv2df(result_csv_file_name)
            plot_graph(df_all, df_burning, df_coasting, result_dir + '/')
            dump_trajectory_kml(df_all, result_dir + '/')
            post_summary(df_all, result_dir + '/')
