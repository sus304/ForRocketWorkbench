"""Ahn-Roh 閉形式 IIP vs 数値弾道伝播 の結果・速度比較（一時検証スクリプト）。"""
import sys
import time

import numpy as np
import pandas as pd

from post_tool.post_iip import _iip_ahn_roh_vec, iip_numerical

CSV = sys.argv[1] if len(sys.argv) > 1 else \
    "/home/susumu/ForRocket/examples/sample_stage1_flight_log.csv"

df = pd.read_csv(CSV)
df = df.dropna(how="any", axis=1)
t = df["Time [s]"].to_numpy()
pos = df[["X-ECI [km]", "Y-ECI [km]", "Z-ECI [km]"]].to_numpy() * 1e3
vel = df[["Vx-ECI [m/s]", "Vy-ECI [m/s]", "Vz-ECI [m/s]"]].to_numpy()
alt = df["Altitude [m]"].to_numpy()
n = len(t)
print(f"CSV: {CSV}")
print(f"rows={n}, time {t[0]:.1f}..{t[-1]:.1f}s, apogee alt={alt.max()/1000:.1f}km")

# --- timing: Ahn-Roh (ベクトル化バッチ＝本番経路) ---
s = time.perf_counter()
tof_a, lat_a, lon_a = _iip_ahn_roh_vec(pos, vel, t)
dt_a = time.perf_counter() - s

# --- timing: numerical ---
lat_n = np.full(n, np.nan); lon_n = np.full(n, np.nan); tof_n = np.full(n, np.nan)
s = time.perf_counter()
for i in range(n):
    tof_n[i], lat_n[i], lon_n[i] = iip_numerical(pos[i], vel[i], t[i], dt=1.0)
dt_n = time.perf_counter() - s

# --- agreement (両者とも有効な行のみ) ---
valid = np.isfinite(lat_a) & np.isfinite(lat_n)
nvalid = int(valid.sum())


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    h = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(h))


dist = haversine_m(lat_a[valid], lon_a[valid], lat_n[valid], lon_n[valid])
dtof = np.abs(tof_a[valid] - tof_n[valid])

print("\n=== Speed ===")
print(f"Ahn-Roh  : {dt_a*1e3:8.1f} ms total, {dt_a/n*1e6:7.1f} us/row")
print(f"Numerical: {dt_n*1e3:8.1f} ms total, {dt_n/n*1e6:7.1f} us/row")
print(f"speedup  : x{dt_n/dt_a:.1f}")

print("\n=== Validity ===")
print(f"Ahn-Roh valid  : {int(np.isfinite(lat_a).sum())}/{n}")
print(f"Numerical valid: {int(np.isfinite(lat_n).sum())}/{n}")
print(f"both valid     : {nvalid}/{n}")

def report(mask, title):
    m = valid & mask
    k = int(m.sum())
    print(f"\n=== Agreement: {title} (n={k}) ===")
    if not k:
        return
    d = haversine_m(lat_a[m], lon_a[m], lat_n[m], lon_n[m])
    dt = np.abs(tof_a[m] - tof_n[m])
    print(f"  dist  p50={np.percentile(d,50):8.2f}  p90={np.percentile(d,90):8.2f}  "
          f"p99={np.percentile(d,99):9.2f}  max={d.max():10.2f} m")
    print(f"  tof   p50={np.percentile(dt,50):7.3f}  max={dt.max():9.3f} s")
    # cpp 規約(経度 -ω·tof のみ, t 分欠落)だと数値解からどれだけずれるか
    lon_cpp = lon_a[m] + np.degrees(7.292115e-5 * t[m])
    d_cpp = haversine_m(lat_a[m], lon_cpp, lat_n[m], lon_n[m])
    print(f"  [cpp経度規約(-ω·tofのみ)] dist p50={np.percentile(d_cpp,50):8.1f}  max={d_cpp.max():9.1f} m")


report(np.ones(n, bool), "全行")
report(alt > 1000.0, "高度>1km")
report(alt > 5000.0, "高度>5km")
