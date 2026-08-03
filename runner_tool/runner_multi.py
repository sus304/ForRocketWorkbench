import os
import glob
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import psutil
from tqdm import tqdm

from runner_tool.runner_single import run_single

# Per-case outcomes returned by _worker.
RAN = 'ran'          # solver (and any per-case post step) succeeded; recorded complete
SKIPPED = 'skipped'  # never started, because a cooperative stop was already requested
FAILED = 'failed'    # raised; deliberately NOT recorded complete, so resume re-runs it

# Append-only list of case names that failed, written next to the completion manifest. The
# manifest alone cannot express "attempted and failed" — a case is either in it or not — so a
# run that finishes with cases missing would otherwise look identical to one that never
# started them.
FAILED_CASES_FILENAME = 'failed_cases.txt'


def _record_failed_case(manifest, filename):
    """Best-effort note that a case failed. Never raises: the failure is already being
    handled, and losing the note must not cost the rest of the run."""
    if manifest is None:
        return
    try:
        path = os.path.join(os.path.dirname(manifest.path), FAILED_CASES_FILENAME)
        with open(path, 'a') as f:
            f.write(filename + '\n')
    except OSError:
        pass


def _case_flight_logs(cases_dir, solver_config_file_name):
    case_num = os.path.basename(solver_config_file_name).split('_', 1)[0]
    return glob.glob(os.path.join(cases_dir, f'{case_num}_*_flight_log.csv'))


def _case_output_valid(cases_dir, solver_config_file_name):
    """True iff the case's flight-log CSVs are all present and non-empty.

    A case writes more than one log (e.g. stage1 + ballistic), and a power loss flushes them
    independently, so one can be torn to 0 bytes while its sibling survives. A case recorded
    complete with ANY missing/empty log is treated as not done, so resume re-runs the whole
    case rather than leaving an empty CSV for post to trip on."""
    logs = _case_flight_logs(cases_dir, solver_config_file_name)
    if not logs:
        return False  # no output at all -> re-run
    for p in logs:
        try:
            if os.path.getsize(p) == 0:
                return False  # any torn/empty log -> re-run the whole case
        except OSError:
            return False
    return True


def _make_output_validator(cases_dir):
    """Build a case output validator from a SINGLE scan of cases_dir.

    Equivalent to calling _case_output_valid per case, but scans the directory once instead of
    globbing it per case, so resume validation is O(files) rather than O(cases x files) — the
    per-case glob stalled real 10k-case runs (tens of thousands of files scanned per case).

    A case is valid iff it produced at least one *_flight_log.csv and none of them are
    empty/unreadable (a power loss can tear one of a case's sibling logs to 0 bytes)."""
    has_log = set()   # case number -> produced at least one flight log
    torn = set()      # case number -> at least one empty/unreadable log
    try:
        with os.scandir(cases_dir) as it:
            for entry in it:
                name = entry.name
                if not name.endswith('_flight_log.csv'):
                    continue
                case_num = name.split('_', 1)[0]
                has_log.add(case_num)
                try:
                    if entry.stat().st_size == 0:
                        torn.add(case_num)
                except OSError:
                    torn.add(case_num)
    except OSError:
        pass  # missing cases dir -> nothing valid -> every case re-runs

    def _valid(solver_config_file_name):
        case_num = os.path.basename(solver_config_file_name).split('_', 1)[0]
        return case_num in has_log and case_num not in torn

    return _valid


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
        return SKIPPED
    os.chdir(cases_dir)
    try:
        run_single(filename)
        if on_case_complete is not None:
            on_case_complete(cases_dir, filename)
    except Exception as exc:
        # One bad case must neither take the run down nor be recorded complete. Staying out
        # of the manifest is exactly what makes resume re-run it; marking it done instead is
        # how a full disk (torn case configs, solvers that wrote nothing) produced thousands
        # of "completed" cases with no output, which post then read as real samples.
        print(f'Case failed and was left incomplete for resume: {filename}: {exc}')
        _record_failed_case(manifest, filename)
        return FAILED
    # Record completion LAST, after the solver run and any per-case post step both
    # succeeded, so an interrupted run never marks a case it didn't fully finish.
    #
    # We deliberately do NOT fsync the case CSV before marking: on the target VM (Hyper-V
    # VHDX) a per-case fsync costs hundreds of ms and collapsed MC throughput ~50x. Durability
    # is instead recovered on resume: a case recorded complete whose CSV is missing/empty
    # (lost to the page cache on a power loss) is re-run by the output validator
    # (_case_output_valid), and post tolerates any residual empty/corrupt CSV. See the
    # reboot-resume regression in tests/test_mc_durability.py.
    if manifest is not None:
        manifest.mark(filename)
    return RAN


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
    failed = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_worker, arg) for arg in args]
            for fut in tqdm(as_completed(futures), total=len(futures)):
                outcome = fut.result()
                if outcome == RAN:
                    ran += 1
                elif outcome == FAILED:
                    failed += 1
    finally:
        os.chdir(original_cwd)
    elapsed = datetime.datetime.now() - time_start

    if stop_event is not None and stop_event.is_set():
        not_started = len(args) - ran - failed
        print(f'Paused. Ran {ran} case(s) this session; {not_started} not started. '
              f'Resume with --resume-work-dir to finish the rest. Elapsed: {elapsed}')
    else:
        print(f'Complete. Elapsed: {elapsed}')
    if failed:
        # Loud and last: an incomplete result set is the kind of thing that otherwise gets
        # read as a full one. The names are in FAILED_CASES_FILENAME next to the manifest.
        print(f'WARNING: {failed} of {len(args)} case(s) failed and were NOT recorded '
              f'complete. The statistics below cover {ran} case(s). See '
              f'{FAILED_CASES_FILENAME}; resume the run to retry them.')
