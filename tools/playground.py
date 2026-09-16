"""Interactive playground -- drag sliders, watch the model move.

    python tools\\playground.py        (Windows)
    python3 tools/playground.py       (Linux/macOS)

Opens a window with live sliders. The fastest way to build intuition for
how spark, boost, VE and compression trade against each other, and for
where fast-path authority actually comes from.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

from tqmodel.model import (Engine, brake_torque, air_mass, spark_efficiency,
                           authority)
from tqmodel.synth import truth_mbt
from tqmodel.units import boost_psi_to_kpa_abs, kpa_abs_to_boost_psi

INIT = dict(rpm=4000.0, boost=8.0, retard=0.0, ve=0.95, cr=11.0)
T_CHARGE = 315.0
LAM = 0.88
MAX_RETARD = 30.0

fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 6))
plt.subplots_adjust(bottom=0.34, top=0.90, wspace=0.28)
fig.suptitle("Torque model playground  —  drag the sliders", fontsize=13)


def compute(rpm, boost, retard, ve, cr):
    eng = Engine(compression_ratio=cr)
    map_kpa = boost_psi_to_kpa_abs(boost)
    mbt = float(truth_mbt(rpm, map_kpa))
    spark = mbt - retard
    t = float(brake_torque(ve, map_kpa, T_CHARGE, rpm, spark, mbt, LAM, eng))
    t_mbt = float(brake_torque(ve, map_kpa, T_CHARGE, rpm, mbt, mbt, LAM, eng))
    auth = float(authority(ve, map_kpa, T_CHARGE, rpm, spark, mbt, LAM, eng,
                           max_retard_deg=MAX_RETARD))
    air = float(air_mass(ve, map_kpa, T_CHARGE, eng))
    return eng, map_kpa, mbt, spark, t, t_mbt, auth, air


def draw(_=None):
    rpm = s_rpm.val; boost = s_boost.val; retard = s_ret.val
    ve = s_ve.val; cr = s_cr.val
    eng, map_kpa, mbt, spark, t, t_mbt, auth, air = compute(
        rpm, boost, retard, ve, cr)

    # ---- left: torque vs retard from MBT ------------------------------
    axL.clear()
    d = np.linspace(0, 40, 200)
    curve = [float(brake_torque(ve, map_kpa, T_CHARGE, rpm, mbt - x, mbt,
                                LAM, eng)) for x in d]
    axL.plot(d, curve, lw=2, color="#2980b9")
    axL.axhline(t_mbt, ls="--", lw=1, color="#7f8c8d", label=f"MBT ceiling {t_mbt:.0f} Nm")
    axL.plot([retard], [t], "o", ms=11, color="#c0392b", zorder=5,
             label=f"operating point {t:.0f} Nm")
    axL.axvspan(retard, min(retard + MAX_RETARD, 40), alpha=.12,
                color="#27ae60", label=f"fast-path authority {auth:.0f} Nm")
    axL.set_xlabel("spark retard from MBT (deg)")
    axL.set_ylabel("crank torque (Nm)")
    axL.set_title("Torque vs spark  —  flat on top, steep after ~10 deg")
    axL.grid(alpha=.3); axL.legend(loc="upper right", fontsize=9)
    axL.set_ylim(0, max(curve) * 1.15)

    # ---- right: torque vs boost --------------------------------------
    axR.clear()
    psis = np.linspace(-10, 25, 120)
    at_mbt, at_now = [], []
    for p in psis:
        mk = boost_psi_to_kpa_abs(p)
        m = float(truth_mbt(rpm, mk))
        at_mbt.append(float(brake_torque(ve, mk, T_CHARGE, rpm, m, m, LAM, eng)))
        at_now.append(float(brake_torque(ve, mk, T_CHARGE, rpm, m - retard, m,
                                         LAM, eng)))
    axR.plot(psis, at_mbt, lw=2, color="#27ae60", label="at MBT")
    axR.plot(psis, at_now, lw=2, color="#c0392b",
             label=f"at {retard:.0f} deg retard")
    axR.plot([boost], [t], "o", ms=11, color="#2c3e50", zorder=5)
    axR.axvline(0, color="k", lw=.8, ls=":")
    axR.set_xlabel("boost (psi)"); axR.set_ylabel("crank torque (Nm)")
    axR.set_title("Torque vs boost")
    axR.grid(alpha=.3); axR.legend(loc="upper left", fontsize=9)

    pct = 100 * auth / t if t > 1 else 0.0
    fig.texts.clear()
    fig.text(0.5, 0.945,
             f"MAP {map_kpa:5.0f} kPa abs  |  air {air:.3f} g/cyl/cycle  |  "
             f"MBT {mbt:.1f} deg BTDC  |  spark {spark:.1f}  |  "
             f"torque {t:.0f} Nm  |  authority {auth:.0f} Nm ({pct:.0f}%)",
             ha="center", fontsize=10, family="monospace")
    fig.canvas.draw_idle()


def _ax(y):
    return plt.axes([0.13, y, 0.75, 0.03])


s_rpm   = Slider(_ax(0.22), "RPM",            900, 7200, valinit=INIT["rpm"],   valstep=50)
s_boost = Slider(_ax(0.175), "boost (psi)",   -10,   25, valinit=INIT["boost"], valstep=0.5)
s_ret   = Slider(_ax(0.13), "retard from MBT",  0,   35, valinit=INIT["retard"],valstep=0.5)
s_ve    = Slider(_ax(0.085), "VE",            0.4,  1.2, valinit=INIT["ve"],    valstep=0.01)
s_cr    = Slider(_ax(0.04), "compression",    8.0, 14.0, valinit=INIT["cr"],    valstep=0.1)

for s in (s_rpm, s_boost, s_ret, s_ve, s_cr):
    s.on_changed(draw)

draw()
print("Playground open. Things worth trying:")
print("  - drag retard 0 -> 10: torque barely moves (the curve is flat on top)")
print("  - drag retard 10 -> 25: it falls off a cliff")
print("  - raise boost, then check how authority in Nm grows with it")
print("  - drop VE and watch torque fall with no change in spark")
plt.show()
