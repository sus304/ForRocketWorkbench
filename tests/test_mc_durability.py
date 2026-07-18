"""Monte Carlo resume durability under an abrupt power loss (regression for the reboot test).

A hard host power-off during a running MC left recently-"completed" cases with an empty
flight-log CSV: the RunManifest append was fsync'd, but the per-case CSV write was not, so the
page-cached CSV data was lost while the manifest entry survived. On resume those cases were
skipped (in the manifest), the empty CSVs remained, and post_montecarlo crashed reading them
(pandas EmptyDataError), failing the whole job.

These cover the three fixes:
- fsync the case outputs (+ dir) before the manifest records the case complete (root cause);
- on resume, re-run cases recorded complete whose output is missing/empty (self-heal);
- post tolerates an empty/corrupt case CSV instead of failing the whole run (safety net).
"""
import os

import pandas as pd
import pytest

from runner_tool import runner_multi
from post_tool import post_montecarlo as pm


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
    assert runner_multi._case_output_valid(str(cases), '0_solver_config.json') is True
    assert runner_multi._case_output_valid(str(cases), '1_solver_config.json') is False
    assert runner_multi._case_output_valid(str(cases), '2_solver_config.json') is False


# --- durability: fsync case outputs before the manifest mark ---------------------

def test_fsync_case_outputs_syncs_only_that_case(tmp_path, monkeypatch):
    cases = tmp_path / 'cases'
    cases.mkdir()
    good = cases / '5_SAMPLE_stage1_flight_log.csv'
    good.write_text('t,x\n0,0\n')
    ballistic = cases / '5_SAMPLE_ballistic_stage1_flight_log.csv'
    ballistic.write_text('t,x\n0,0\n')
    other = cases / '6_SAMPLE_stage1_flight_log.csv'
    other.write_text('t,x\n0,0\n')

    synced = []
    monkeypatch.setattr(runner_multi, '_fsync_file', lambda p: synced.append(os.path.basename(p)))

    runner_multi._fsync_case_outputs(str(cases), '5_solver_config.json')

    assert '5_SAMPLE_stage1_flight_log.csv' in synced
    assert '5_SAMPLE_ballistic_stage1_flight_log.csv' in synced
    assert '6_SAMPLE_stage1_flight_log.csv' not in synced  # only case 5
    # the shared cases/ dir is intentionally NOT fsync'd per case (throughput); a lost file
    # is re-run on resume by the output validator instead.


def test_worker_fsyncs_before_manifest_mark(tmp_path, monkeypatch):
    """The case output must be durable BEFORE the manifest records completion, else a crash
    can leave a 'completed' case with a lost CSV."""
    cases = tmp_path / 'cases'
    cases.mkdir()
    (cases / '3_SAMPLE_stage1_flight_log.csv').write_text('t,x\n0,0\n')

    order = []
    monkeypatch.setattr(runner_multi, 'run_single', lambda f: None)  # no solver/binary
    monkeypatch.setattr(runner_multi, '_fsync_case_outputs',
                        lambda cd, f: order.append('fsync'))

    class _Manifest:
        def mark(self, name):
            order.append('mark')

    runner_multi._worker((str(cases), '3_solver_config.json', None, _Manifest(), None))
    assert order == ['fsync', 'mark']  # durability barrier precedes the completion record


# --- post tolerance: an empty case CSV must not fail the whole run ---------------

def test_process_one_case_returns_none_on_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '7_SAMPLE_stage1_flight_log.csv').write_text('')  # empty
    assert pm._process_one_case('7_SAMPLE_stage1_flight_log.csv') is None


def test_collect_case_results_skips_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '7_SAMPLE_stage1_flight_log.csv').write_text('')  # only an empty file
    result = pm._collect_case_results(['7_SAMPLE_stage1_flight_log.csv'])
    assert result[0] == []  # case_numbers empty, no crash
