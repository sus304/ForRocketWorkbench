"""Instantaneous Impact Point (IIP) time-history calculation.

真空（抗力なし・二体重力）での瞬間落下点を、ForRocket の flight_log に記録された
慣性系状態（X/Y/Z-ECI [km], Vx/Vy/Vz-ECI [m/s]）から計算する。

2 手法を実装:
  1. iip_ahn_roh()  : 閉形式（Ahn & Roh 2012, JGCD の非反復IIP）。
                      ForRocket src/dynamics/noniterative_iip.cpp の移植 + バグ修正。
  2. iip_numerical(): ECI 二体重力での RK4 弾道伝播による独立リファレンス。

両者とも ECEF への変換は DCM_ECI2ECEF(t+tof) を用い、最終 lat/lon は
lib.coordinate.ECEF2LLH（測地緯度）で求める（手法間で同一基準）。

ForRocket の ECI は ECI≡ECEF@t=0 規約で時刻 t に ω·t 分回転している点に注意。
落下点 ECEF 経度には ω·(t + tof) を反映する（cpp は ω·tof のみで t 分が欠落）。
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from lib import wgs84
from lib.coordinate import DCM_ECI2ECEF, ECEF2LLH
from post_tool.post_kml import dump_iip_kml


def _wrap_deg(lon_deg):
    """経度を [-180, 180) に正規化。"""
    return (lon_deg + 180.0) % 360.0 - 180.0


def _ecef2llh_vec(pos_ecef):
    """ECEF 座標配列 (N,3)[m] → 測地 (lat_deg, lon_deg)。lib.coordinate.ECEF2LLH のベクトル版。"""
    x, y, z = pos_ecef[:, 0], pos_ecef[:, 1], pos_ecef[:, 2]
    p = np.sqrt(x ** 2 + y ** 2)
    theta = np.arctan2(z * wgs84.a, p * wgs84.b)
    e_dash2 = (wgs84.a ** 2 - wgs84.b ** 2) / wgs84.b ** 2
    lat = np.arctan2(z + e_dash2 * wgs84.b * np.sin(theta) ** 3,
                     p - wgs84.e_square * wgs84.a * np.cos(theta) ** 3)
    lon = np.arctan2(y, x)
    return np.degrees(lat), np.degrees(lon)


# ---------------------------------------------------------------------------
# Method 1: Ahn & Roh (2012) closed-form non-iterative IIP
# ---------------------------------------------------------------------------
def _iip_ahn_roh_vec(pos_eci, vel_eci, t, n_iter=12):
    """閉形式 IIP のベクトル版。pos/vel: (N,3)[m,m/s], t: (N,)[s]。

    Returns: (tof, lat_deg, lon_deg) いずれも (N,) 配列。計算不能行は NaN。
    rp（楕円体地心距離）は全行一括の固定回数反復で収束させる（行ごとの収束判定は省く）。
    """
    a, e, GM, omega = wgs84.a, wgs84.e, wgs84.GM, wgs84.omega
    pos = np.asarray(pos_eci, dtype=float)
    vel = np.asarray(vel_eci, dtype=float)
    t = np.asarray(t, dtype=float)

    with np.errstate(all='ignore'):  # 無効行（lam>=2 等）の警告は抑止し、最後に NaN マスク
        r0 = np.linalg.norm(pos, axis=1)
        v0 = np.linalg.norm(vel, axis=1)
        ir0 = pos / r0[:, None]
        iv0 = vel / v0[:, None]
        vc = np.sqrt(GM / r0)                         # 円軌道速度
        gamma0 = np.arcsin(np.clip(np.sum(ir0 * iv0, axis=1), -1.0, 1.0))  # 慣性経路角
        lam = (v0 / vc) ** 2                          # 速度比の二乗
        cos_g = np.cos(gamma0)
        tan_g = np.tan(gamma0)

        rp = np.full_like(r0, 0.5 * (wgs84.a + wgs84.b))
        ip = sin_phi = cos_phi = phi = None
        for _ in range(n_iter):
            c0 = -tan_g
            c1 = 1.0 - 1.0 / (lam * cos_g ** 2)
            c2 = r0 / rp - 1.0 / (lam * cos_g ** 2)
            disc = np.clip(c0 ** 2 * c2 ** 2 - (c0 ** 2 + c1 ** 2) * (c2 ** 2 - c1 ** 2), 0.0, None)
            sin_phi = np.clip((c0 * c2 + np.sqrt(disc)) / (c0 ** 2 + c1 ** 2), -1.0, 1.0)
            cos_phi = np.sqrt(1.0 - sin_phi ** 2)
            phi = np.arcsin(sin_phi)
            k0 = np.cos(gamma0 + phi) / cos_g
            k1 = sin_phi / cos_g
            ip = k0[:, None] * ir0 + k1[:, None] * iv0
            ipn = np.linalg.norm(ip, axis=1)
            lat_eci = np.arcsin(np.clip(ip[:, 2] / ipn, -1.0, 1.0))  # 地心緯度
            rp = a * np.sqrt(1.0 - (e * np.sin(lat_eci)) ** 2)

        # 飛行時間 tof（Ahn & Roh の閉形式）
        denom = (2.0 - lam) * ((1.0 - cos_phi) / (lam * cos_g ** 2) + np.cos(gamma0 + phi) / cos_g)
        tf1 = (tan_g * (1.0 - cos_phi) + (1.0 - lam) * sin_phi) / denom
        tf2 = (2.0 * cos_g / (lam * (2.0 / lam - 1.0) ** 1.5)) \
            * np.arctan2(np.sqrt(2.0 / lam - 1.0), cos_g / np.tan(phi * 0.5) - np.sin(gamma0))
        tof = r0 / (v0 * cos_g) * (tf1 + tf2)

        # 落下時刻 t+tof の ECEF 経由で測地 LLH（地心/測地緯度・経度オフセットを一括処理）
        ipn = np.linalg.norm(ip, axis=1)
        P = rp[:, None] * ip / ipn[:, None]
        xi = omega * (t + tof)                        # z 軸まわり ECI->ECEF 回転
        cx, sx = np.cos(xi), np.sin(xi)
        pos_ecef = np.stack([cx * P[:, 0] + sx * P[:, 1],
                             -sx * P[:, 0] + cx * P[:, 1],
                             P[:, 2]], axis=1)
        lat, lon = _ecef2llh_vec(pos_ecef)

    # 計算不能行を NaN に（鉛直近傍 cos_g→0・非束縛 lam>=2・退化）
    bad = ((r0 <= 0.0) | (v0 <= 0.0) | (np.abs(cos_g) < 1e-8)
           | (lam <= 0.0) | (lam >= 2.0) | ~np.isfinite(tof) | (tof < 0.0))
    tof = np.where(bad, np.nan, tof)
    lat = np.where(bad, np.nan, lat)
    lon = np.where(bad, np.nan, _wrap_deg(lon))
    return tof, lat, lon


def iip_ahn_roh(pos_eci, vel_eci, t=0.0):
    """閉形式 IIP（単一状態）。`_iip_ahn_roh_vec` の薄いラッパ。

    Args:
        pos_eci, vel_eci: 慣性系位置 [m] / 速度 [m/s]（ForRocket ECI）。
        t: ミッション時刻 [s]（ECI の ω·t オフセット補正に必要）。
    Returns:
        (tof[s], lat_deg, lon_deg) または計算不能時 (nan, nan, nan)。
    """
    tof, lat, lon = _iip_ahn_roh_vec(
        np.atleast_2d(np.asarray(pos_eci, dtype=float)),
        np.atleast_2d(np.asarray(vel_eci, dtype=float)),
        np.atleast_1d(np.asarray(t, dtype=float)))
    return float(tof[0]), float(lat[0]), float(lon[0])


# ---------------------------------------------------------------------------
# Method 2: numerical two-body ballistic propagation (independent reference)
# ---------------------------------------------------------------------------
def _two_body_accel(r_eci):
    r = np.linalg.norm(r_eci)
    return -wgs84.GM / r ** 3 * r_eci


def _altitude_at(r_eci, t_abs):
    pos_ecef = DCM_ECI2ECEF(t_abs).dot(r_eci)
    return ECEF2LLH(pos_ecef)[2]


def iip_numerical(pos_eci, vel_eci, t=0.0, dt=1.0, max_tof=2000.0):
    """ECI 二体重力での RK4 弾道伝播。高度が 0 を下向きに横切る点を落下点とする。

    Returns: (tof[s], lat_deg, lon_deg) または (nan, nan, nan)。
    """
    r = np.asarray(pos_eci, dtype=float).copy()
    v = np.asarray(vel_eci, dtype=float).copy()
    tau = 0.0
    alt_prev = _altitude_at(r, t + tau)

    while tau < max_tof:
        # RK4
        k1v = _two_body_accel(r)
        k1r = v
        k2v = _two_body_accel(r + 0.5 * dt * k1r)
        k2r = v + 0.5 * dt * k1v
        k3v = _two_body_accel(r + 0.5 * dt * k2r)
        k3r = v + 0.5 * dt * k2v
        k4v = _two_body_accel(r + dt * k3r)
        k4r = v + dt * k3v
        r_next = r + dt / 6.0 * (k1r + 2 * k2r + 2 * k3r + k4r)
        v_next = v + dt / 6.0 * (k1v + 2 * k2v + 2 * k3v + k4v)
        tau_next = tau + dt
        alt_next = _altitude_at(r_next, t + tau_next)

        if alt_prev > 0.0 and alt_next <= 0.0:
            # 線形補間で交差時刻を絞り込み（高度に対して）
            frac = alt_prev / (alt_prev - alt_next)
            tau_hit = tau + frac * dt
            r_hit = r + frac * (r_next - r)
            pos_ecef = DCM_ECI2ECEF(t + tau_hit).dot(r_hit)
            lat, lon, _ = ECEF2LLH(pos_ecef)
            return tau_hit, lat, _wrap_deg(lon)

        r, v, tau, alt_prev = r_next, v_next, tau_next, alt_next

    return np.nan, np.nan, np.nan


# ---------------------------------------------------------------------------
# Time-history over a flight_log DataFrame
# ---------------------------------------------------------------------------
_ECI_POS_COLS = ["X-ECI [km]", "Y-ECI [km]", "Z-ECI [km]"]
_ECI_VEL_COLS = ["Vx-ECI [m/s]", "Vy-ECI [m/s]", "Vz-ECI [m/s]"]


def compute_iip_timehistory(df, method="ahn_roh"):
    """flight_log DataFrame から IIP 時間履歴を計算。

    Returns: dict(time, lat, lon, tof) の numpy 配列。
    """
    t_arr = df["Time [s]"].to_numpy()
    pos = df[_ECI_POS_COLS].to_numpy() * 1.0e3  # km -> m
    vel = df[_ECI_VEL_COLS].to_numpy()

    if method == "ahn_roh":
        tof, lat, lon = _iip_ahn_roh_vec(pos, vel, t_arr)  # ベクトル化（高速）
    else:  # numerical: 独立リファレンス、行ごとに伝播
        n = len(t_arr)
        lat = np.full(n, np.nan)
        lon = np.full(n, np.nan)
        tof = np.full(n, np.nan)
        for i in range(n):
            tof[i], lat[i], lon[i] = iip_numerical(pos[i], vel[i], t_arr[i])
    return {"time": t_arr, "lat": lat, "lon": lon, "tof": tof}


# ---------------------------------------------------------------------------
# WGS84 Vincenty inverse (surface distance) — IIP の打上点からの飛距離用
# ---------------------------------------------------------------------------
def geodesic_distance(lat1, lon1, lat2, lon2, itr_limit=200):
    """WGS84 楕円体上の測地線距離 [m]。lat2/lon2 は配列可（lat1/lon1 はスカラー）。
    同一点は 0、NaN 入力は NaN。スカラー入力ならスカラーを返す。"""
    a, b, f = wgs84.a, wgs84.b, wgs84.f
    lat2 = np.asarray(lat2, dtype=float)
    lon2 = np.asarray(lon2, dtype=float)
    scalar = (lat2.ndim == 0)
    lat2 = np.atleast_1d(lat2)
    lon2 = np.atleast_1d(lon2)

    out = np.full(lat2.shape, np.nan)
    m = np.isfinite(lat2) & np.isfinite(lon2)
    if m.any():
        with np.errstate(all='ignore'):
            L = np.radians(lon2[m] - lon1)
            U1 = np.arctan((1.0 - f) * np.tan(np.radians(lat1)))
            U2 = np.arctan((1.0 - f) * np.tan(np.radians(lat2[m])))
            sinU1, cosU1 = np.sin(U1), np.cos(U1)
            sinU2, cosU2 = np.sin(U2), np.cos(U2)
            lam = L.copy()
            sin_sigma = sigma = cos_sigma = cos_2sm = cos2_alpha = None
            for _ in range(itr_limit):
                sin_lam, cos_lam = np.sin(lam), np.cos(lam)
                sin_sigma = np.sqrt((cosU2 * sin_lam) ** 2
                                    + (cosU1 * sinU2 - sinU1 * cosU2 * cos_lam) ** 2)
                cos_sigma = sinU1 * sinU2 + cosU1 * cosU2 * cos_lam
                sigma = np.arctan2(sin_sigma, cos_sigma)
                safe = sin_sigma != 0.0
                sin_alpha = np.where(safe, cosU1 * cosU2 * sin_lam / np.where(safe, sin_sigma, 1.0), 0.0)
                cos2_alpha = 1.0 - sin_alpha ** 2
                cos_2sm = np.where(cos2_alpha != 0.0,
                                   cos_sigma - 2.0 * sinU1 * sinU2 / np.where(cos2_alpha != 0.0, cos2_alpha, 1.0),
                                   0.0)
                C = f / 16.0 * cos2_alpha * (4.0 + f * (4.0 - 3.0 * cos2_alpha))
                lam_prev = lam
                lam = L + (1.0 - C) * f * sin_alpha * (
                    sigma + C * sin_sigma * (cos_2sm + C * cos_sigma * (-1.0 + 2.0 * cos_2sm ** 2)))
                if np.nanmax(np.abs(lam - lam_prev)) < 1e-12:
                    break
            u2 = cos2_alpha * (a ** 2 - b ** 2) / b ** 2
            A = 1.0 + u2 / 16384.0 * (4096.0 + u2 * (-768.0 + u2 * (320.0 - 175.0 * u2)))
            B = u2 / 1024.0 * (256.0 + u2 * (-128.0 + u2 * (74.0 - 47.0 * u2)))
            d_sigma = B * sin_sigma * (cos_2sm + 0.25 * B * (
                cos_sigma * (-1.0 + 2.0 * cos_2sm ** 2)
                - (1.0 / 6.0) * B * cos_2sm * (-3.0 + 4.0 * sin_sigma ** 2) * (-3.0 + 4.0 * cos_2sm ** 2)))
            dist = b * A * (sigma - d_sigma)
        # 同一点（sin_sigma=0 で NaN 化）は距離 0
        dist = np.where(np.isfinite(dist), dist, 0.0)
        out[m] = dist

    return float(out[0]) if scalar else out


# 各 flight_log から IIP を計算するのに必要な列
IIP_INPUT_COLUMNS = (["Time [s]", "Altitude [m]", "Latitude [deg]", "Longitude [deg]"]
                     + _ECI_POS_COLS + _ECI_VEL_COLS)

# 頂点高度がこの値[m]未満なら IIP を自動スキップ（小型ロケットには不要）。
# 安全側（IIP必須の大型を取りこぼさない）に倒すなら下げる。引数で上書き可。
IIP_MIN_APOGEE_M = 10000.0


def has_iip_input(columns):
    """IIP 計算に必要な ECI 列が揃っているか（minimum_dump ログ等の防御）。"""
    return set(_ECI_POS_COLS + _ECI_VEL_COLS).issubset(set(columns))


def should_run_iip(df_all, iip=None, min_apogee=IIP_MIN_APOGEE_M):
    """IIP を実行すべきか判定。

    iip: None=頂点高度ゲート（既定）, True=強制ON, False=強制OFF。
    """
    if iip is not None:
        return bool(iip)
    return float(df_all["Altitude [m]"].max()) >= min_apogee


# ---------------------------------------------------------------------------
# IIP DataFrame / CSV (単発・MC 共有コア)
# ---------------------------------------------------------------------------
def iip_dataframe(df_all, method="ahn_roh", min_altitude=100.0):
    """IIP 時間履歴を計算し、縮退行をマスクした DataFrame を返す。

    min_altitude: 機体高度がこの値[m]未満の行は IIP を NaN にする。着地寸前など
                  IIP 基準面（WGS84 楕円体≒海面）に機体が近い行は解が縮退し
                  （地表すれすれの残留速度で半周回先に落ちる解になる）非物理なため除外。
    """
    res = compute_iip_timehistory(df_all, method=method)
    time, lat, lon, tof = res["time"], res["lat"].copy(), res["lon"].copy(), res["tof"].copy()

    degenerate = df_all["Altitude [m]"].to_numpy() < min_altitude
    lat[degenerate] = np.nan
    lon[degenerate] = np.nan
    tof[degenerate] = np.nan

    lat0 = float(df_all["Latitude [deg]"].iloc[0])
    lon0 = float(df_all["Longitude [deg]"].iloc[0])
    downrange = geodesic_distance(lat0, lon0, lat, lon)  # ベクトル化

    return pd.DataFrame({
        "Time [s]": time,
        "IIP Latitude [deg]": lat,
        "IIP Longitude [deg]": lon,
        "IIP TimeToImpact [s]": tof,
        "IIP Downrange from Launch [m]": downrange,
    })


def write_iip_log(df_all, file_prefix, method="ahn_roh", min_altitude=100.0):
    """IIP 時間履歴 CSV (`<file_prefix>_iip_log.csv`) を書き出し、DataFrame を返す。"""
    iip_df = iip_dataframe(df_all, method=method, min_altitude=min_altitude)
    iip_df.to_csv(file_prefix + "_iip_log.csv", index=False)
    return iip_df


# ---------------------------------------------------------------------------
# Trajectory post-processing entry point (単発: CSV + プロット + KML)
# ---------------------------------------------------------------------------
def post_iip(df_all, file_prefix, method="ahn_roh", min_altitude=100.0):
    """単発軌道の IIP 時間履歴を計算し、CSV・プロット・KML を出力する。"""
    iip_df = write_iip_log(df_all, file_prefix, method=method, min_altitude=min_altitude)
    time = iip_df["Time [s]"].to_numpy()
    lat = iip_df["IIP Latitude [deg]"].to_numpy()
    lon = iip_df["IIP Longitude [deg]"].to_numpy()
    tof = iip_df["IIP TimeToImpact [s]"].to_numpy()
    downrange = iip_df["IIP Downrange from Launch [m]"].to_numpy()

    lat0 = float(df_all["Latitude [deg]"].iloc[0])
    lon0 = float(df_all["Longitude [deg]"].iloc[0])
    valid = np.isfinite(lat) & np.isfinite(lon)

    # IIP 地表トラック（経度-緯度）
    plt.figure()
    if valid.any():
        plt.plot(lon[valid], lat[valid], color='royalblue', label='IIP track')
    plt.plot(lon0, lat0, marker='^', color='black', linestyle='None', label='Launch')
    plt.plot(float(df_all["Longitude [deg]"].iloc[-1]), float(df_all["Latitude [deg]"].iloc[-1]),
             marker='x', color='orangered', linestyle='None', label='Landing')
    plt.xlabel("Longitude [deg]")
    plt.ylabel("Latitude [deg]")
    plt.grid()
    plt.legend()
    plt.gca().set_aspect('equal', adjustable='datalim')
    plt.savefig(file_prefix + "_iip_track.png")
    plt.close()

    # IIP 飛距離・落下時間の時間履歴
    fig, ax1 = plt.subplots()
    ax1.plot(time[valid], downrange[valid] / 1000.0, color='royalblue', label='IIP downrange')
    ax1.set_xlabel("Time [s]")
    ax1.set_ylabel("IIP Downrange from Launch [km]", color='royalblue')
    ax1.grid()
    ax2 = ax1.twinx()
    ax2.plot(time[valid], tof[valid], color='orangered', linestyle='dashed', label='Time to impact')
    ax2.set_ylabel("IIP Time to Impact [s]", color='orangered')
    fig.tight_layout()
    fig.savefig(file_prefix + "_iip_timehistory.png")
    plt.close(fig)

    # KML
    dump_iip_kml(lat[valid], lon[valid], file_prefix)

    return iip_df
