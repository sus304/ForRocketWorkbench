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
    # case 3: partial — one of the case's two logs (stage1 + ballistic) was torn to 0 bytes
    # while the sibling survived. A power loss flushes the two logs independently, so this is
    # the common torn shape; the whole case must be re-run, not treated as done.
    (cases / '3_SAMPLE_stage1_flight_log.csv').write_text('t,x\n0,0\n')           # good
    (cases / '3_SAMPLE_ballistic_stage1_flight_log.csv').write_text('')           # torn sibling
    assert runner_multi._case_output_valid(str(cases), '0_solver_config.json') is True
    assert runner_multi._case_output_valid(str(cases), '1_solver_config.json') is False
    assert runner_multi._case_output_valid(str(cases), '2_solver_config.json') is False
    assert runner_multi._case_output_valid(str(cases), '3_solver_config.json') is False


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

def test_process_one_case_returns_none_on_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '7_SAMPLE_stage1_flight_log.csv').write_text('')  # empty
    assert pm._process_one_case('7_SAMPLE_stage1_flight_log.csv') is None


def test_collect_case_results_skips_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '7_SAMPLE_stage1_flight_log.csv').write_text('')  # only an empty file
    result = pm._collect_case_results(['7_SAMPLE_stage1_flight_log.csv'])
    assert result[0] == []  # case_numbers empty, no crash
