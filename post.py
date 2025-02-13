import argparse
import os

from post_tool.post_trajectory import post_trajectory
from post_tool.post_area import post_area
from post_tool.post_montecarlo import post_montecarlo
# from post_tool.post_dispersion import post_dispersion

ver_post_tool = '1.0.0'

def get_args():
    argparser = argparse.ArgumentParser(prog='PostTool')

    # argparser.add_argument('-p', '--prefix', help='prefix that post file name', type=str, default='default')

    argparser.add_argument('-c', '--csv-directory', help="solve result directory.", type=str)
    argparser.add_argument('-a', '--area-directory', help="area solve result directory.", type=str)
    argparser.add_argument('-m', '--montecarlo-directory', help="dispersion solve result directory.", type=str)
    # argparser.add_argument('-d', '--dispersion-directory', help="dispersion solve result directory.", type=str)

    argparser.add_argument('-s', '--summary', action="store_true", help='display result summary.')

    argparser.add_argument('-v', '--version', action='version', version='%(prog)s '+ver_post_tool)

    args = argparser.parse_args()
    return args


if __name__ == '__main__':
    args = get_args()

    print('ForRocket Post Start.')

    if args.csv_directory:
        post_trajectory(args.csv_directory)

    if args.area_directory:
        post_area(args.area_directory)

    if args.montecarlo_directory:
        post_montecarlo(args.montecarlo_directory)