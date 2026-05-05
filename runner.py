import argparse
import os

from runner_tool.runner_trajectory import run_trajectory
from runner_tool.runner_area import run_area
from runner_tool.runner_montecarlo import run_montecarlo
from runner_tool.runner_sensitivity import run_sensitivity
from post_tool.post_sensitivity import post_sensitivity

ver_runner_tool = '1.1.0'

def get_args():
    argparser = argparse.ArgumentParser(prog='RunnerTool')

    argparser.add_argument('-s', '--solver-config-json', help="Solver config json file name", type=str, required=True)

    argparser.add_argument('-a', '--area-config-json', help="Area config json file name", type=str)
    argparser.add_argument('-m', '--montecarlo-config-json', help="Montecarlo config json file name", type=str)
    argparser.add_argument('-e', '--sensitivity-config-json', help="Sensitivity analysis config json file name", type=str)

    argparser.add_argument('-X', '--use-max-thread', action='store_true', help='Using max cpu thread in area and montecarlo calculate')

    argparser.add_argument('-v', '--version', action='version', version='%(prog)s '+ver_runner_tool)

    args = argparser.parse_args()
    return args


if __name__ == '__main__':
    args = get_args()

    print('ForRocket Runner Start.')

    if args.montecarlo_config_json:
        print('== Impact Point Montecarlo Simulation Mode ==')
        print(os.path.basename(args.solver_config_json), os.path.basename(args.montecarlo_config_json))
        run_montecarlo(os.path.basename(args.solver_config_json), os.path.basename(args.montecarlo_config_json), args.use_max_thread)
    elif args.area_config_json:
        print('== Impact Point Area Calcuration Mode ==')
        run_area(os.path.basename(args.solver_config_json), os.path.basename(args.area_config_json), args.use_max_thread)
    elif args.sensitivity_config_json:
        print('== Sensitivity Analysis Mode ==')
        print(os.path.basename(args.solver_config_json), os.path.basename(args.sensitivity_config_json))
        work_dir = run_sensitivity(os.path.basename(args.solver_config_json), os.path.basename(args.sensitivity_config_json), args.use_max_thread)
        post_sensitivity(work_dir)
    else:
        print('== Trajectory Calculation Mode ==')
        run_trajectory(os.path.basename(args.solver_config_json))


