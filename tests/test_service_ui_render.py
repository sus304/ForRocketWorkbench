"""Tests for the service-native result rendering logic (design §11.5, Phase 9).

The new GUI renders results directly from a service work_dir (use case ②), with no dependency
on the legacy Calculation DB. These cover the pure, DB-free helpers the NiceGUI cards are built
on — file discovery, summary parsing, unit rescaling, chart option assembly and the impact
ellipse maths ported from the legacy result page.
"""
import numpy as np
import pandas as pd

from web.service_ui import render


# --- file discovery ----------------------------------------------------------

def test_find_flight_logs_dedupes_by_stem(tmp_path):
    (tmp_path / "0_flight_log.csv").write_text("t,x\n0,0\n")
    sub = tmp_path / "result_0"
    sub.mkdir()
    (sub / "0_flight_log.csv").write_text("t,x\n0,0\n")
    (tmp_path / "1_flight_log.csv").write_text("t,x\n0,0\n")
    logs = render.find_flight_logs(str(tmp_path))
    stems = sorted(__import__("pathlib").Path(f).stem for f in logs)
    assert stems == ["0_flight_log", "1_flight_log"]


def test_find_flight_logs_missing_dir():
    assert render.find_flight_logs("/no/such/dir") == []


def test_find_summaries(tmp_path):
    r = tmp_path / "result_0"
    r.mkdir()
    (r / "_summary.txt").write_text("Apogee Altitude, 1000 [m]\n")
    assert render.find_summaries(str(tmp_path)) == [str(r / "_summary.txt")]


def test_find_mc_result_tables(tmp_path):
    (tmp_path / "result_table.csv").write_text("altitude_apogee\n1\n")
    (tmp_path / "ballistic_result_table.csv").write_text("altitude_apogee\n1\n")
    tables = render.find_mc_result_tables(str(tmp_path))
    labels = [lbl for lbl, _ in tables]
    assert "" in labels and "Ballistic" in labels
    assert "Descent" not in labels  # not present


# --- summary parsing ---------------------------------------------------------

def test_parse_summary_splits_key_value_unit(tmp_path):
    p = tmp_path / "_summary.txt"
    p.write_text(
        "Apogee Altitude, 12345.6 [m]\n"
        "Max Mach, 3.21 [-]\n"
        "Note, no unit here\n"
        "\n"
    )
    items = render.parse_summary(str(p))
    assert ("Apogee Altitude", "12345.6", "[m]") in items
    assert ("Max Mach", "3.21", "[-]") in items
    assert ("Note", "no unit here", "") in items


def test_get_event_positions_maps_times_to_track():
    df = pd.DataFrame({
        "Time [s]": [0.0, 1.0, 2.0, 3.0],
        "Latitude [deg]": [35.0, 35.1, 35.2, 35.3],
        "Longitude [deg]": [139.0, 139.1, 139.2, 139.3],
        "Altitude [m]": [0.0, 100.0, 200.0, 50.0],
    })
    items = [("Apogee Time", "2.0", "[s]"), ("Landing Time", "3.0", "[s]")]
    events = render.get_event_positions(items, df)
    labels = [e[0] for e in events]
    assert any(l.startswith("Apogee") for l in labels)
    assert any(l.startswith("Landing") for l in labels)
    apogee = next(e for e in events if e[0].startswith("Apogee"))
    assert apogee[1] == 35.2 and apogee[3] == 200.0  # lat / alt at t=2s


# --- unit / formatting -------------------------------------------------------

def test_auto_km_rescales_large_metres():
    vals = [0.0, 50_000.0, 100_000.0]
    scaled, label = render._auto_km("Altitude [m]", vals)
    assert label == "Altitude [km]"
    assert scaled[-1] == 100.0


def test_auto_km_keeps_small_metres():
    vals = [0.0, 100.0, 500.0]
    scaled, label = render._auto_km("Downrange [m]", vals)
    assert label == "Downrange [m]" and scaled == vals


def test_fmtv_avoids_scientific_notation():
    assert "e" not in render._fmtv(123456.0).lower()
    assert render._fmtv(0.001234).count(".") == 1


# --- chart options -----------------------------------------------------------

def test_echart_opts_has_series_data():
    df = pd.DataFrame({"Time [s]": [0, 1, 2], "Altitude [m]": [0, 10, 20]})
    opts = render._echart_opts(df, "Time [s]", "Altitude [m]")
    assert opts["series"][0]["type"] == "line"
    assert len(opts["series"][0]["data"]) == 3


def test_mc_histogram_opts_reports_mean_std():
    opts = render._mc_histogram_opts([1.0, 2.0, 3.0, 4.0, 5.0], "Apogee", "km", "#42a5f5")
    assert "μ" in opts["title"]["subtext"] and "σ" in opts["title"]["subtext"]
    assert opts["series"][0]["type"] == "bar"


# --- impact ellipses ---------------------------------------------------------

def test_compute_impact_ellipses_shapes():
    rng = np.random.default_rng(0)
    lats = (35.0 + rng.normal(0, 0.01, 200)).tolist()
    lons = (139.0 + rng.normal(0, 0.01, 200)).tolist()
    east, north, mlat, mlon, ne_ell, ll_ell = render.compute_impact_ellipses(lats, lons)
    assert len(east) == len(north) == 200
    assert abs(mlat - 35.0) < 0.01 and abs(mlon - 139.0) < 0.01
    assert [n for n, _, _ in ne_ell] == [1, 2, 3]  # 1σ/2σ/3σ
    # each ellipse polyline is closed (first point repeated at the end)
    for _n, _clr, pts in ll_ell:
        assert pts[0] == pts[-1]


def test_compute_impact_ellipses_too_few_points():
    east, north, _, _, ne_ell, ll_ell = render.compute_impact_ellipses([35.0, 35.1], [139.0, 139.1])
    assert len(east) == 2 and ne_ell == [] and ll_ell == []


# --- API response converters (design §6) -------------------------------------

def test_table_to_df_roundtrip():
    df = render.table_to_df({"columns": ["case", "downrange_impact"],
                             "rows": [[0, 1000.0], [1, 2000.0]]})
    assert list(df.columns) == ["case", "downrange_impact"]
    assert df["downrange_impact"].tolist() == [1000.0, 2000.0]


def test_extract_log_to_df_coerces_numeric():
    df = render.extract_log_to_df({"columns": ["Time [s]", "Altitude [m]"],
                                   "rows": [["0.0", "100"], ["0.5", "110"]]})
    assert df["Altitude [m]"].tolist() == [100, 110]
    assert str(df["Time [s]"].dtype).startswith("float")


def test_summary_items_from_api_shape():
    items = render.summary_items_from_api([{"key": "apogee", "value": "3000", "unit": "[m]"}])
    assert items == [("apogee", "3000", "[m]")]
    assert render.summary_items_from_api(None) == []


def test_mc_table_labels_cover_result_tables():
    assert render._MC_TABLE_LABELS["ballistic_result_table"] == "Ballistic"
    assert render._MC_TABLE_LABELS["result_table"] == ""
