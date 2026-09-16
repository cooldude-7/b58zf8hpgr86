"""Run your coordinator through one upshift and plot it.

    python tools\\shift\\simulate.py

Runs twice -- your code as written, and your code with the air-chase bug
switched on -- so you can see them side by side.

The air path is a first-order lag: air cannot move instantly. That is the
whole reason spark does the cutting.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import matplotlib.pyplot as plt

from shift.coordinator import (new_controller, start_shift, update,
                               fraction_for_retard)

DT = 0.001
DURATION = 0.9
SHIFT_AT = 0.15
DRIVER_TORQUE = 400.0
MBT = 22.0
AIR_TAU = 0.18
CUT_TO = 150.0


def run(bug=False):
    c = new_controller()
    c["chase_air_bug"] = bug
    air = DRIVER_TORQUE
    asked = False
    n = int(DURATION / DT)
    out = {k: np.zeros(n) for k in
           ("t", "torque", "target", "spark", "air_req", "air_act")}
    phases = []

    for i in range(n):
        t = i * DT
        if not asked and t >= SHIFT_AT:
            start_shift(c, CUT_TO, DRIVER_TORQUE)
            asked = True

        spark, air_request, torque_target = update(c, DT, DRIVER_TORQUE, MBT)
        air = air + (air_request - air) * (DT / AIR_TAU)
        torque = air * fraction_for_retard(MBT - spark)

        out["t"][i] = t
        out["torque"][i] = torque
        out["target"][i] = torque_target
        out["spark"][i] = spark
        out["air_req"][i] = air_request
        out["air_act"][i] = air
        phases.append(c["phase"])

    out["phases"] = phases
    return out


def plot(good, bad):
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)

    a = axes[0]
    a.plot(good["t"], good["target"], "k--", lw=1.2, label="target")
    a.plot(good["t"], good["torque"], lw=2, color="#27ae60", label="your code")
    a.plot(bad["t"], bad["torque"], lw=2, color="#c0392b", alpha=.85,
           label="with air-chase bug")
    a.axhline(DRIVER_TORQUE, color="#95a5a6", lw=.8, ls=":")
    a.set_ylabel("crank torque (Nm)")
    a.set_title("Does the cut land, and does it come back cleanly?")
    a.legend(); a.grid(alpha=.3)

    a = axes[1]
    a.plot(good["t"], good["spark"], lw=2, color="#27ae60", label="your code")
    a.plot(bad["t"], bad["spark"], lw=2, color="#c0392b", alpha=.85, label="bug")
    a.axhline(MBT, color="#95a5a6", lw=.8, ls=":", label="MBT")
    a.set_ylabel("spark (deg BTDC)"); a.legend(); a.grid(alpha=.3)

    a = axes[2]
    a.plot(good["t"], good["air_act"], lw=2, color="#27ae60", label="air (your code)")
    a.plot(bad["t"], bad["air_act"], lw=2, color="#c0392b", alpha=.85, label="air (bug)")
    a.plot(bad["t"], bad["air_req"], lw=1, ls="--", color="#c0392b", alpha=.5,
           label="air requested (bug)")
    a.set_ylabel("air (Nm-equivalent)"); a.set_xlabel("time (s)")
    a.legend(); a.grid(alpha=.3)

    fig.tight_layout()
    return fig


if __name__ == "__main__":
    good, bad = run(False), run(True)

    def summarise(name, L):
        during = (L["t"] > SHIFT_AT + 0.06) & (L["t"] < SHIFT_AT + 0.28)
        after = L["t"] > SHIFT_AT + 0.55
        print(f"{name:22s} during cut {L['torque'][during].mean():6.1f} Nm "
              f"(target {CUT_TO:.0f})   peak after {L['torque'][after].max():6.1f} Nm "
              f"(driver {DRIVER_TORQUE:.0f})")

    summarise("your code", good)
    summarise("with air-chase bug", bad)
    if abs(good["torque"].mean() - bad["torque"].mean()) < 1.0:
        print("\nBoth lines identical -- the TODOs are still placeholders.")

    out = sys.argv[1] if len(sys.argv) > 1 else None
    fig = plot(good, bad)
    if out:
        os.makedirs(out, exist_ok=True)
        fig.savefig(os.path.join(out, "shift.png"), dpi=120, bbox_inches="tight")
        print(f"plot written to {out}/shift.png")
    else:
        plt.show()
