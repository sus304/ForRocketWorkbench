"""
Smoke tests for the multi-case runner pipelines (montecarlo, area).

Each test runs the real ForRocket binary on a small case count and asserts that
per-case flight log files actually exist on disk afterwards. Catches:

  - the "mode forgot to stage dependency files into cases dir" class of bug
    (caught here because solvers fail to find their input files), and
  - the "ThreadPoolExecutor swallowed case exceptions silently" class of bug
    (caught here because we assert result files exist, not just exit code 0).

A trajectory smoke test is omitted because test_regression.py / test_behavior.py
already exercise that path end-to-end.
"""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from path_define import chdir
from runner_tool.runner_area import run_area
from runner_tool.runner_montecarlo import run_montecarlo
from post_tool.post_montecarlo import post_montecarlo, CASE_METRICS_FILE, _MC_COLS
from tests._selfcontained import assert_cases_self_contained
from tests._project import copy_example, enable_all_file_inputs, disable_parachute


@pytest.fixture
def project_copy(tmp_path, projects_dir) -> Path:
    """Copy the tracked sample project into a tmp dir so runs don't pollute it."""
    return copy_example(projects_dir, tmp_path / "example")


@pytest.fixture(scope="session")
def mc_post_supported(binary_path, projects_dir, tmp_path_factory) -> bool:
    """Whether the available ForRocket binary emits every column post_montecarlo needs.

    The Monte Carlo statistics (used by both the legacy full-log post and the new
    stats-only mode) require the resonance/AoA diagnostic columns in _MC_COLS. Older
    binaries predate them, so the post step can't run. Probe once and let dependent
    tests skip cleanly instead of failing on an out-of-date solver build.
    """
    proj = copy_example(projects_dir, tmp_path_factory.mktemp("mc_probe") / "example")
    _disable_all_mc_errors(proj / "config_montecarlo.json", 1, output_all_logs=True)
    with chdir(str(proj)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")
    work_dir = list(proj.glob("work_montecarlo*"))[0]
    logs = list((work_dir / "cases").glob("*_stage1_flight_log.csv"))
    if not logs:
        return False
    header = pd.read_csv(logs[0], nrows=0).columns
    return all(c in header for c in _MC_COLS)


def _disable_all_mc_errors(mc_cfg_path: Path, case_count: int, output_all_logs: bool = True):
    cfg = json.loads(mc_cfg_path.read_text())
    cfg["MonteCarlo Case Count"] = case_count
    cfg["Output All Case Logs"] = output_all_logs
    for ep in cfg.get("Error Parameters", {}).values():
        if isinstance(ep, dict) and "Enable" in ep:
            ep["Enable"] = False
    mc_cfg_path.write_text(json.dumps(cfg))


def test_montecarlo_produces_per_case_flight_logs(binary_path, project_copy):
    case_count = 2
    _disable_all_mc_errors(project_copy / "config_montecarlo.json", case_count)

    with chdir(str(project_copy)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")

    work_dirs = list(project_copy.glob("work_montecarlo*"))
    assert work_dirs, "no work_montecarlo directory was created"
    cases_dir = work_dirs[0] / "cases"
    assert cases_dir.is_dir(), f"cases dir missing under {work_dirs[0]}"

    for i in range(case_count):
        logs = list(cases_dir.glob(f"{i}_*_stage1_flight_log.csv"))
        assert logs, f"no flight log for case {i} in {cases_dir}"


def _synthetic_flight_log() -> pd.DataFrame:
    """Minimal flight log containing every column in _MC_COLS, with a clear apogee so
    post_summary_for_montecarlo's ascent-window slicing ([:index_apogee]) is non-empty."""
    altitude = [0.0, 100.0, 250.0, 400.0, 300.0, 120.0]  # apogee at index 3
    n = len(altitude)
    data = {
        'Time [s]':                    [float(i) for i in range(n)],
        'Altitude [m]':                altitude,
        'Downrange [m]':               [0.0, 10.0, 30.0, 60.0, 90.0, 120.0],
        'Latitude [deg]':              [31.25, 31.25, 31.26, 31.27, 31.28, 31.29],
        'Longitude [deg]':             [131.08, 131.08, 131.09, 131.10, 131.11, 131.12],
        'Vx-body [m/s]':               [0.0, 50.0, 90.0, 70.0, 40.0, 20.0],
        'Vy-body [m/s]':               [0.0, 1.0, 2.0, 1.5, 1.0, 0.5],
        'Vz-body [m/s]':               [0.0, 1.0, 2.0, 1.5, 1.0, 0.5],
        'DynamicPressure [kPa]':       [0.0, 20.0, 35.0, 25.0, 10.0, 2.0],
        'MachNumber [-]':              [0.0, 0.5, 1.2, 0.9, 0.4, 0.1],
        'TotalAoA [deg]':              [0.0, 2.0, 5.0, 3.0, 1.0, 0.5],
        'AngleVelx [deg/s]':           [0.0, 10.0, 30.0, 20.0, 5.0, 1.0],
        'Burning [0/1]':               [1, 1, 1, 0, 0, 0],
        'Fz-gravity [N]':              [0.0, -90.0, -90.0, -90.0, -90.0, -90.0],
        'GyroStabilityFactor Sg [-]':  [2.0, 1.8, 1.5, 1.6, 1.9, 2.1],
        'ResonanceRatio [-]':          [3.0, 2.5, 1.2, 1.4, 2.0, 3.0],
        'TrimAoA [deg]':               [0.0, 1.0, 2.5, 1.5, 0.5, 0.2],
        'LateralAeroLoad [N]':         [0.0, 100.0, 250.0, 150.0, 50.0, 10.0],
    }
    return pd.DataFrame(data, columns=_MC_COLS)


def test_montecarlo_stats_only_pipeline_without_binary(monkeypatch, project_copy):
    """Binary-independent check of the full stats-only path: a fake solver writes a
    flight log per case; the runner must extract metrics + delete the log during the run,
    and post must rebuild result_table.csv from the metrics file alone.

    Doesn't depend on the solver build, so it validates the feature even while the
    resonance-diagnostic columns are pending a solver rebuild.
    """
    case_count = 3

    def _fake_run_solver(solver_config_json_file_path, cwd=None):
        with open(solver_config_json_file_path) as f:
            cfg = json.load(f)
        log_name = f"{cfg['Model ID']}_stage1_flight_log.csv"
        _synthetic_flight_log().to_csv(log_name, index=False)

    # run_single calls run_solver by the name imported into its own module namespace.
    monkeypatch.setattr("runner_tool.runner_single.run_solver", _fake_run_solver)

    disable_parachute(project_copy)  # one stage1 log per case (no ballistic/decent split)
    _disable_all_mc_errors(project_copy / "config_montecarlo.json", case_count, output_all_logs=False)
    with chdir(str(project_copy)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")

    work_dir = list(project_copy.glob("work_montecarlo*"))[0]

    # Flight logs must have been deleted during the run (peak-disk bound).
    leftover = list((work_dir / "cases").glob("*_flight_log.csv"))
    assert not leftover, f"flight logs were not discarded: {leftover}"

    # Compact metrics file: one row per case.
    metrics = pd.read_csv(work_dir / CASE_METRICS_FILE)
    assert len(metrics) == case_count

    # Post rebuilds the statistics table from the metrics file alone.
    post_montecarlo(str(work_dir))
    result = pd.read_csv(work_dir / "result_table.csv")
    assert len(result) == case_count
    # Apogee altitude is deterministic (synthetic log), so every case must report it.
    assert (result['altitude_apogee'] == 400.0).all()


def test_montecarlo_writes_completion_manifest(monkeypatch, project_copy):
    """Resumability foundation: a normal run must record every completed case in the
    manifest, so an interrupted run can later skip them. Binary-independent."""
    from runner_tool.run_manifest import RunManifest

    case_count = 4

    def _fake_run_solver(solver_config_json_file_path, cwd=None):
        with open(solver_config_json_file_path) as f:
            cfg = json.load(f)
        _synthetic_flight_log().to_csv(f"{cfg['Model ID']}_stage1_flight_log.csv", index=False)
    monkeypatch.setattr("runner_tool.runner_single.run_solver", _fake_run_solver)

    disable_parachute(project_copy)
    _disable_all_mc_errors(project_copy / "config_montecarlo.json", case_count, output_all_logs=False)
    with chdir(str(project_copy)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")

    work_dir = list(project_copy.glob("work_montecarlo*"))[0]
    manifest_file = work_dir / RunManifest.FILENAME
    assert manifest_file.exists(), "completion manifest was not written"
    completed = {line.strip() for line in manifest_file.read_text().splitlines() if line.strip()}
    expected = {f"{i}_solver_config.json" for i in range(case_count)}
    assert completed == expected, f"manifest {completed} != expected {expected}"

    # The incremental metrics file must hold one row per case (stats-only mode).
    metrics = pd.read_csv(work_dir / CASE_METRICS_FILE)
    assert len(metrics) == case_count


def test_run_multi_skips_cases_recorded_in_manifest(monkeypatch, tmp_path):
    """run_multi must re-run only the cases NOT already in the manifest, and append the
    rest as they finish. This is the resume primitive that higher layers build on."""
    from runner_tool.run_manifest import RunManifest
    from runner_tool import runner_multi

    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    case_files = [f"{i}_solver_config.json" for i in range(5)]

    ran = []
    monkeypatch.setattr(runner_multi, "run_single", lambda f: ran.append(f))

    # Pretend cases 0 and 2 already completed in a prior (interrupted) run.
    manifest = RunManifest(str(tmp_path))
    manifest.mark("0_solver_config.json")
    manifest.mark("2_solver_config.json")

    runner_multi.run_multi(str(cases_dir), case_files, manifest=manifest)

    assert sorted(ran) == ["1_solver_config.json", "3_solver_config.json", "4_solver_config.json"]
    # All five are now recorded complete (the two pre-existing plus the three just run).
    assert manifest.completed() == set(case_files)


def test_watch_stop_flag_sets_event_when_file_appears(tmp_path):
    """The web service pauses a montecarlo subprocess by creating a stop-flag file;
    runner._watch_stop_flag must turn that into the stop_event the runner already honors.
    Cross-platform pause primitive (no signals)."""
    import threading
    import time
    import runner

    flag = tmp_path / "stop.flag"
    ev = threading.Event()
    runner._watch_stop_flag(str(flag), ev, poll_sec=0.02)
    assert not ev.is_set(), "event must stay clear until the flag file exists"

    flag.write_text("stop")
    for _ in range(200):  # up to ~4s; normally trips within one poll
        if ev.is_set():
            break
        time.sleep(0.02)
    assert ev.is_set(), "stop_event must be set once the flag file appears"


def test_run_multi_stop_event_pauses_without_starting_new_cases(monkeypatch, tmp_path):
    """A stop_event set before the pool runs must prevent any un-started case from
    running, and (crucially) those cases must stay OUT of the manifest so resume re-runs
    them. The cooperative pause primitive that the CLI's Ctrl-C handler drives."""
    import threading
    from runner_tool.run_manifest import RunManifest
    from runner_tool import runner_multi

    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    case_files = [f"{i}_solver_config.json" for i in range(4)]

    ran = []
    monkeypatch.setattr(runner_multi, "run_single", lambda f: ran.append(f))

    manifest = RunManifest(str(tmp_path))
    stop_event = threading.Event()
    stop_event.set()  # already paused: no case should start

    runner_multi.run_multi(str(cases_dir), case_files, manifest=manifest, stop_event=stop_event)

    assert ran == [], "no case should run once a stop was requested"
    assert manifest.completed() == set(), "un-started cases must not be marked complete"


def test_montecarlo_resume_runs_only_remaining_cases(monkeypatch, project_copy):
    """End-to-end resume: after an interruption, resume_montecarlo must re-run only the
    cases not recorded complete, reusing the existing per-case inputs (no re-sampling),
    and must not leave duplicate metric rows for a case whose metrics were written but
    not yet marked complete (orphan-row reconciliation). Binary-independent."""
    from runner_tool.run_manifest import RunManifest
    from runner_tool.runner_montecarlo import resume_montecarlo

    case_count = 5

    runs = []

    def _fake_run_solver(solver_config_json_file_path, cwd=None):
        with open(solver_config_json_file_path) as f:
            cfg = json.load(f)
        runs.append(cfg['Model ID'])
        _synthetic_flight_log().to_csv(f"{cfg['Model ID']}_stage1_flight_log.csv", index=False)
    monkeypatch.setattr("runner_tool.runner_single.run_solver", _fake_run_solver)

    disable_parachute(project_copy)  # one stage1 log per case, no ballistic split
    _disable_all_mc_errors(project_copy / "config_montecarlo.json", case_count, output_all_logs=False)
    with chdir(str(project_copy)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")

    work_dir = list(project_copy.glob("work_montecarlo*"))[0]
    assert len(runs) == case_count, "first run should execute every case once"
    assert len(pd.read_csv(work_dir / CASE_METRICS_FILE)) == case_count

    # Simulate an interruption after cases 0,1,2 were marked complete: rewind the manifest
    # to {0,1,2} but leave the metrics rows for 3 and 4 in place (orphans), so resume must
    # prune them before re-running 3 and 4 (else they'd be duplicated).
    manifest_path = work_dir / RunManifest.FILENAME
    manifest_path.write_text("\n".join(f"{i}_solver_config.json" for i in range(3)) + "\n")

    runs.clear()
    with chdir(str(project_copy)):
        resume_montecarlo("config_montecarlo.json", str(work_dir))

    # Only the unfinished cases re-run.
    reran = sorted({int(m.split('_', 1)[0]) for m in runs})
    assert reran == [3, 4], f"resume re-ran {reran}, expected [3, 4]"

    # Exactly one metric row per case — orphans pruned, no duplicates.
    metrics_after = pd.read_csv(work_dir / CASE_METRICS_FILE)
    assert sorted(metrics_after['case'].tolist()) == list(range(case_count))

    # Manifest is now complete; post rebuilds the full result table.
    assert RunManifest(str(work_dir)).completed() == {f"{i}_solver_config.json" for i in range(case_count)}
    post_montecarlo(str(work_dir))
    assert len(pd.read_csv(work_dir / "result_table.csv")) == case_count


def test_montecarlo_poi_file_mode_writes_scaled_per_case_files(monkeypatch, project_copy):
    """POI in file mode: each component whose error is enabled must get a per-case CSV
    holding the base curve scaled by a single multiplier, with the case rocket_param
    pointing at it. Case 0 is the unscaled nominal. Components without an enabled error
    keep the file copied by copy_config_files() and get no per-case file.

    Binary-independent: per-case files are written before run_multi, so a no-op solver
    is enough to exercise the staging logic.
    """
    case_count = 4
    np.random.seed(0)  # make the multiplier sampling deterministic for this test

    # Enable POI file mode with a known Ixy base curve; Ixz/Iyz exist but get no error.
    rp_path = project_copy / "param_rocket.json"
    rp = json.loads(rp_path.read_text())
    rp["Enable Product of Inertia"] = False
    rp["Enable Product of Inertia File"] = True
    rp.setdefault("Product of Inertia File", {})
    rp["Product of Inertia File"]["Ixy File Path"] = "poi_ixy.csv"
    rp["Product of Inertia File"]["Ixz File Path"] = "poi_ixz.csv"
    rp["Product of Inertia File"]["Iyz File Path"] = "poi_iyz.csv"
    rp_path.write_text(json.dumps(rp))

    base = np.array([[0.0, 2.0], [1.0, 4.0], [2.0, 6.0]])
    base_vals = base[:, 1]
    for comp in ("ixy", "ixz", "iyz"):
        np.savetxt(project_copy / f"poi_{comp}.csv", base, delimiter=",",
                   header=f"Time,{comp.capitalize()}", comments="")

    # Enable only POI Ixy error.
    mc_path = project_copy / "config_montecarlo.json"
    cfg = json.loads(mc_path.read_text())
    cfg["MonteCarlo Case Count"] = case_count
    cfg["Output All Case Logs"] = True
    for ep in cfg["Error Parameters"].values():
        if isinstance(ep, dict) and "Enable" in ep:
            ep["Enable"] = False
    cfg["Error Parameters"]["POI Ixy"] = {
        "Enable": True, "Error Unit": "%", "Error 3sigma Low": 30.0, "Error 3sigma High": 30.0,
    }
    mc_path.write_text(json.dumps(cfg))

    def _fake_run_solver(solver_config_json_file_path, cwd=None):
        with open(solver_config_json_file_path) as f:
            c = json.load(f)
        _synthetic_flight_log().to_csv(f"{c['Model ID']}_stage1_flight_log.csv", index=False)
    monkeypatch.setattr("runner_tool.runner_single.run_solver", _fake_run_solver)

    with chdir(str(project_copy)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")

    cases_dir = list(project_copy.glob("work_montecarlo*"))[0] / "cases"

    multipliers = []
    for i in range(case_count):
        poi_file = cases_dir / f"{i}_poi_Ixy.csv"
        assert poi_file.exists(), f"missing per-case POI Ixy file for case {i}"
        scaled = np.loadtxt(poi_file, delimiter=",", skiprows=1)[:, 1]
        m = scaled / base_vals
        assert np.allclose(m, m[0]), "a single multiplier must scale the whole curve"
        multipliers.append(m[0])
        rp_case = json.loads((cases_dir / f"{i}_rocket_param.json").read_text())
        assert rp_case["Product of Inertia File"]["Ixy File Path"] == f"{i}_poi_Ixy.csv"
        # Non-errored components are untouched (keep the copied basename, no per-case file).
        assert rp_case["Product of Inertia File"]["Ixz File Path"] == "poi_ixz.csv"

    assert np.isclose(multipliers[0], 1.0), "case 0 must be the unscaled nominal"
    assert any(abs(m - 1.0) > 0.01 for m in multipliers[1:]), "errored cases must be scaled"
    assert not list(cases_dir.glob("*_poi_Ixz.csv")), "Ixz has no error -> no per-case file"
    assert not list(cases_dir.glob("*_poi_Iyz.csv")), "Iyz has no error -> no per-case file"


def test_montecarlo_cases_are_self_contained(monkeypatch, project_copy):
    """Regression guard for the projects/** path-leak class of bug. The sample project ships
    with aero coefficients in constant mode, so we first enable every file input — that is the
    exact "file mode x non-varied input" path the original blind spot left untested. Every case
    config must then reference its inputs by a basename resolving inside cases/ — both when a
    parameter is NOT perturbed (the copied original) and when it IS perturbed (a per-case scaled
    file). Binary-independent: a no-op solver suffices since we only inspect generated configs."""
    enable_all_file_inputs(project_copy)

    def _fake_run_solver(solver_config_json_file_path, cwd=None):
        with open(solver_config_json_file_path) as f:
            c = json.load(f)
        _synthetic_flight_log().to_csv(f"{c['Model ID']}_stage1_flight_log.csv", index=False)
    monkeypatch.setattr("runner_tool.runner_single.run_solver", _fake_run_solver)

    def _run_and_get_cases_dir():
        # Identify the work dir created by THIS run via set-diff (project_copy may already
        # contain a stale work_montecarlo from a prior run, copied in by the fixture).
        before = set(project_copy.glob("work_montecarlo*"))
        with chdir(str(project_copy)):
            run_montecarlo("config_solver.json", "config_montecarlo.json")
        new_dirs = set(project_copy.glob("work_montecarlo*")) - before
        assert len(new_dirs) == 1, f"expected exactly one new work dir, got {new_dirs}"
        return new_dirs.pop() / "cases"

    # Scenario A: all errors disabled -> non-perturbed branch references copied basenames
    # (this is the exact path that previously leaked os.path.abspath(projects/**)).
    _disable_all_mc_errors(project_copy / "config_montecarlo.json", 2)
    assert_cases_self_contained(_run_and_get_cases_dir())

    # Scenario B: CA error enabled -> per-case scaled CA file; must also stay inside cases/.
    cfg = json.loads((project_copy / "config_montecarlo.json").read_text())
    for ep in cfg["Error Parameters"].values():
        if isinstance(ep, dict) and "Enable" in ep:
            ep["Enable"] = False
    cfg["Error Parameters"]["CA"] = {
        "Enable": True, "Error Unit": "%", "Error 3sigma Low": 10.0, "Error 3sigma High": 10.0,
    }
    (project_copy / "config_montecarlo.json").write_text(json.dumps(cfg))
    cases_b = _run_and_get_cases_dir()
    assert_cases_self_contained(cases_b)
    # Sanity: the perturbed CA files were actually written per-case inside cases/.
    assert list(cases_b.glob("*_CA.csv")), "CA error enabled but no per-case CA file written"


def test_montecarlo_stats_only_discards_logs_and_writes_metrics(binary_path, mc_post_supported, project_copy):
    """End-to-end (real solver): stats-only mode must delete per-case flight logs during
    the run and still produce result_table.csv from the metrics file."""
    if not mc_post_supported:
        pytest.skip("ForRocket binary does not emit all _MC_COLS yet (pending solver rebuild)")

    case_count = 2
    disable_parachute(project_copy)  # one stage1 log per case (no ballistic/decent split)
    _disable_all_mc_errors(project_copy / "config_montecarlo.json", case_count, output_all_logs=False)

    with chdir(str(project_copy)):
        run_montecarlo("config_solver.json", "config_montecarlo.json")

    work_dir = list(project_copy.glob("work_montecarlo*"))[0]

    leftover_logs = list((work_dir / "cases").glob("*_flight_log.csv"))
    assert not leftover_logs, f"flight logs were not discarded: {leftover_logs}"

    metrics_path = work_dir / CASE_METRICS_FILE
    assert metrics_path.is_file(), f"{CASE_METRICS_FILE} missing under {work_dir}"
    assert len(pd.read_csv(metrics_path)) == case_count

    post_montecarlo(str(work_dir))
    result_table = work_dir / "result_table.csv"
    assert result_table.is_file(), "result_table.csv was not produced in stats-only mode"
    assert len(pd.read_csv(result_table)) == case_count


def test_montecarlo_stats_only_matches_full_statistics(binary_path, mc_post_supported, projects_dir, tmp_path):
    """End-to-end (real solver): with all errors disabled the cases are deterministic, so
    the stats-only result table must match the full-log result table value-for-value."""
    if not mc_post_supported:
        pytest.skip("ForRocket binary does not emit all _MC_COLS yet (pending solver rebuild)")

    case_count = 2

    def _run(name: str, output_all_logs: bool) -> pd.DataFrame:
        proj = copy_example(projects_dir, tmp_path / name)
        disable_parachute(proj)  # single result_table.csv (no ballistic/decent split)
        _disable_all_mc_errors(proj / "config_montecarlo.json", case_count, output_all_logs)
        with chdir(str(proj)):
            run_montecarlo("config_solver.json", "config_montecarlo.json")
        work_dir = list(proj.glob("work_montecarlo*"))[0]
        post_montecarlo(str(work_dir))
        return pd.read_csv(work_dir / "result_table.csv")

    full = _run("example_full", True)
    stats_only = _run("example_stats", False)

    assert list(full.columns) == list(stats_only.columns)
    np.testing.assert_allclose(full.to_numpy(), stats_only.to_numpy(), rtol=1e-6, atol=1e-6)


def test_area_produces_per_case_flight_logs(binary_path, project_copy):
    # Minimal 2-case wind grid: 2 speeds × 1 direction.
    # Reference Height is set high so the power-law extrapolation in law_wind
    # produces tiny (not divergent) wind values at altitude — the solver would
    # otherwise hang on garbage input. This is a known wind-generator quirk;
    # we just want to verify orchestration, not stress the wind model.
    area_cfg = {
        "Law Wind": {
            "Wind Characteristic Coefficient": 0.143,
            "Reference Height [m]": 20000.0,
            "Reference Wind Speed Lower Limit [m/s]": 1.0,
            "Reference Wind Speed Upper Limit [m/s]": 2.0,
            "Reference Wind Speed Step [m/s]": 1.0,
            "Wind Direction Lower Limit [deg]": 0.0,
            "Wind Direction Upper Limit [deg]": 0.0,
            "Wind Direction Step [deg]": 10.0,
        }
    }
    (project_copy / "config_area.json").write_text(json.dumps(area_cfg))

    with chdir(str(project_copy)):
        run_area("config_solver.json", "config_area.json")

    work_dirs = list(project_copy.glob("work_area*"))
    assert work_dirs, "no work_area directory was created"
    logs = list(work_dirs[0].glob("*_stage1_flight_log.csv"))
    assert len(logs) >= 2, f"expected >=2 flight logs in {work_dirs[0]}, got {len(logs)}"
