"""Run your coordinator through one upshift and plot what it did.

    python tools\\shift\\simulate.py

Runs twice: once with your code as written, once with chase_air_bug=True,
so you can see the two failure modes the correct version avoids.

The air path is modelled as a first-order lag -- air cannot move instantly,
which is the entire reason spark does the cutting.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import matplotlib.pyplot as plt

from tqmodel.model import spark_efficiency
from shift.coordinator import ShiftCoordinator, ShiftRequest, ShiftState

DT = 0.001              # 1 ms ticks
DURATION = 0.9          # seconds
SHIFT_AT = 0.15         # when the trans asks
DRIVER_TORQUE = 400.0   # foot flat, unchanged throughout
MBT = 22.0
AIR_TAU = 0.18          # manifold + turbo lag, seconds
CUT_TO = 150.0


def run(chase_air_bug=False):
    coord = ShiftCoordinator(chase_air_bug=chase_air_bug)
    n = int(DURATION / DT)
    air_actual = DRIVER_TORQUE          # "torque this air makes at MBT"
    asked = False

    log = {k: np.zeros(n) for k in
           ("t", "torque", "target", "spark", "air_req", "air_act", "state")}

    for i in range(n):
        t = i * DT
        if not asked and t >= SHIFT_AT:
            coord.request_shift(ShiftRequest(target_torque_nm=CUT_TO),
                                current_torque_nm=DRIVER_TORQUE)
            asked = True

        cmd = coord.update(DT, DRIVER_TORQUE, MBT)

        # air path: first-order lag toward whatever was requested
        air_actual += (cmd.air_request_nm - air_actual) * (DT / AIR_TAU)

        eff = float(spark_efficiency(MBT - cmd.spark_deg))
        torque = air_actual * eff

        log["t"][i] = t
        log["torque"][i] = torque
        log["target"][i] = cmd.torque_target_nm
        log["spark"][i] = cmd.spark_deg
        log["air_req"][i] = cmd.air_request_nm
        log["air_act"][i] = air_actual
        log["state"][i] = list(ShiftState).index(cmd.state)
    return log


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
        shift = (L["t"] > SHIFT_AT + 0.06) & (L["t"] < SHIFT_AT + 0.28)
        after = L["t"] > SHIFT_AT + 0.55
        print(f"{name:22s} during cut {L['torque'][shift].mean():6.1f} Nm "
              f"(target {CUT_TO:.0f})   peak after {L['torque'][after].max():6.1f} Nm "
              f"(driver {DRIVER_TORQUE:.0f})")

    summarise("your code", good)
    summarise("with air-chase bug", bad)
    print("\nIf both lines look identical, the TODOs are still placeholders.")

    out = sys.argv[1] if len(sys.argv) > 1 else None
    fig = plot(good, bad)
    if out:
        os.makedirs(out, exist_ok=True)
        fig.savefig(os.path.join(out, "shift.png"), dpi=120, bbox_inches="tight")
        print(f"plot written to {out}/shift.png")
    else:
        plt.show()
