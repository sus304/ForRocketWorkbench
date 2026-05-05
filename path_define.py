import os
from contextlib import contextmanager

workbench_work_directory = 'workspace'

runner_trajectory_directory = 'work_trajectory'
runner_area_directory = 'work_area'
runner_montecarlo_directory = 'work_montecarlo'
runner_sensitivity_directory = 'work_sensitivity'


@contextmanager
def chdir(path):
    """Temporarily change the current working directory; always restores on exit."""
    original = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def make_unique_work_dir(base_name):
    """Create './<base_name>' directory, appending _01, _02... if it already exists."""
    work_dir = './' + base_name
    if os.path.exists(work_dir):
        i = 1
        while os.path.exists(work_dir):
            work_dir = './' + base_name + '_%02d' % i
            i += 1
    os.mkdir(work_dir)
    return work_dir
