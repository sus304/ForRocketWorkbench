import os
import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm

from runner_tool.runner_single import run_single


def _worker(args):
    cases_dir, filename = args
    os.chdir(cases_dir)
    run_single(filename)


def run_multi(cases_dir, solver_config_file_list, max_thread_run=False):
    '''
    cases_dir: 絶対パス。各ケースのJSONファイルが置かれたディレクトリ。
    solver_config_file_list: cases_dir からの相対ファイル名リスト。
    max_thread_run: True の場合 cpu_count スレッド、False の場合 cpu_count-1 スレッド使用。
    '''
    if not solver_config_file_list:
        return

    cpu = os.cpu_count() or 1
    workers = cpu if max_thread_run else max(1, cpu - 1)

    print(f'CPU count: {cpu}, Using workers: {workers}')
    print(f'Total: {len(solver_config_file_list)} cases')

    args = [(cases_dir, f) for f in solver_config_file_list]

    time_start = datetime.datetime.now()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_worker, arg) for arg in args]
        for _ in tqdm(as_completed(futures), total=len(futures)):
            pass
    elapsed = datetime.datetime.now() - time_start

    print(f'Complete. Elapsed: {elapsed}')
