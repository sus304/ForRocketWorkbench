import os
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from runner_tool.runner_single import run_single


def _worker(args):
    cases_dir, filename, on_case_complete = args
    os.chdir(cases_dir)
    run_single(filename)
    if on_case_complete is not None:
        on_case_complete(cases_dir, filename)


def run_multi(cases_dir, solver_config_file_list, max_thread_run=False, on_case_complete=None):
    '''
    cases_dir: 絶対パス。各ケースのJSONファイルが置かれたディレクトリ。
    solver_config_file_list: cases_dir からの相対ファイル名リスト。
    max_thread_run: True の場合 cpu_count スレッド、False の場合 cpu_count-1 スレッド使用。
    on_case_complete: 省略可。callable(cases_dir, solver_config_file_name)。各ケースの
        ソルバ完了直後にワーカスレッド内で呼ばれる。モンテカルロの統計のみ出力モードで、
        ケースごとに統計を抽出してフライトログを即削除する用途。ワーカ間で並列に呼ばれるため
        スレッドセーフに実装すること。
    '''
    if not solver_config_file_list:
        return

    cpu = os.cpu_count() or 1
    workers = cpu if max_thread_run else max(1, cpu - 1)

    print(f'CPU count: {cpu}, Using workers: {workers}')
    print(f'Total: {len(solver_config_file_list)} cases')

    args = [(cases_dir, f, on_case_complete) for f in solver_config_file_list]

    original_cwd = os.getcwd()
    time_start = datetime.datetime.now()
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_worker, arg) for arg in args]
            for fut in tqdm(as_completed(futures), total=len(futures)):
                fut.result()
    finally:
        os.chdir(original_cwd)
    elapsed = datetime.datetime.now() - time_start

    print(f'Complete. Elapsed: {elapsed}')
