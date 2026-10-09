import numpy as np
import pandas as pd
import pytest

from post_tool.apogee import refine_apogee, value_at_apogee

G = 9.32                         # gravity near 163 km [m/s2]
H_APO = 163000.0
T_APO = 192.4707
R_GEO = 6534.0e3                 # geocentric radius [m]
H4 = -2.0 * G ** 2 / R_GEO       # h'''' = -2g^2/r for vacuum inverse-square gravity


def make_log(dt, t_span=400.0, phase=0.0, with_vz=True, vh=44.0, h4=H4):
    """Sample h(tau) = H_APO - g*tau^2/2 + h4*tau^4/24 at step dt.

    The quartic term is required: a pure parabola is reproduced exactly by cubic Hermite,
    so the dt^4 error scaling would not be observable. phase shifts the sample positions.
    """
    t = np.arange(phase, t_span, dt)
    tau = t - T_APO
    h = H_APO - 0.5 * G * tau ** 2 + h4 * tau ** 4 / 24.0
    hdot = -G * tau + h4 * tau ** 3 / 6.0
    keep = h > 0.0
    t, h, hdot = t[keep], h[keep], hdot[keep]
    cols = {"Time [s]": t, "Altitude [m]": h,
            "Downrange [m]": vh * t, "Latitude [deg]": 31.25 + 0.0 * t,
            "Longitude [deg]": 131.08 + 0.0 * t}
    if with_vz:
        cols["Vz-NED [m/s]"] = -hdot        # NED is down-positive
    return pd.DataFrame(cols)


def test_hermite_beats_raw_max_on_coarse_log():
    df = make_log(dt=50.0, phase=3.0)
    apo = refine_apogee(df)
    assert apo.method == "hermite"
    assert abs(apo.altitude - H_APO) < abs(apo.raw_altitude - H_APO)
    assert abs(apo.altitude - H_APO) < 1.0
    assert abs(apo.raw_altitude - H_APO) > 100.0


def test_apogee_time_is_recovered():
    df = make_log(dt=50.0, phase=7.0)
    apo = refine_apogee(df)
    assert abs(apo.time - T_APO) < 0.01
    assert abs(apo.raw_time - T_APO) > 1.0


def test_error_scales_like_dt_fourth_power():
    """Doubling dt should raise the error ~16x, as cubic Hermite predicts."""
    errs = []
    for dt in (12.5, 25.0, 50.0):
        worst = max(abs(refine_apogee(make_log(dt=dt, phase=p)).altitude - H_APO)
                    for p in np.linspace(0.0, dt, 7, endpoint=False))
        errs.append(worst)
    for lo, hi in zip(errs[:-1], errs[1:]):
        ratio = hi / max(lo, 1e-12)
        assert 8.0 < ratio < 32.0, f"dt x2 gave {ratio:.1f}x error (expected ~16x)"


def test_falls_back_to_raw_max_without_vz_column():
    """Minimum-dump logs (-m) have no Vz-NED column; fall back instead of raising."""
    df = make_log(dt=1.0, with_vz=False)
    apo = refine_apogee(df)
    assert apo.method.startswith("raw-max")
    assert apo.altitude == pytest.approx(df["Altitude [m]"].max())


def test_picks_highest_of_multiple_crossings():
    """With several vertical velocity sign changes (staging, gas jet), keep the highest peak."""
    lo = make_log(dt=2.0, t_span=120.0)
    lo["Altitude [m]"] *= 0.2                      # a lower hump first
    lo["Vz-NED [m/s]"] *= 0.2
    hi = make_log(dt=2.0)
    hi["Time [s]"] += 200.0
    df = pd.concat([lo, hi], ignore_index=True)
    apo = refine_apogee(df)
    assert apo.method == "hermite"
    assert apo.altitude == pytest.approx(H_APO, abs=1.0)


def test_auxiliary_values_use_corrected_time():
    """Downrange and friends must be read at the corrected apogee time, not the raw row."""
    df = make_log(dt=50.0, phase=3.0, vh=44.0)
    apo = refine_apogee(df)
    dr = value_at_apogee(df, "Downrange [m]", apo)
    assert dr == pytest.approx(44.0 * T_APO, abs=44.0 * 0.05)
    raw_dr = float(df["Downrange [m]"].to_numpy()[apo.index])
    assert abs(dr - 44.0 * T_APO) < abs(raw_dr - 44.0 * T_APO)


def test_duplicate_timestamps_are_skipped():
    """Event rows can repeat a timestamp (dt=0); must not divide by zero."""
    df = make_log(dt=5.0)
    dup = df.iloc[[40]].copy()
    df = pd.concat([df.iloc[:41], dup, df.iloc[41:]], ignore_index=True)
    apo = refine_apogee(df)
    assert np.isfinite(apo.altitude)
    assert apo.method == "hermite"
