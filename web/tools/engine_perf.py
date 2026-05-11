"""Hybrid rocket engine steady-state and burn-simulation calculations.

Model
-----
- Fuel regression law : r_dot [mm/s] = a * G_ox^n   (G_ox in kg/m²/s)
- Constant oxidizer mass-flow assumption (blowdown not modelled)
- Isentropic nozzle expansion (Cf from area ratio + ambient pressure)
- Explicit-Euler time integration for burn simulation
"""
import math

G0 = 9.80665  # m/s²

# Fuel presets: (rho [kg/m³], a [mm/s/(kg/m²/s)^n], n [-])
# Regression coefficients are approximate values from open literature for N₂O oxidizer.
FUEL_PRESETS: dict[str, dict] = {
    'HTPB / N₂O':  {'rho': 920,  'a': 0.116,  'n': 0.347, 'desc': 'Hydroxyl-terminated polybutadiene'},
    'PE / N₂O':    {'rho': 950,  'a': 0.0486, 'n': 0.450, 'desc': 'Polyethylene'},
    'ABS / N₂O':   {'rho': 1040, 'a': 0.069,  'n': 0.376, 'desc': 'Acrylonitrile-butadiene-styrene'},
    'PMMA / N₂O':  {'rho': 1190, 'a': 0.0424, 'n': 0.470, 'desc': 'Polymethyl methacrylate (acrylic)'},
    'Custom':       {'rho': 920,  'a': 0.10,   'n': 0.40,  'desc': 'User-defined'},
}


def _mach_supersonic(eps: float, gam: float) -> float:
    """Supersonic Mach number from isentropic area ratio (Newton-Raphson)."""
    Me = max(1.5, 1.0 + 0.27 * (eps - 1))
    for _ in range(60):
        t    = 1 + (gam - 1) / 2 * Me ** 2
        exp  = (gam + 1) / (2 * (gam - 1))
        A    = (2 / (gam + 1) * t) ** exp / Me
        dA   = A * ((gam - 1) * Me / (2 * t) - 1 / Me)
        step = (A - eps) / dA
        Me  -= step
        Me   = max(1.001, Me)
        if abs(step) < 1e-9:
            break
    return Me


def calc_cf(gamma: float, expansion_ratio: float, Pc_Pa: float,
            Pa_Pa: float = 101_325.0) -> float:
    """Thrust coefficient Cf including ambient back-pressure correction."""
    g   = gamma
    eps = max(expansion_ratio, 1.0)
    Me  = _mach_supersonic(eps, g)
    Pe_Pc = (1 + (g - 1) / 2 * Me ** 2) ** (-g / (g - 1))
    Cf_vac = (
        math.sqrt(
            2 * g ** 2 / (g - 1)
            * (2 / (g + 1)) ** ((g + 1) / (g - 1))
            * (1 - Pe_Pc ** ((g - 1) / g))
        )
        + Pe_Pc * eps
    )
    return Cf_vac - Pa_Pa / Pc_Pa * eps


def calc_point(
    m_dot_ox: float,     # kg/s
    d_port_mm: float,    # mm, current port inner diameter
    L_grain_mm: float,   # mm, grain length
    rho_fuel: float,     # kg/m³
    a: float,            # regression coeff [mm/s / (kg/m²/s)^n]
    n: float,            # regression exponent
    cstar: float,        # m/s (already includes η_c*)
    d_throat_mm: float,  # mm
    Cf: float,           # thrust coefficient
) -> dict:
    """Single operating-point (steady-state) calculation."""
    A_port   = math.pi * (d_port_mm / 2e3) ** 2   # m²
    A_throat = math.pi * (d_throat_mm / 2e3) ** 2  # m²

    G_ox      = m_dot_ox / A_port            # kg/m²/s
    rdot_mms  = a * G_ox ** n               # mm/s  regression rate
    rdot_ms   = rdot_mms / 1000             # m/s

    # Fuel mass flow from cylindrical port regression
    m_dot_fuel = rho_fuel * rdot_ms * math.pi * (d_port_mm / 1000) * (L_grain_mm / 1000)
    OF         = m_dot_ox / m_dot_fuel if m_dot_fuel > 0 else float('inf')
    m_dot_tot  = m_dot_ox + m_dot_fuel

    Pc   = m_dot_tot * cstar / A_throat      # Pa
    F    = Cf * Pc * A_throat                # N
    Isp  = F / (m_dot_tot * G0)             # s

    return {
        'G_ox':        G_ox,
        'rdot_mms':    rdot_mms,
        'm_dot_fuel':  m_dot_fuel,
        'm_dot_tot':   m_dot_tot,
        'OF':          OF,
        'Pc_MPa':      Pc / 1e6,
        'F_N':         F,
        'Isp_s':       Isp,
        'A_throat_m2': A_throat,
    }


def burn_simulation(
    m_ox_total: float,       # kg
    m_dot_ox: float,         # kg/s  (constant throughout burn)
    d_port_init_mm: float,   # mm
    d_outer_mm: float,       # mm
    L_grain_mm: float,       # mm
    rho_fuel: float,
    a: float,
    n: float,
    cstar: float,
    d_throat_mm: float,
    Cf: float,
    dt: float = 0.05,        # s, time step
    max_steps: int = 4000,
) -> dict:
    """
    Explicit-Euler burn simulation.

    Port grows radially (both walls) at the local regression rate.
    Burn ends when oxidizer is exhausted or port hits the outer wall.
    """
    d_port = d_port_init_mm
    m_ox   = m_ox_total
    t      = 0.0

    ts: list[float] = []
    Fs: list[float] = []
    Isps: list[float] = []
    OFs: list[float] = []
    Pcs: list[float] = []

    for _ in range(max_steps):
        if m_ox <= 1e-6 or d_port >= d_outer_mm:
            break
        res = calc_point(m_dot_ox, d_port, L_grain_mm, rho_fuel, a, n, cstar, d_throat_mm, Cf)
        ts.append(t)
        Fs.append(res['F_N'])
        Isps.append(res['Isp_s'])
        OFs.append(res['OF'])
        Pcs.append(res['Pc_MPa'])
        # Advance state
        d_port += 2 * res['rdot_mms'] * dt
        m_ox   -= m_dot_ox * dt
        t      += dt

    burn_time     = t
    avg_F         = sum(Fs) / len(Fs) if Fs else 0.0
    avg_Isp       = sum(Isps) / len(Isps) if Isps else 0.0
    total_impulse = avg_F * burn_time

    return {
        'burn_time':     burn_time,
        'total_impulse': total_impulse,
        'avg_thrust':    avg_F,
        'avg_Isp':       avg_Isp,
        'times':         ts,
        'thrusts':       Fs,
        'OFs':           OFs,
        'Pcs':           Pcs,
    }
