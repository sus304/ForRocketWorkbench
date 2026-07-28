from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

VZ_COL = "Vz-NED [m/s]"
T_COL = "Time [s]"
H_COL = "Altitude [m]"


@dataclass
class Apogee:
    time: float                 # [s]
    altitude: float             # [m]
    index: int                  # raw argmax row; slice bound for maxQ/maxVel/maxMach
    method: str                 # 'hermite' | 'raw-max (reason)'
    interval: float             # interpolation interval [s]
    raw_time: float             # [s]
    raw_altitude: float         # [m]
    check_altitude: float       # same peak on one-step-wider interval [m]

    @property
    def altitude_correction(self) -> float:
        return self.altitude - self.raw_altitude

    @property
    def time_correction(self) -> float:
        return self.time - self.raw_time

    @property
    def convergence_gap(self) -> float:
        if math.isnan(self.check_altitude):
            return float("nan")
        return abs(self.altitude - self.check_altitude)


def _peak_on_interval(t0: float, t1: float, h0: float, h1: float,
                      d0: float, d1: float) -> Optional[tuple]:
    dt = t1 - t0
    if not (dt > 0.0):
        return None
    a3 = 2.0 * h0 + d0 * dt - 2.0 * h1 + d1 * dt
    a2 = -3.0 * h0 - 2.0 * d0 * dt + 3.0 * h1 - d1 * dt
    a1 = d0 * dt
    a0 = h0

    def val(s: float) -> float:
        return ((a3 * s + a2) * s + a1) * s + a0

    # Solve h'(s) = 3*a3*s^2 + 2*a2*s + a1 = 0. A vacuum apogee is near-parabolic, so a3 can be
    # ~20 orders below b^2 and the naive quadratic formula cancels catastrophically on one root.
    # Take the large root stably, recover the other from the product C/A.
    roots = []
    A, B, C = 3.0 * a3, 2.0 * a2, a1
    if abs(A) <= 1e-13 * abs(B):
        if B != 0.0:
            roots.append(-C / B)
    else:
        disc = B * B - 4.0 * A * C
        if disc >= 0.0:
            q = -0.5 * (B + math.copysign(math.sqrt(disc), B if B != 0.0 else 1.0))
            if q != 0.0:
                roots.extend((q / A, C / q))
            else:
                roots.append(0.0)
    cand = [s for s in roots if 0.0 <= s <= 1.0]
    cand.extend((0.0, 1.0))
    s_best = max(cand, key=val)
    return t0 + s_best * dt, val(s_best)


def refine_apogee(df) -> Apogee:
    h = df[H_COL].to_numpy(dtype=float)
    k_raw = int(np.argmax(h))
    has_time = T_COL in df.columns
    t = df[T_COL].to_numpy(dtype=float) if has_time else np.full(len(h), np.nan)
    raw_t, raw_h = float(t[k_raw]) if has_time else float("nan"), float(h[k_raw])

    def fallback(reason: str) -> Apogee:
        return Apogee(time=raw_t, altitude=raw_h, index=k_raw, method=f"raw-max ({reason})",
                      interval=0.0, raw_time=raw_t, raw_altitude=raw_h,
                      check_altitude=float("nan"))

    if not has_time:
        return fallback(f"no {T_COL}")
    if VZ_COL not in df.columns:
        return fallback(f"no {VZ_COL}")
    if len(t) < 2:
        return fallback("too few rows")

    hdot = -df[VZ_COL].to_numpy(dtype=float)
    ok = np.diff(t) > 0.0
    cross = np.where((hdot[:-1] > 0.0) & (hdot[1:] <= 0.0) & ok)[0]
    if len(cross) == 0:
        return fallback("no vertical velocity sign change")

    best = None
    for j in cross.tolist():
        peak = _peak_on_interval(t[j], t[j+1], h[j], h[j+1], hdot[j], hdot[j+1])
        if peak is None:
            continue
        if best is None or peak[1] > best[1]:
            best = (peak[0], peak[1], j)
    if best is None:
        return fallback("interpolation failed")
    t_apo, h_apo, j = best

    check = float("nan")
    if j - 1 >= 0 and j + 2 < len(t) and t[j+2] > t[j-1]:
        wide = _peak_on_interval(t[j-1], t[j+2], h[j-1], h[j+2], hdot[j-1], hdot[j+2])
        if wide is not None:
            check = wide[1]

    return Apogee(time=float(t_apo), altitude=float(h_apo), index=k_raw, method="hermite",
                  interval=float(t[j+1] - t[j]), raw_time=raw_t, raw_altitude=raw_h,
                  check_altitude=check)


def value_at_apogee(df, column: str, apo: Apogee) -> float:
    if apo.method != "hermite":
        return float(df[column].to_numpy(dtype=float)[apo.index])
    return float(np.interp(apo.time, df[T_COL].to_numpy(dtype=float),
                           df[column].to_numpy(dtype=float)))


def diagnostics_text(apo: Apogee) -> str:
    if apo.method != "hermite":
        return f"Apogee Method,{apo.method}\n"
    lines = [
        "Apogee Method,hermite\n",
        f"Apogee Interpolation Interval,{apo.interval:.4f}[s]\n",
        f"Apogee Raw-Max Altitude,{apo.raw_altitude:.3f}[m]\n",
        f"Apogee Correction vs Raw-Max,{apo.altitude_correction:+.3f}[m]\n",
        f"Apogee Time Correction vs Raw-Max,{apo.time_correction:+.4f}[s]\n",
    ]
    gap = apo.convergence_gap
    if not math.isnan(gap):
        lines.append(f"Apogee Convergence Gap,{gap:.3f}[m]\n")
        if apo.altitude > 0.0 and gap > 1.0e-4 * apo.altitude:
            lines.append("Apogee Warning,log too coarse near apogee "
                         "(tighten Solver Tolerance Abs)\n")
    return "".join(lines)
