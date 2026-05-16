"""Barrowman (1967) subsonic aerodynamic coefficient calculation.

Reference: Barrowman, J.S., "The Practical Calculation of the Aerodynamic
Characteristics of Slender Finned Vehicles", 1967.

All length inputs in mm (or any consistent unit).
"""
import math

NOSE_CP_FRACTION: dict[str, float] = {
    'conical':       2 / 3,
    'tangent_ogive': 0.466,
    'parabolic':     0.500,
    'elliptical':    1 / 3,
    'haack':         0.437,
}

NOSE_LABELS: dict[str, str] = {
    'conical':       'Conical',
    'tangent_ogive': 'Tangent Ogive',
    'parabolic':     'Parabolic (k=1)',
    'elliptical':    'Elliptical',
    'haack':         'Von Kármán (Haack)',
}


def _nose(nose_type: str, length: float) -> tuple[float, float]:
    """(CNα, XCP from nose tip) for nose cone. CNα = 2 for all subsonic shapes."""
    frac = NOSE_CP_FRACTION.get(nose_type, 2 / 3)
    return 2.0, length * frac


def _fins(n: int, Cr: float, Ct: float, span: float, sweep_le: float,
          d_body: float, x_root_le: float) -> tuple[float, float]:
    """
    Barrowman fin set CNα and XCP.

    n         : number of fins
    Cr        : root chord
    Ct        : tip chord
    span      : fin span from body surface (not from axis)
    sweep_le  : horizontal tip-LE offset from root-LE (positive = swept back)
    d_body    : body diameter at fin location
    x_root_le : nose-tip to fin root leading edge distance
    """
    if Cr + Ct <= 0 or d_body <= 0 or span <= 0:
        return 0.0, 0.0
    r  = d_body / 2
    s  = span + r                        # semi-span from body axis
    AR = 2 * span / (Cr + Ct)           # fin aspect ratio
    # CNα with Barrowman body-fin interference factor (1 + r/s)
    CNa = (4 * n * (s / d_body) ** 2 * (1 + r / s)) / (1 + math.sqrt(1 + AR ** 2))
    # XCP offset from root LE (Barrowman delta formula)
    m  = sweep_le
    dx = (m * (Cr + 2 * Ct)) / (3 * (Cr + Ct)) + (Cr + Ct - Cr * Ct / (Cr + Ct)) / 6
    return CNa, x_root_le + dx


def _transition(d_front: float, d_rear: float, length: float,
                x_front: float, d_ref: float) -> tuple[float, float]:
    """
    Barrowman transition / boat-tail CNα and XCP.
    Positive CNα = destabilising; negative = stabilising (d_rear < d_front).
    """
    if d_ref <= 0 or d_rear <= 0:
        return 0.0, x_front
    CNa   = 2.0 * ((d_rear / d_ref) ** 2 - (d_front / d_ref) ** 2)
    ratio = d_front / d_rear
    denom = 1 - ratio ** 2
    dx    = (length / 3 * (1 + (1 - ratio) / denom)) if abs(denom) > 1e-9 else length / 2
    return CNa, x_front + dx


def compute(comps: list[dict], d_ref: float, xcg: float | None = None) -> dict:
    """
    Run Barrowman analysis on a component list.

    Each component dict must have 'type' in {'nose', 'fins', 'transition'} plus
    type-specific keys matching the private helpers above.

    Returns dict with 'rows', 'CNa_total', 'xcp_total', 'static_margin'.
    """
    rows: list[dict] = []
    sum_CN  = 0.0
    sum_CNx = 0.0

    for c in comps:
        try:
            t = c.get('type', '')
            if t == 'nose':
                CN, xcp = _nose(c['nose_type'], c['length'])
            elif t == 'fins':
                CN, xcp = _fins(
                    int(c['n']), c['Cr'], c['Ct'],
                    c['span'], c['sweep_le'], c['d_body'], c['x_root_le'],
                )
            elif t == 'transition':
                CN, xcp = _transition(
                    c['d_front'], c['d_rear'], c['length'], c['x_front'], d_ref,
                )
            else:
                continue
        except Exception:
            continue

        rows.append({'component': c.get('name', t), 'CNa': CN, 'xcp': xcp})
        sum_CN  += CN
        sum_CNx += CN * xcp

    xcp_total = sum_CNx / sum_CN if sum_CN > 0 else 0.0
    sm = (xcp_total - xcg) / d_ref if (xcg is not None and d_ref > 0) else None

    return {
        'rows':          rows,
        'CNa_total':     sum_CN,
        'xcp_total':     xcp_total,
        'static_margin': sm,
    }
