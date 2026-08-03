import argparse
import os
import signal
import threading
import time

from runner_tool.runner_trajectory import run_trajectory
from runner_tool.runner_area import run_area
from runner_tool.runner_montecarlo import run_montecarlo, resume_montecarlo
from runner_tool.runner_sensitivity import run_sensitivity
from post_tool.post_sensitivity import post_sensitivity
from version import workbench_version

# The runner no longer carries a version of its own: it ships with the Workbench and is only ever
# run from this tree, so a separate hand-maintained number could only ever drift (see version.py).
ver_runner_tool = workbench_version()

def _install_graceful_stop():
    """Install a SIGINT (Ctrl-C) handler for the long montecarlo modes.

    First Ctrl-C requests a graceful pause: in-flight cases finish, no new ones start,
    and the run exits cleanly so it can be resumed later. A second Ctrl-C restores the
    default handler for an immediate hard abort. Returns the threading.Event to pass to
    the runner. Main-thread only (CLI); the GUI never calls this.
    """
    stop_event = threading.Event()

    def _handler(signum, frame):
        if not stop_event.is_set():
            print('\nPause requested: finishing in-flight cases, then stopping. '
                  'Press Ctrl-C again to abort immediately.')
            stop_event.set()
        else:
            signal.signal(signal.SIGINT, signal.SIG_DFL)

    signal.signal(signal.SIGINT, _handler)
    return stop_event


def _watch_stop_flag(flag_path, stop_event, poll_sec=1.0):
    """Set stop_event when a stop-flag file appears at flag_path.

    Lets a parent process (e.g. the web service) request a graceful pause in a
    cross-platform way: signals are unreliable for subprocesses on Windows, but a
    sentinel file works everywhere. Runs in a daemon thread; polling is cheap relative
    to the tens-of-seconds-per-case solver cadence.
    """
    def _poll():
        while not stop_event.is_set():
            if os.path.exists(flag_path):
                print('\nPause requested via stop flag: finishing in-flight cases, then stopping.')
                stop_event.set()
                return
            time.sleep(poll_sec)

    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    return t


def get_args():
    argparser = argparse.ArgumentParser(prog='RunnerTool')

    argparser.add_argument('-s', '--solver-config-json', help="Solver config json file name", type=str, required=True)

    argparser.add_argument('-a', '--area-config-json', help="Area config json file name", type=str)
    argparser.add_argument('-m', '--montecarlo-config-json', help="Montecarlo config json file name", type=str)
    argparser.add_argument('-e', '--sensitivity-config-json', help="Sensitivity analysis config json file name", type=str)

    argparser.add_argument('-X', '--use-max-thread', action='store_true', help='Use all logical (SMT) threads instead of the default (physical core count) for area/montecarlo/sensitivity')

    argparser.add_argument('-r', '--resume-work-dir', help="Resume an interrupted montecarlo run in this existing work_montecarlo directory", type=str)

    argparser.add_argument('-w', '--work-dir', help="Pre-created work directory to use for a fresh run (the compute service creates it so it knows the run's directory at start-up)", type=str)

    argparser.add_argument('--stop-flag-file', help="Path to a sentinel file; when it appears, the montecarlo run pauses gracefully (cross-platform pause for the web service)", type=str)

    argparser.add_argument('-v', '--version', action='version', version='%(prog)s '+ver_runner_tool)

    args = argparser.parse_args()
    return args


if __name__ == '__main__':
    args = get_args()

    print('ForRocket Runner Start.')

    if args.montecarlo_config_json:
        stop_event = _install_graceful_stop()
        if args.stop_flag_file:
            _watch_stop_flag(args.stop_flag_file, stop_event)
        if args.resume_work_dir:
            print('== Impact Point Montecarlo Simulation Mode (Resume) ==')
            print(os.path.basename(args.montecarlo_config_json), '->', args.resume_work_dir)
            resume_montecarlo(os.path.basename(args.montecarlo_config_json), args.resume_work_dir,
                              args.use_max_thread, stop_event=stop_event)
        else:
            print('== Impact Point Montecarlo Simulation Mode ==')
            print(os.path.basename(args.solver_config_json), os.path.basename(args.montecarlo_config_json))
            run_montecarlo(os.path.basename(args.solver_config_json), os.path.basename(args.montecarlo_config_json),
                           args.use_max_thread, stop_event=stop_event, work_dir=args.work_dir)
    elif args.area_config_json:
        print('== Impact Point Area Calcuration Mode ==')
        run_area(os.path.basename(args.solver_config_json), os.path.basename(args.area_config_json), args.use_max_thread, work_dir=args.work_dir)
    elif args.sensitivity_config_json:
        print('== Sensitivity Analysis Mode ==')
        print(os.path.basename(args.solver_config_json), os.path.basename(args.sensitivity_config_json))
        work_dir = run_sensitivity(os.path.basename(args.solver_config_json), os.path.basename(args.sensitivity_config_json), args.use_max_thread, work_dir=args.work_dir)
        post_sensitivity(work_dir)
    else:
        print('== Trajectory Calculation Mode ==')
        run_trajectory(os.path.basename(args.solver_config_json), work_dir=args.work_dir)


