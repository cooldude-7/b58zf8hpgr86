"""Six checks on your coordinator.

    python tools\\shift\\test_shift.py

No pytest needed. Each check prints PASS or FAIL with what it expected,
so a failure tells you which TODO to look at.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np

from tqmodel.model import spark_efficiency
from shift.coordinator import ShiftCoordinator, ShiftRequest, ShiftState

DT, MBT, DRIVER, CUT, AIR_TAU = 0.001, 22.0, 400.0, 150.0, 0.18
REQ = ShiftRequest(target_torque_nm=CUT, ramp_in_ms=50, hold_ms=250,
                   ramp_out_ms=150)

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not ok and detail:
        print(f"         {detail}")


def simulate(bug=False, n=900):
    c = ShiftCoordinator(chase_air_bug=bug)
    air, asked = DRIVER, False
    rows = []
    for i in range(n):
        t = i * DT
        if not asked and t >= 0.15:
            c.request_shift(REQ, DRIVER)
            asked = True
        cmd = c.update(DT, DRIVER, MBT)
        air += (cmd.air_request_nm - air) * (DT / AIR_TAU)
        rows.append((t, air * float(spark_efficiency(MBT - cmd.spark_deg)),
                     cmd.spark_deg, cmd.air_request_nm, cmd.state))
    return rows


print("Running checks...\n")
rows = simulate()
t      = np.array([r[0] for r in rows])
torque = np.array([r[1] for r in rows])
spark  = np.array([r[2] for r in rows])
airreq = np.array([r[3] for r in rows])
states = [r[4] for r in rows]

seen = []
for s in states:
    if not seen or seen[-1] != s:
        seen.append(s)

# 1 -- state machine visits all four states in order, and returns to IDLE
check("TODO 1: state machine runs CUTTING -> HOLDING -> RESTORING -> IDLE",
      seen == [ShiftState.IDLE, ShiftState.CUTTING, ShiftState.HOLDING,
               ShiftState.RESTORING, ShiftState.IDLE],
      f"got {[s.value for s in seen]}")

# 2 -- the shift lasts about as long as it was asked to
busy = [i for i, s in enumerate(states) if s != ShiftState.IDLE]
dur_ms = (busy[-1] - busy[0]) * DT * 1000 if busy else 0
check("TODO 1: total duration is about 450 ms",
      430 <= dur_ms <= 470, f"got {dur_ms:.0f} ms")

# 3 -- torque target is actually reached during the hold
hold = [i for i, s in enumerate(states) if s == ShiftState.HOLDING]
held = torque[hold[len(hold)//3:]] if hold else np.array([999.0])
check("TODO 2+3: torque reaches the 150 Nm target during HOLDING",
      abs(held.mean() - CUT) < 12, f"got {held.mean():.1f} Nm, wanted ~{CUT}")

# 4 -- THE important one: air request is held flat through the shift
air_busy = airreq[busy] if busy else np.array([0.0, 1.0])
check("TODO 4: air request stays CONSTANT during the shift",
      np.ptp(air_busy) < 1.0,
      f"air request moved by {np.ptp(air_busy):.1f} Nm - it must be frozen")

# 5 -- no overshoot once the shift is done
after = torque[t > 0.75]
check("no torque overshoot after the shift",
      after.max() <= DRIVER * 1.03,
      f"peaked at {after.max():.1f} Nm vs driver request {DRIVER}")

# 6 -- spark ends up back at MBT
check("spark returns to MBT when idle",
      abs(spark[-1] - MBT) < 0.5, f"ended at {spark[-1]:.1f} deg")

# and the bug version should visibly differ
bug = simulate(bug=True)
bug_hold = np.array([r[1] for r in bug])[hold[len(hold)//3:]] if hold else np.array([0.0])
print(f"\n  (sanity) with chase_air_bug=True the cut lands at "
      f"{bug_hold.mean():.0f} Nm instead of {CUT:.0f} - "
      f"{'bug reproduces' if bug_hold.mean() > CUT + 25 else 'bug not reproducing yet'}")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
