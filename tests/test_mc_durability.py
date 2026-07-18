"""Monte Carlo resume durability under an abrupt power loss (regression for the reboot test).

A hard host power-off during a running MC left recently-"completed" cases with an empty
flight-log CSV: the RunManifest append was fsync'd, but the per-case CSV write was not, so the
page-cached CSV data was lost while the manifest entry survived. On resume those cases were
skipped (in the manifest), the empty CSVs remained, and post_montecarlo crashed reading them
(pandas EmptyDataError), failing the whole job.

Fixing this with a per-case CSV fsync-before-mark was correct but unusable on the target VM
(Hyper-V VHDX): a per-case fsync cost hundreds of ms and collapsed MC throughput ~50x. So the
fix instead has no per-case runtime cost:
- on resume, re-run any case recorded complete whose output is missing/empty (self-heal);
- post tolerates an empty/corrupt case CSV instead of failing the whole run (safety net).
The residual risk (a case whose CSV was truncated but non-empty at the instant of power loss)
is accepted: rare, and a minor per-case statistical perturbation rather than a crash.
"""
import json
import os
import shutil

import pandas as pd
import pytest

from runner_tool import runner_multi
from runner_tool import runner_single
from post_tool import post_montecarlo as pm

EXAMPLE = os.path.join(os.path.dirname(__file__), '..', 'projects', 'example')


# --- resume self-heal: re-run marked-but-invalid-output cases --------------------

def test_resume_remaining_reruns_marked_but_invalid_output():
    files = ['0_solver_config.json', '1_solver_config.json', '2_solver_config.json']
    done = {'0_solver_config.json', '1_solver_config.json'}  # case 2 not done

    def output_valid(f):  # case 0 kept a good CSV; case 1's CSV was lost (empty)
        return f == '0_solver_config.json'

    remaining = runner_multi._resume_remaining(files, done, output_validator=output_valid)
    # case 1 re-run (marked but output invalid), case 2 re-run (not in manifest), case 0 skipped
    assert remaining == ['1_solver_config.json', '2_solver_config.json']


def test_resume_remaining_no_validator_is_legacy_behaviour():
    files = ['0_x.json', '1_x.json']
    assert runner_multi._resume_remaining(files, {'0_x.json'}) == ['1_x.json']


def test_resume_remaining_empty_manifest_runs_all():
    files = ['0_x.json', '1_x.json']
    assert runner_multi._resume_remaining(files, set()) == files


def test_case_output_valid_detects_empty_and_missing(tmp_path):
    cases = tmp_path / 'cases'
    cases.mkdir()
    (cases / '0_SAMPLE_stage1_flight_log.csv').write_text('t,x\n0,0\n')  # good
    (cases / '1_SAMPLE_stage1_flight_log.csv').write_text('')            # empty (torn)
    # case 2: no file at all (lost)
    # case 3: partial — one of the case's two logs (stage1 + ballistic) was torn to 0 bytes
    # while the sibling survived. A power loss flushes the two logs independently, so this is
    # the common torn shape; the whole case must be re-run, not treated as done.
    (cases / '3_SAMPLE_stage1_flight_log.csv').write_text('t,x\n0,0\n')           # good
    (cases / '3_SAMPLE_ballistic_stage1_flight_log.csv').write_text('')           # torn sibling
    assert runner_multi._case_output_valid(str(cases), '0_solver_config.json') is True
    assert runner_multi._case_output_valid(str(cases), '1_solver_config.json') is False
    assert runner_multi._case_output_valid(str(cases), '2_solver_config.json') is False
    assert runner_multi._case_output_valid(str(cases), '3_solver_config.json') is False


# --- batch output validator: one directory scan, not one glob per case ------------
#
# _case_output_valid globs cases/ per case, so resume validation was O(cases x files) and
# stalled on real 10k-case runs (tens of thousands of files scanned per case). The batch
# validator scans cases/ exactly once and answers each case in O(1) from the snapshot.

def test_make_output_validator_matches_per_case_semantics(tmp_path):
    cases = tmp_path / 'cases'
    cases.mkdir()
    (cases / '0_SAMPLE_stage1_flight_log.csv').write_text('t,x\n0,0\n')            # good
    (cases / '1_SAMPLE_stage1_flight_log.csv').write_text('')                      # empty (torn)
    # case 2: no file at all (lost)
    (cases / '3_SAMPLE_stage1_flight_log.csv').write_text('t,x\n0,0\n')            # good
    (cases / '3_SAMPLE_ballistic_stage1_flight_log.csv').write_text('')           # torn sibling
    (cases / '10_SAMPLE_stage1_flight_log.csv').write_text('t,x\n0,0\n')          # good (prefix 10 != 1)

    valid = runner_multi._make_output_validator(str(cases))
    for case_num, expected in (('0', True), ('1', False), ('2', False), ('3', False), ('10', True)):
        f = f'{case_num}_solver_config.json'
        assert valid(f) is expected
        # ...and agrees with the authoritative per-case checker it replaces.
        assert valid(f) == runner_multi._case_output_valid(str(cases), f)


def test_make_output_validator_scans_directory_once(tmp_path, monkeypatch):
    cases = tmp_path / 'cases'
    cases.mkdir()
    for i in range(5):
        (cases / f'{i}_SAMPLE_stage1_flight_log.csv').write_text('t\n0\n')

    calls = {'n': 0}
    real_scandir = os.scandir

    def counting_scandir(path):
        calls['n'] += 1
        return real_scandir(path)

    monkeypatch.setattr(runner_multi.os, 'scandir', counting_scandir)
    valid = runner_multi._make_output_validator(str(cases))
    for i in range(5):
        valid(f'{i}_solver_config.json')
    assert calls['n'] == 1  # one scan for the whole resume decision, not one per case


# --- worker stays on the fast path (no per-case fsync) ---------------------------

def test_worker_marks_without_per_case_fsync(tmp_path, monkeypatch):
    """The per-case path must not fsync (it was ~50x too slow on the target VM); it just runs
    the case and records completion in the manifest."""
    cases = tmp_path / 'cases'
    cases.mkdir()
    monkeypatch.setattr(runner_multi, 'run_single', lambda f: None)  # no solver/binary
    monkeypatch.setattr(os, 'fsync', lambda fd: (_ for _ in ()).throw(AssertionError('no fsync')))

    marked = []

    class _Manifest:
        def mark(self, name):
            marked.append(name)

    runner_multi._worker((str(cases), '3_solver_config.json', None, _Manifest(), None))
    assert marked == ['3_solver_config.json']  # completion recorded, and no fsync happened


# --- post tolerance: an empty case CSV must not fail the whole run ---------------

def test_process_case_full_flags_empty(tmp_path):
    p = tmp_path / '7_SAMPLE_stage1_flight_log.csv'
    p.write_text('')  # empty (torn)
    out = pm._process_case_full((str(p), None, pm.IIP_MIN_APOGEE_M))
    assert out['status'] == 'empty' and out['case'] == 7


def test_case_pipeline_skips_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '7_SAMPLE_stage1_flight_log.csv').write_text('')  # only an empty file
    results = pm._run_case_pipeline(['7_SAMPLE_stage1_flight_log.csv'])
    assert pm._metric_lists(results, ballistic=False)[0] == []  # case_numbers empty, no crash


def _write_synth_log(path):
    """Minimal flight log with every _MC_COLS column and a clear apogee at index 3."""
    alt = [0.0, 100.0, 250.0, 400.0, 300.0, 120.0]
    n = len(alt)
    data = {c: [1.0] * n for c in pm._MC_COLS}
    data['Time [s]'] = [float(i) for i in range(n)]
    data['Altitude [m]'] = alt
    data['Fz-gravity [N]'] = [0.0] + [-90.0] * (n - 1)
    pd.DataFrame(data, columns=pm._MC_COLS).to_csv(path, index=False)


def test_case_pipeline_process_pool_path(tmp_path, monkeypatch):
    """Above _SERIAL_THRESHOLD the pipeline goes through ProcessPoolExecutor: the worker and
    its args must survive pickling/spawn and results must cover every case. Guards the
    parallel path the small-N tests never reach (the empty log must also survive it)."""
    monkeypatch.chdir(tmp_path)
    n = pm._SERIAL_THRESHOLD + 4
    names = []
    for i in range(n):
        name = f'{i}_SAMPLE_stage1_flight_log.csv'
        _write_synth_log(tmp_path / name)
        names.append(name)
    (tmp_path / f'{n}_SAMPLE_stage1_flight_log.csv').write_text('')  # torn straggler
    names.append(f'{n}_SAMPLE_stage1_flight_log.csv')

    results = pm._run_case_pipeline(names)
    lists = pm._metric_lists(results, ballistic=False)
    assert lists[0] == list(range(n))  # every good case present, sorted; empty one skipped
    assert sum(1 for r in results if r['status'] == 'empty') == 1


# --- ballistic input regeneration: torn per-case ballistic configs are rewritten ------
#
# The two-phase (nominal + ballistic) MC generates the ballistic per-case inputs
# (*_ballistic.json for soe / stage config) at run time. A power loss can tear these to
# 0 bytes. run_single must regenerate them on re-run, or the ballistic solver phase runs
# against an empty config and the descent statistics silently degrade for the interrupted
# block. Regeneration is idempotent (the content is derived deterministically from the case
# config), so the fix is to always (re)write them rather than skip when the path exists.

def _example_case_dir(tmp_path):
    """Copy the version-controlled example project into tmp_path so run_single (which resolves
    stage/soe by basename relative to cwd) has a self-contained working directory."""
    for name in ('config_solver.json', 'param_list_stage1.json', 'sequence_of_event.json',
                 'param_rocket.json', 'param_engine.json', 'thrust_mdot_p.csv', 'wind.csv'):
        shutil.copy(os.path.join(EXAMPLE, name), tmp_path / name)
    return tmp_path


def test_run_single_regenerates_torn_ballistic_inputs(tmp_path, monkeypatch):
    _example_case_dir(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner_single, 'run_solver', lambda f: None)  # no ForRocket binary

    # Simulate a power loss that tore the ballistic soe/stage configs to 0 bytes on a prior run.
    torn_soe = tmp_path / 'sequence_of_event_ballistic.json'
    torn_stage = tmp_path / 'param_list_stage1_ballistic.json'
    torn_soe.write_text('')
    torn_stage.write_text('')

    runner_single.run_single('config_solver.json')

    # Both must be regenerated with valid, ballistic-disabled content (not left empty).
    assert torn_soe.stat().st_size > 0
    assert torn_stage.stat().st_size > 0
    soe = json.loads(torn_soe.read_text())
    assert soe['Enable Parachute Open'] is False
    stage = json.loads(torn_stage.read_text())
    assert stage['Sequence of Event File Path'] == 'sequence_of_event_ballistic.json'
