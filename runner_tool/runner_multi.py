import os
import glob
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import psutil
from tqdm import tqdm

from runner_tool.runner_single import run_single


def _fsync_file(path):
    """fsync a single file's data to disk (best effort)."""
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _case_flight_logs(cases_dir, solver_config_file_name):
    case_num = os.path.basename(solver_config_file_name).split('_', 1)[0]
    return glob.glob(os.path.join(cases_dir, f'{case_num}_*_flight_log.csv'))


def _fsync_case_outputs(cases_dir, solver_config_file_name):
    """Durably flush a case's flight-log CSV data to disk just before the manifest records the
    case complete. Without this a case's CSV write can sit in the page cache while the fsync'd
    manifest entry survives a power loss, leaving a "completed" case with an empty CSV that post
    then chokes on (found by the reboot-resume test).

    The containing directory is intentionally NOT fsync'd per case: doing so serialised all
    worker threads on the shared cases/ dir and collapsed throughput ~50x. A case whose CSV
    file is lost entirely (directory entry not yet durable) is instead re-run on resume by the
    output validator (_case_output_valid), so per-case dir fsync is unnecessary for correctness.
    """
    for p in _case_flight_logs(cases_dir, solver_config_file_name):
        _fsync_file(p)


def _case_output_valid(cases_dir, solver_config_file_name):
    """True iff the case has a non-empty flight-log CSV on disk. A case recorded complete
    whose CSV is missing/empty (torn by a power loss) is treated as not done, so resume
    re-runs it instead of leaving an empty CSV for post to trip on."""
    for p in _case_flight_logs(cases_dir, solver_config_file_name):
        try:
            if os.path.getsize(p) > 0:
                return True
        except OSError:
            pass
    return False


def _resume_remaining(solver_config_file_list, done, output_validator=None):
    """Cases still to run: those not recorded complete, plus those recorded complete whose
    output is missing/empty (output_validator returns False). With no validator this is the
    legacy 'skip everything in the manifest' behaviour."""
    remaining = []
    for f in solver_config_file_list:
        if f not in done:
            remaining.append(f)
        elif output_validator is not None and not output_validator(f):
            remaining.append(f)
    return remaining


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
    # succeeded, so an interrupted run never marks a case it didn't fully finish. fsync the
    # case's outputs BEFORE the manifest mark so a power loss cannot leave a case recorded
    # complete with a lost/empty CSV (durability ordering; reboot-resume regression).
    if manifest is not None:
        _fsync_case_outputs(cases_dir, filename)
        manifest.mark(filename)
    return True


def run_multi(cases_dir, solver_config_file_list, max_thread_run=False, on_case_complete=None,
              manifest=None, stop_event=None, output_validator=None):
    '''
    cases_dir: 絶対パス。各ケースのJSONファイルが置かれたディレクトリ。
    solver_config_file_list: cases_dir からの相対ファイル名リスト。
    max_thread_run: False（既定）の場合は物理コア数スレッド、True の場合は論理コア数
        （SMT込みの全スレッド）を使用。ForRocket ソルバはメモリ帯域バウンドで、1物理コアに
        1ソルバプロセスを割り当てた付近でスループットが最大になり、SMT で物理コアを超えて
        oversubscribe すると共有メモリポートの奪い合いで逆に低下する（2026-07-15 実測：物理
        コア数が論理コア数比で約15-20%高速）。このため既定は物理コア数とする。
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
    # output_validator (keep-logs mode) additionally forces a re-run of any case recorded
    # complete whose CSV is missing/empty (torn by a power loss), so post never sees it.
    if manifest is not None:
        done = manifest.completed()
        if done:
            remaining = _resume_remaining(solver_config_file_list, done, output_validator)
            skipped = len(solver_config_file_list) - len(remaining)
            print(f'Resuming: {skipped} of {len(solver_config_file_list)} cases already complete, '
                  f'{len(remaining)} remaining')
            solver_config_file_list = remaining
            if not solver_config_file_list:
                print('All cases already complete; nothing to run.')
                return

    logical = os.cpu_count() or 1
    if max_thread_run:
        workers = logical
    else:
        # Memory-bandwidth-bound solver: peak throughput at ~1 process per physical core.
        # psutil.cpu_count(logical=False) can return None on exotic platforms; fall back to
        # the previous logical-1 heuristic there.
        physical = psutil.cpu_count(logical=False)
        workers = max(1, physical if physical else logical - 1)

    print(f'CPU count (logical): {logical}, Using workers: {workers}')
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
