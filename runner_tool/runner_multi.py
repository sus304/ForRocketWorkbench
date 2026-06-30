import os
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from runner_tool.runner_single import run_single


def _worker(args):
    cases_dir, filename, on_case_complete, manifest, stop_event = args
    # Cooperative pause: if a stop was requested, don't start this case. Cases already
    # in flight finish normally; un-started cases stay out of the manifest and are re-run
    # on resume. Returns a sentinel so run_multi can count what it skipped.
    if stop_event is not None and stop_event.is_set():
        return False
    os.chdir(cases_dir)
    run_single(filename)
    if on_case_complete is not None:
        on_case_complete(cases_dir, filename)
    # Record completion LAST, after the solver run and any per-case post step both
    # succeeded, so an interrupted run never marks a case it didn't fully finish.
    if manifest is not None:
        manifest.mark(filename)
    return True


def run_multi(cases_dir, solver_config_file_list, max_thread_run=False, on_case_complete=None,
              manifest=None, stop_event=None):
    '''
    cases_dir: 絶対パス。各ケースのJSONファイルが置かれたディレクトリ。
    solver_config_file_list: cases_dir からの相対ファイル名リスト。
    max_thread_run: True の場合 cpu_count スレッド、False の場合 cpu_count-1 スレッド使用。
    on_case_complete: 省略可。callable(cases_dir, solver_config_file_name)。各ケースの
        ソルバ完了直後にワーカスレッド内で呼ばれる。モンテカルロの統計のみ出力モードで、
        ケースごとに統計を抽出してフライトログを即削除する用途。ワーカ間で並列に呼ばれるため
        スレッドセーフに実装すること。
    manifest: 省略可。RunManifest。指定時、既に完了記録のあるケースをスキップし（中断後の
        再開）、各ケース完了時に完了を記録する。
    stop_event: 省略可。threading.Event。実行中にセットされると未開始のケースの起動を止め、
        実行中のケースは完走させてから戻る（協調的な一時停止）。未開始ケースは manifest に
        記録されないため、resume で再実行される。
    '''
    if not solver_config_file_list:
        return

    # Resume support: skip cases already recorded complete by a previous (interrupted) run.
    if manifest is not None:
        done = manifest.completed()
        if done:
            remaining = [f for f in solver_config_file_list if f not in done]
            skipped = len(solver_config_file_list) - len(remaining)
            print(f'Resuming: {skipped} of {len(solver_config_file_list)} cases already complete, '
                  f'{len(remaining)} remaining')
            solver_config_file_list = remaining
            if not solver_config_file_list:
                print('All cases already complete; nothing to run.')
                return

    cpu = os.cpu_count() or 1
    workers = cpu if max_thread_run else max(1, cpu - 1)

    print(f'CPU count: {cpu}, Using workers: {workers}')
    print(f'Total: {len(solver_config_file_list)} cases')

    args = [(cases_dir, f, on_case_complete, manifest, stop_event) for f in solver_config_file_list]

    original_cwd = os.getcwd()
    time_start = datetime.datetime.now()
    ran = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_worker, arg) for arg in args]
            for fut in tqdm(as_completed(futures), total=len(futures)):
                if fut.result():
                    ran += 1
    finally:
        os.chdir(original_cwd)
    elapsed = datetime.datetime.now() - time_start

    if stop_event is not None and stop_event.is_set():
        not_started = len(args) - ran
        print(f'Paused. Ran {ran} case(s) this session; {not_started} not started. '
              f'Resume with --resume-work-dir to finish the rest. Elapsed: {elapsed}')
    else:
        print(f'Complete. Elapsed: {elapsed}')
