"""Mass budget, center-of-gravity, and moment-of-inertia calculation.

Convention
----------
All lengths in mm (from a reference point, typically nose tip).
All masses in kg.
MOI values in kg·m² (lengths converted internally from mm to m).
"""


def compute(components: list[dict]) -> dict:
    """
    Compute total mass, CG, and moments of inertia.

    Each component dict:
        name      : str
        mass      : float [kg]
        x_cg      : float [mm from reference]
        Iyy_self  : float [kg·m²] lateral MOI about component's own CG, default 0
        Ixx       : float [kg·m²] axial (spin) MOI, default 0

    Returns:
        total_mass : float [kg]
        xcg        : float [mm]
        Iyy        : float [kg·m²]  total lateral MOI about system CG (parallel-axis applied)
        Ixx        : float [kg·m²]  total axial MOI
        rows       : list of per-component result dicts
    """
    total_mass = sum(c['mass'] for c in components)
    if total_mass <= 0:
        return {'total_mass': 0.0, 'xcg': 0.0, 'Iyy': 0.0, 'Ixx': 0.0, 'rows': []}

    xcg = sum(c['mass'] * c['x_cg'] for c in components) / total_mass

    rows: list[dict] = []
    Iyy_total = Ixx_total = 0.0

    for c in components:
        m      = c['mass']
        dx_m   = (c['x_cg'] - xcg) / 1000.0       # mm → m for MOI
        Iyy_i  = c.get('Iyy_self', 0.0) + m * dx_m ** 2
        Ixx_i  = c.get('Ixx', 0.0)
        Iyy_total += Iyy_i
        Ixx_total += Ixx_i
        rows.append({
            'name':      c['name'],
            'mass_kg':   m,
            'x_cg_mm':   c['x_cg'],
            'Iyy_kgm2':  Iyy_i,
            'Ixx_kgm2':  Ixx_i,
            'fraction':  m / total_mass,
        })

    return {
        'total_mass': total_mass,
        'xcg':        xcg,
        'Iyy':        Iyy_total,
        'Ixx':        Ixx_total,
        'rows':       rows,
    }
