"""Six checks on your coordinator.

    python tools\\shift\\test_shift.py

Each failure names the TODO responsible.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np

from shift.coordinator import (new_controller, start_shift, update,
                               fraction_for_retard)

DT, MBT, DRIVER, CUT, AIR_TAU = 0.001, 22.0, 400.0, 150.0, 0.18
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not ok and detail:
        print(f"         {detail}")


def simulate(bug=False, n=900, moving_pedal=False):
    """moving_pedal: the driver eases off slightly mid-shift.

    This distinguishes a genuinely frozen air request from one that merely
    happens to be constant because it is following an unchanging pedal.
    """
    c = new_controller()
    c["chase_air_bug"] = bug
    air, asked, rows = DRIVER, False, []
    for i in range(n):
        t = i * DT
        driver = DRIVER
        if moving_pedal and t > 0.20:
            driver = DRIVER - 60.0        # pedal eases off during the shift
        if not asked and t >= 0.15:
            start_shift(c, CUT, DRIVER)
            asked = True
        spark, air_req, target = update(c, DT, driver, MBT)
        air = air + (air_req - air) * (DT / AIR_TAU)
        rows.append((t, air * fraction_for_retard(MBT - spark), spark,
                     air_req, c["phase"]))
    return rows


print("Running checks...\n")
rows = simulate()
t = np.array([r[0] for r in rows])
torque = np.array([r[1] for r in rows])
spark = np.array([r[2] for r in rows])
airreq = np.array([r[3] for r in rows])
phases = [r[4] for r in rows]

seen = []
for p in phases:
    if not seen or seen[-1] != p:
        seen.append(p)

check("TODO 1: phases run idle -> cutting -> holding -> restoring -> idle",
      seen == ["idle", "cutting", "holding", "restoring", "idle"],
      f"got {seen}")

busy = [i for i, p in enumerate(phases) if p != "idle"]
dur = (busy[-1] - busy[0]) * DT * 1000 if busy else 0
check("TODO 1: whole shift lasts about 450 ms",
      430 <= dur <= 470, f"got {dur:.0f} ms")

hold = [i for i, p in enumerate(phases) if p == "holding"]
held = torque[hold[len(hold) // 3:]] if hold else np.array([999.0])
check("TODO 2+3: torque reaches the 150 Nm target while holding",
      abs(held.mean() - CUT) < 12, f"got {held.mean():.1f} Nm, wanted ~{CUT}")

# Run again with the pedal moving mid-shift. A correct implementation holds
# the frozen value regardless; a placeholder that just echoes driver_torque
# will follow the pedal and give itself away.
mrows = simulate(moving_pedal=True)
mbusy = [i for i, r in enumerate(mrows) if r[4] != "idle"]
mair = np.array([mrows[i][3] for i in mbusy]) if mbusy else np.array([0.0, 99.0])
check("TODO 4: air request stays FROZEN during the shift (pedal moves, air must not)",
      len(mbusy) > 0 and np.ptp(mair) < 1.0,
      f"it moved by {np.ptp(mair):.1f} Nm when the pedal moved -- it must stay "
      f"frozen at the pre-shift value")

after = torque[t > 0.75]
check("no torque overshoot after the shift",
      after.max() <= DRIVER * 1.03,
      f"peaked at {after.max():.1f} Nm vs driver request {DRIVER}")

check("spark back at MBT once idle",
      abs(spark[-1] - MBT) < 0.5, f"ended at {spark[-1]:.1f} deg")

bugrows = simulate(bug=True)
bugheld = np.array([r[1] for r in bugrows])[hold[len(hold) // 3:]] if hold else np.array([0.0])
print(f"\n  (sanity) with chase_air_bug on, the cut lands at {bugheld.mean():.0f} Nm "
      f"instead of {CUT:.0f} -- "
      f"{'bug reproduces' if bugheld.mean() > CUT + 25 else 'not reproducing yet'}")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
