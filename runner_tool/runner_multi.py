import datetime
from tqdm import tqdm

import multiprocessing
from multiprocessing import Pool

from runner_tool.runner_single import run_single


def run_multi(solver_config_json_file_list, max_thread_run=False):
    '''
    file_listをイタレータにして複数計算ケースを実行する
    2ケース以上のみ対応
    マルチスレッド対応
    '''
    if len(solver_config_json_file_list) < 1:
        return

    cpu_thread_count = multiprocessing.cpu_count()
    if cpu_thread_count < 3:
        using_cpu_count = 1
    else:
        using_cpu_count = int(cpu_thread_count / 3)
    if max_thread_run and cpu_thread_count > 1:
        using_cpu_count = cpu_thread_count - 1
    print('CPU Max Thread: '+str(cpu_thread_count))
    print('Using CPU Thread: '+str(using_cpu_count))

    # 計算時間推定用のテストラン
    print('\rPreparing ...', end='')
    time_start_calc = datetime.datetime.now()
    run_single(solver_config_json_file_list[0])
    time_end_calc = datetime.datetime.now()
    case_calc_duration = time_end_calc - time_start_calc
    print('\rPrepare Complete\n', end='')

    total_case_count = len(solver_config_json_file_list)
    print('Total: '+str(total_case_count)+' case')

    estimate_total_calc_duration = case_calc_duration * total_case_count / using_cpu_count
    if total_case_count < using_cpu_count:
        estimate_total_calc_duration = case_calc_duration
    print('Estimate Calcurate Duration: ', estimate_total_calc_duration)
    print('\rCalculating ...', end='')

    # テストランした先頭ケースを除外してマルチプロセス処理を開始
    case_multi_list = solver_config_json_file_list[1:]
    time_start_calc = datetime.datetime.now()
    with Pool(processes=using_cpu_count) as p:
        p_imap = p.imap(func=run_single, iterable=case_multi_list)
        res = list(tqdm(p_imap, total=len(case_multi_list)))
    time_end_calc = datetime.datetime.now()
    print('Complete calculate.')
    print('Actual Calculate Duration: ', time_end_calc - time_start_calc)
    

