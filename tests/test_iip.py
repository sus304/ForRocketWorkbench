"""IIP（瞬間落下点）計算の回帰テスト。

- 2 手法（Ahn-Roh 閉形式 / 数値弾道伝播）が一致することを保証。
- ForRocket ECI の ω·t フレーム規約が正しく反映されることをガード。
- example flight_log があれば post_iip の出力一式とサニティ（着地直前の IIP≒実着地）を確認。

合成 ECI 状態を使うコア部分はバイナリ非依存で常に走る。
"""
import math
import os
from pathlib import Path

import numpy as np
import pytest
import matplotlib
matplotlib.use("Agg")  # headless: post_iip がプロットを生成するため

from lib.coordinate import DCM_ECEF2NED, DCM_ECI2ECEF, LLH2ECEF, vel_ECEF2ECI
from post_tool.post_iip import iip_ahn_roh, iip_numerical, should_run_iip

EXAMPLE_LOG = Path("/home/susumu/ForRocket/examples/sample_stage1_flight_log.csv")


def _eci_state(lat, lon, alt, v_ned, t):
    """打上点 LLH + NED 速度 + ミッション時刻 t から ForRocket 流の ECI 状態を作る。"""
    llh = np.array([lat, lon, alt], dtype=float)
    r_ecef = LLH2ECEF(llh)
    v_ecef = DCM_ECEF2NED(llh).T.dot(np.asarray(v_ned, dtype=float))  # NED -> ECEF
    R = DCM_ECI2ECEF(t)
    r_eci = R.T.dot(r_ecef)
    v_eci = vel_ECEF2ECI(v_ecef, R, r_eci)
    return r_eci, v_eci


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# (lat, lon, alt_m, [vN, vE, vD] m/s, t_s) — いずれも亜軌道・非鉛直
_CASES = [
    (35.0, 140.0, 30000.0, [100.0, 700.0, -1400.0], 50.0),
    (35.0, 140.0, 60000.0, [200.0, 1200.0, -800.0], 150.0),
    (0.0, 100.0, 80000.0, [50.0, 1500.0, -300.0], 300.0),
    (40.0, 132.0, 50000.0, [-300.0, 900.0, -1000.0], 500.0),
]


@pytest.mark.parametrize("lat,lon,alt,v_ned,t", _CASES)
def test_two_methods_agree(lat, lon, alt, v_ned, t):
    """Ahn-Roh 閉形式と数値弾道伝播が落下点・落下時間で一致する。"""
    r, v = _eci_state(lat, lon, alt, v_ned, t)
    tof_a, lat_a, lon_a = iip_ahn_roh(r, v, t)
    tof_n, lat_n, lon_n = iip_numerical(r, v, t, dt=0.5)

    assert np.isfinite(lat_a) and np.isfinite(lat_n)
    dist = _haversine_m(lat_a, lon_a, lat_n, lon_n)
    assert dist < 50.0, f"impact-point mismatch {dist:.1f} m"
    assert abs(tof_a - tof_n) < 1.0, f"tof mismatch {abs(tof_a - tof_n):.3f} s"


def test_eci_frame_t_term_applied():
    """ForRocket ECI は ω·t 累積するため、落下点経度に t 項が効く必要がある。
    同一慣性状態でも t を無視すると経度が大きくずれる＝回帰ガード。"""
    r, v = _eci_state(35.0, 140.0, 60000.0, [200.0, 1200.0, -800.0], 400.0)
    _, _, lon_correct = iip_ahn_roh(r, v, 400.0)
    _, _, lon_ignore_t = iip_ahn_roh(r, v, 0.0)
    # 400 s 分の地球自転 ≈ 1.67°。t を落とすとこれだけずれるはず。
    assert abs(lon_correct - lon_ignore_t) > 1.0


def test_escape_velocity_is_nan():
    """脱出速度域（lam=(v/vc)^2 >= 2）は落下点が存在しないので NaN を返す。"""
    r, v = _eci_state(0.0, 100.0, 80000.0, [0.0, 12000.0, 0.0], 10.0)  # 東向き超高速
    tof, lat, lon = iip_ahn_roh(r, v, 10.0)
    assert math.isnan(lat) and math.isnan(lon) and math.isnan(tof)


def test_should_run_iip_apogee_gate():
    """頂点高度ゲート: 小型(2-3km)は自動スキップ、大型は実行、強制ON/OFFは上書き。"""
    import pandas as pd
    small = pd.DataFrame({"Altitude [m]": [0.0, 1500.0, 2500.0, 1000.0]})
    big = pd.DataFrame({"Altitude [m]": [0.0, 30000.0, 90000.0, 100.0]})

    assert should_run_iip(small) is False        # 既定10km未満 → スキップ
    assert should_run_iip(big) is True           # 大型 → 実行
    assert should_run_iip(small, iip=True) is True    # 強制ON
    assert should_run_iip(big, iip=False) is False    # 強制OFF
    assert should_run_iip(small, min_apogee=1000.0) is True  # しきい値上書き


@pytest.mark.skipif(not EXAMPLE_LOG.exists(), reason="example flight_log not available")
def test_post_iip_outputs_and_sanity(tmp_path):
    """post_iip が出力一式を生成し、着地直前の IIP が実着地点に収束する。"""
    import pandas as pd
    from post_tool.post_df import csv2df
    from post_tool.post_iip import post_iip

    df_all, _, _ = csv2df(str(EXAMPLE_LOG))
    prefix = os.path.join(str(tmp_path), "")
    post_iip(df_all, prefix)

    for suf in ("_iip_log.csv", "_iip_track.png", "_iip_timehistory.png", "_iip.kml"):
        assert os.path.exists(prefix + suf), f"missing output {suf}"

    log = pd.read_csv(prefix + "_iip_log.csv")
    valid = log["IIP Latitude [deg]"].notna()
    assert valid.sum() > 0

    # 真空 IIP は着地直前（残留速度小）で実着地点に収束する
    last = log[valid].iloc[-1]
    actual_dr = abs(float(df_all["Downrange [m]"].iloc[-1]))
    iip_dr = float(last["IIP Downrange from Launch [m]"])
    assert abs(iip_dr - actual_dr) < 0.05 * actual_dr + 500.0, (
        f"last IIP downrange {iip_dr:.1f} vs actual landing {actual_dr:.1f}"
    )


@pytest.mark.skipif(not EXAMPLE_LOG.exists(), reason="example flight_log not available")
def test_mc_per_case_iip_writer(tmp_path):
    """MC(ログ非削除)用 per-case IIP ライタ: 正常ログは書き出し、ECI 無しはスキップ。"""
    import glob
    import shutil
    import pandas as pd
    from path_define import chdir
    from post_tool.post_montecarlo import _run_case_pipeline, _iip_counts

    shutil.copy(str(EXAMPLE_LOG), str(tmp_path / "01_stage1_flight_log.csv"))
    df = pd.read_csv(str(EXAMPLE_LOG))
    df[[c for c in df.columns if "ECI" not in c]].to_csv(
        str(tmp_path / "02_stage1_flight_log.csv"), index=False)  # ECI 列なし（minimum_dump 模擬）

    with chdir(str(tmp_path)):
        results = _run_case_pipeline(glob.glob("*_flight_log.csv"))
    counts = _iip_counts(results)

    assert counts == {'written': 1, 'no_eci': 1, 'small': 0}
    assert (tmp_path / "01_stage1_iip_log.csv").exists()       # 19km級 → ゲート通過
    assert not (tmp_path / "02_stage1_iip_log.csv").exists()   # ECI 無し → スキップ


@pytest.mark.skipif(not EXAMPLE_LOG.exists(), reason="example flight_log not available")
def test_mc_per_case_iip_gate_skips_small(tmp_path):
    """頂点高度ゲート: 強制 OFF（または小型）なら MC でも全件スキップ。"""
    import glob
    import shutil
    from path_define import chdir
    from post_tool.post_montecarlo import _run_case_pipeline, _iip_counts

    shutil.copy(str(EXAMPLE_LOG), str(tmp_path / "01_stage1_flight_log.csv"))
    with chdir(str(tmp_path)):
        counts = _iip_counts(_run_case_pipeline(glob.glob("*_flight_log.csv"), iip=False))
    assert counts == {'written': 0, 'no_eci': 0, 'small': 1}
    assert not (tmp_path / "01_stage1_iip_log.csv").exists()
