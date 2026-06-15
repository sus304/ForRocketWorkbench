import argparse
import os

from post_tool.post_trajectory import post_trajectory
from post_tool.post_area import post_area
from post_tool.post_montecarlo import post_montecarlo

ver_post_tool = '1.1.0'

def get_args():
    argparser = argparse.ArgumentParser(prog='PostTool')

    # argparser.add_argument('-p', '--prefix', help='prefix that post file name', type=str, default='default')

    argparser.add_argument('-c', '--csv-directory', help="solve result directory.", type=str)
    argparser.add_argument('-a', '--area-directory', help="area solve result directory.", type=str)
    argparser.add_argument('-m', '--montecarlo-directory', help="montecarlo solve result directory.", type=str)

    argparser.add_argument('-s', '--summary', action="store_true", help='display result summary.')

    argparser.add_argument('--iip', choices=['auto', 'on', 'off'], default='auto',
                           help='IIP calc: auto=apogee-gated (default), on/off=force.')
    argparser.add_argument('--iip-min-altitude', type=float, default=None,
                           help='apogee threshold [km] for IIP auto-gate (default 10).')

    argparser.add_argument('-v', '--version', action='version', version='%(prog)s '+ver_post_tool)

    args = argparser.parse_args()
    return args


if __name__ == '__main__':
    args = get_args()

    print('ForRocket Post Start.')

    iip = {'auto': None, 'on': True, 'off': False}[args.iip]
    iip_kwargs = {'iip': iip}
    if args.iip_min_altitude is not None:
        iip_kwargs['iip_min_apogee'] = args.iip_min_altitude * 1000.0

    if args.csv_directory:
        post_trajectory(args.csv_directory, **iip_kwargs)

    if args.area_directory:
        post_area(args.area_directory)

    if args.montecarlo_directory:
        post_montecarlo(args.montecarlo_directory, **iip_kwargs)