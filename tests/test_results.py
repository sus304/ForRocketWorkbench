"""Contract tests for service.results — the pure result-inspection layer behind the remote
result API (docs/result_retrieval_design.md §4). No HTTP here; the FastAPI wiring (step 4) is
tested separately. Binary-free: a synthetic Monte Carlo work_dir is built on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from service import results


_FLIGHT_HEADER = "Time [s],Altitude [m],Latitude [deg],Longitude [deg],Airspeed [m/s]"


def _write_flight_log(path: Path, n_points: int = 5):
    lines = [_FLIGHT_HEADER]
    for i in range(n_points):
        t = i * 0.5
        lines.append(f"{t},{100.0 + i},{35.0 + i * 0.01},{139.0 + i * 0.01},{50.0 + i}")
    path.write_text("\n".join(lines) + "\n")


def _write_result_table(path: Path, cases_metrics):
    """cases_metrics: list of (case, downrange_impact, lat_impact, lon_impact)."""
    header = ("case,maxQ,mach,time_apogee,altitude_apogee,vel_apogee,"
              "downrange_impact,lat_impact,lon_impact,peak_total_aoa")
    lines = [header]
    for case, dr, lat, lon in cases_metrics:
        lines.append(f"{case},50000,1.5,20,3000,150,{dr},{lat},{lon},4.0")
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def mc_work_dir(tmp_path) -> Path:
    """Synthetic keep-logs MC work_dir with descent+ballistic split, 4 cases."""
    wd = tmp_path / "work_montecarlo"
    cases = wd / "cases"
    cases.mkdir(parents=True)
    n = 4
    for c in range(n):
        _write_flight_log(cases / f"{c}_stage1_flight_log.csv")
        _write_flight_log(cases / f"{c}_ballistic_flight_log.csv")
    # one IIP log present (case 0 stage1 only) to exercise availability reporting
    (cases / "0_stage1_iip_log.csv").write_text("Time [s],IIP Lat [deg],IIP Lon [deg]\n0,35,139\n")
    # stage1 (descent) metrics: downrange increases with case index; ballistic differs
    _write_result_table(wd / "decent_result_table.csv",
                        [(c, 1000 * (c + 1), 35 + c, 139) for c in range(n)])
    _write_result_table(wd / "ballistic_result_table.csv",
                        [(c, 5000 - 500 * c, 36 + c, 140) for c in range(n)])
    (wd / "_summary.txt").write_text("apogee,3000 [m]\nmax Q,50000 [Pa]\n")
    return wd


def test_meta_reports_tables_phases_columns(mc_work_dir):
    meta = results.result_meta(str(mc_work_dir), "montecarlo")
    assert meta["mode"] == "montecarlo"
    assert set(meta["tables"]) == {"decent_result_table", "ballistic_result_table"}
    assert meta["case_count"] == 4
    assert set(meta["phases"]) == {"stage1", "ballistic"}
    assert "Time [s]" in meta["flight_columns"]
    assert "downrange_impact" in meta["metrics_columns"]
    assert meta["iip_available"] is True


def test_read_table_whitelist_and_content(mc_work_dir):
    tbl = results.read_table(str(mc_work_dir), "ballistic_result_table")
    assert "case" in tbl["columns"]
    assert "downrange_impact" in tbl["columns"]
    assert len(tbl["rows"]) == 4
    with pytest.raises(results.ResultError):
        results.read_table(str(mc_work_dir), "../../etc/passwd")
    with pytest.raises(results.ResultError):
        results.read_table(str(mc_work_dir), "nonexistent_table")


def test_resolve_select_nominal_and_ids(mc_work_dir):
    assert [r["case"] for r in results.resolve_select(str(mc_work_dir), "nominal")] == [0]
    ids = results.resolve_select(str(mc_work_dir), "id:2,0,3")
    assert sorted(r["case"] for r in ids) == [0, 2, 3]


def test_resolve_select_top_bottom_by_phase(mc_work_dir):
    # stage1 downrange increases with case -> top 2 are cases 3 and 2
    top = results.resolve_select(str(mc_work_dir), "top:2:downrange_impact:stage1")
    assert [r["case"] for r in top] == [3, 2]
    # ballistic downrange decreases with case -> top 2 are cases 0 and 1
    top_b = results.resolve_select(str(mc_work_dir), "top:2:downrange_impact:ballistic")
    assert [r["case"] for r in top_b] == [0, 1]
    # bottom of stage1 -> smallest downrange first: case 0 then 1
    bot = results.resolve_select(str(mc_work_dir), "bottom:2:downrange_impact")
    assert [r["case"] for r in bot] == [0, 1]


def test_resolve_select_errors(mc_work_dir):
    with pytest.raises(results.ResultError):
        results.resolve_select(str(mc_work_dir), "top:2:no_such_metric")
    with pytest.raises(results.ResultError):
        results.resolve_select(str(mc_work_dir), "garbage")


def test_resolve_select_filter(mc_work_dir):
    # stage1 downrange = 1000*(case+1): >2500 -> cases 2,3
    hit = results.resolve_select(str(mc_work_dir), "filter:downrange_impact>2500:stage1")
    assert sorted(r["case"] for r in hit) == [2, 3]
    # ballistic downrange = 5000-500*case: <4000 -> cases 3 (3500) only... 5000,4500,4000,3500
    hit_b = results.resolve_select(str(mc_work_dir), "filter:downrange_impact<4000:ballistic")
    assert sorted(r["case"] for r in hit_b) == [3]
    # default phase stage1
    hit_d = results.resolve_select(str(mc_work_dir), "filter:downrange_impact<=2000")
    assert sorted(r["case"] for r in hit_d) == [0, 1]


def test_resolve_select_filter_errors(mc_work_dir):
    for bad in ("filter:no_such_metric>1", "filter:downrange_impact#1", "filter:downrange_impact>abc"):
        with pytest.raises(results.ResultError):
            results.resolve_select(str(mc_work_dir), bad)


def test_missing_work_dir_raises_gone(tmp_path):
    with pytest.raises(results.ResultsGone):
        results.result_meta(str(tmp_path / "does_not_exist"), "montecarlo")


def test_summaries_parsed(mc_work_dir):
    s = results.read_summaries(str(mc_work_dir))
    joined = {k: v for k, v, _ in s}
    assert "apogee" in joined


# ── KML discovery (design §9 / review N-7) ──────────────────────────────────

def test_kml_classify_ellipse_not_confused_with_envelope():
    # envelope and ellipse share the _impact_3sigma_envelop.kml suffix; the 'ellipse' token
    # is the only discriminator.
    assert results._classify_kml("decent_impact_3sigma_envelop.kml") == ("decent", "envelope")
    assert results._classify_kml("decent_ellipse_impact_3sigma_envelop.kml") == ("decent", "ellipse")
    assert results._classify_kml("_impact_3sigma_envelop.kml") == ("", "envelope")
    assert results._classify_kml("ellipse_impact_3sigma_envelop.kml") == ("", "ellipse")
    assert results._classify_kml("decent_impact_points.kml") == ("decent", "points")
    assert results._classify_kml("something_else.kml") == (None, None)


def test_list_kml_and_path(tmp_path):
    wd = tmp_path / "work_montecarlo"
    wd.mkdir()
    for fn in ("decent_impact_3sigma_envelop.kml", "decent_ellipse_impact_3sigma_envelop.kml",
               "decent_impact_points.kml", "ballistic_impact_points.kml"):
        (wd / fn).write_text("<kml/>")
    cat = results.list_kml(str(wd))
    assert cat["decent_envelope"] == "decent_impact_3sigma_envelop.kml"
    assert cat["decent_ellipse"] == "decent_ellipse_impact_3sigma_envelop.kml"
    assert cat["decent_points"] == "decent_impact_points.kml"
    assert cat["ballistic_points"] == "ballistic_impact_points.kml"
    assert results.kml_path(str(wd), "decent_ellipse").name == "decent_ellipse_impact_3sigma_envelop.kml"
    with pytest.raises(results.ResultError):
        results.kml_path(str(wd), "../../etc/passwd")


def test_list_kml_finds_trajectory_iip_at_depth_1(tmp_path):
    """Flight-path KML lives one level down in result_* and must be discoverable (the viewer's
    main target), while cases/ (huge in MC runs) is never scanned."""
    wd = tmp_path / "work_trajectory"
    (wd / "result_ROCKET-A_0_stage1").mkdir(parents=True)
    (wd / "result_ROCKET-A_0_stage1" / "_trajectory.kml").write_text("<kml/>")
    (wd / "result_ROCKET-A_0_stage1" / "_iip.kml").write_text("<kml/>")
    # a cases/ tree that must NOT be walked
    (wd / "cases" / "0").mkdir(parents=True)
    (wd / "cases" / "0" / "_trajectory.kml").write_text("<kml/>")

    cat = results.list_kml(str(wd))
    assert cat["trajectory"] == "result_ROCKET-A_0_stage1/_trajectory.kml"
    assert cat["iip"] == "result_ROCKET-A_0_stage1/_iip.kml"
    # nothing from cases/ leaked in
    assert not any("cases/" in v for v in cat.values())
    # kml_path resolves the discovered relative path
    assert results.kml_path(str(wd), "trajectory").name == "_trajectory.kml"
    assert results.kml_path(str(wd), "trajectory").parent.name == "result_ROCKET-A_0_stage1"


def test_list_kml_qualifies_duplicate_kinds_across_result_dirs(tmp_path):
    wd = tmp_path / "work_trajectory"
    for d in ("result_ROCKET-A_0_stage1", "result_ROCKET-A_0_stage2"):
        (wd / d).mkdir(parents=True)
        (wd / d / "_trajectory.kml").write_text("<kml/>")
    cat = results.list_kml(str(wd))
    # first (sorted) keeps the plain "trajectory" id; the second is dir-qualified → unique keys
    assert cat["trajectory"] == "result_ROCKET-A_0_stage1/_trajectory.kml"
    assert cat["result_ROCKET-A_0_stage2_trajectory"] == "result_ROCKET-A_0_stage2/_trajectory.kml"


def test_meta_cases_by_phase(mc_work_dir):
    meta = results.result_meta(str(mc_work_dir), "montecarlo")
    assert sorted(meta["cases_by_phase"]["stage1"]) == [0, 1, 2, 3]
    assert sorted(meta["cases_by_phase"]["ballistic"]) == [0, 1, 2, 3]
    assert "kml" in meta


# ── extract (design §4.2) ───────────────────────────────────────────────────

def test_extract_columns_and_phase(mc_work_dir):
    ex = results.extract(str(mc_work_dir), select="id:1", phase="stage1", kind="flight",
                         columns=["Altitude [m]"])
    assert len(ex["logs"]) == 1
    log = ex["logs"][0]
    assert log["case"] == 1 and log["phase"] == "stage1"
    # time column is always included even though only Altitude was requested
    assert log["columns"] == ["Time [s]", "Altitude [m]"]
    assert log["n_points"] == 5


def test_extract_phase_all_returns_both(mc_work_dir):
    ex = results.extract(str(mc_work_dir), select="id:0", phase="all", kind="flight")
    phases = sorted(log["phase"] for log in ex["logs"])
    assert phases == ["ballistic", "stage1"]


def test_extract_decimation_keeps_endpoints(mc_work_dir):
    ex = results.extract(str(mc_work_dir), select="id:0", phase="stage1", kind="flight",
                         max_points=3)
    log = ex["logs"][0]
    assert log["n_points"] == 3
    assert log["decimated"] is True
    tcol = log["columns"].index("Time [s]")
    times = [row[tcol] for row in log["rows"]]
    assert times[0] == 0.0 and times[-1] == 2.0  # first & last preserved (5 pts, t=0..2)


def test_extract_time_window(mc_work_dir):
    ex = results.extract(str(mc_work_dir), select="id:0", phase="stage1", kind="flight",
                         t_start=0.5, t_end=1.5)
    log = ex["logs"][0]
    tcol = log["columns"].index("Time [s]")
    times = [row[tcol] for row in log["rows"]]
    assert min(times) >= 0.5 and max(times) <= 1.5


def test_extract_iip_partial_success(mc_work_dir):
    # only case 0 stage1 has an IIP log in the fixture
    ex = results.extract(str(mc_work_dir), select="id:0,1", phase="stage1", kind="iip")
    got = {log["case"] for log in ex["logs"]}
    missing = {m["case"] for m in ex["missing"]}
    assert got == {0}
    assert missing == {1}


def test_extract_limits(mc_work_dir):
    with pytest.raises(results.ResultError):
        results.extract(str(mc_work_dir), select="id:0", max_points=results.MAX_POINTS_CAP + 1)
    # max_points=0 (no decimation) only allowed for few cases
    with pytest.raises(results.ResultError):
        results.extract(str(mc_work_dir), select="id:0,1,2,3", max_points=0)
    ok = results.extract(str(mc_work_dir), select="id:0", max_points=0)
    assert ok["logs"][0]["n_points"] == 5

    with pytest.raises(results.ResultError):
        results.extract(str(mc_work_dir), select="id:0", columns=["No Such Column"])


def test_extract_nan_inf_becomes_null(tmp_path):
    """Real flight logs contain NaN/Inf; the JSON payload must carry None, not non-finite floats
    (FastAPI's encoder rejects those). Regression for the E2E ValueError."""
    import json
    wd = tmp_path / "work_montecarlo"
    (wd / "cases").mkdir(parents=True)
    (wd / "cases" / "0_stage1_flight_log.csv").write_text(
        "Time [s],Altitude [m]\n0,100\n0.5,nan\n1.0,inf\n")
    ex = results.extract(str(wd), select="id:0", phase="stage1", kind="flight", max_points=0)
    rows = ex["logs"][0]["rows"]
    alt = [r[1] for r in rows]
    assert alt[0] == 100 and alt[1] is None and alt[2] is None
    json.dumps(rows)  # must not raise
