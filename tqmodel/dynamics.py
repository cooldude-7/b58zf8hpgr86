"""Manifold filling dynamics.

The VE equation in model.py is steady-state. During a throttle transient
the air actually entering the cylinder is not what it says, and the torque
estimate is worst exactly when it matters -- tip-in, shifts, traction
events.

Treat the manifold as a control volume and integrate.
"""
import numpy as np

R_AIR = 287.0  # J/(kg*K)


def simulate_manifold(throttle_flow_g_s, rpm, t_manifold_k, volume_l,
                      ve, eng, dt, map0_kpa=30.0):
    """Integrate manifold pressure given inflow and engine pumping.

        dm/dt = flow_in(throttle) - flow_out(engine)

    Returns MAP in kPa per sample. First order and cheap; without it,
    modelled air leads or lags reality through every transient.
    """
    n = len(throttle_flow_g_s)
    vol_m3 = volume_l * 1e-3
    map_kpa = np.empty(n)
    m_g = map0_kpa * 1000.0 * vol_m3 / (R_AIR * t_manifold_k) * 1000.0

    for i in range(n):
        p_pa = m_g * 1e-3 * R_AIR * t_manifold_k / vol_m3
        map_kpa[i] = p_pa / 1000.0
        # engine pumping: charge mass per cycle x cycles per second
        rho = p_pa / (R_AIR * t_manifold_k)
        charge_g = ve[i] * eng.vd_per_cyl_l * 1e-3 * rho * 1000.0
        out_g_s = charge_g * eng.n_cyl * (rpm[i] / 60.0) / 2.0
        m_g = max(m_g + (throttle_flow_g_s[i] - out_g_s) * dt, 1e-6)

    return map_kpa
