"""Step the simulator without a GUI and check it behaves like a car."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])
from tuner.core.tune import default_tune
from tuner.core.sim_ecu import SimulatedECU, ENGAGED

fails = 0
def check(name, ok, detail=""):
    global fails; fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))

sim = SimulatedECU(default_tune())
check("coordinator imported from tools/shift", sim.coord is not None, sim.coord_error or "")

# idle at standstill
for _ in range(400): sim._step()
c = sim._channels
check("idles near 800 rpm at standstill", 780 <= c["rpm"] <= 950, f"{c['rpm']:.0f}")
check("creeps gently, does not run away", c["speed"] < 12, f"{c['speed']:.1f} km/h")
check("three elements applied in 1st", sum(sim.p[e] > 3 for e in "ABCDE") == 3 and all(sim.p[e] > 3 for e in ENGAGED[1]))

# full throttle launch, 14 s
sim.pedal = 1.0
gears_seen, peak_rpm, peak_tq, shifts, cut_seen = set(), 0, 0, 0, False
for i in range(1400):
    sim._step(); c = sim._channels
    gears_seen.add(int(c["gear"])); peak_rpm = max(peak_rpm, c["rpm"]); peak_tq = max(peak_tq, c["torque"])
    if c["shift_phase"] == 1 and (i == 0 or last_phase == 0): shifts += 1
    if c["coord_phase"] == 2 and c["spark"] < c["mbt"] - 8: cut_seen = True
    last_phase = c["shift_phase"]
check("accelerates through several gears", len(gears_seen) >= 3, f"gears {sorted(gears_seen)}")
check("upshifts happen near the WOT shift point", 6500 <= peak_rpm <= 7600, f"peak {peak_rpm:.0f} rpm")
check("reaches a plausible speed", c["speed"] > 100, f"{c['speed']:.0f} km/h")
check("makes plausible torque on boost", 250 <= peak_tq <= 520, f"peak {peak_tq:.0f} Nm")
check("boost builds", c["boost"] > 5, f"{c['boost']:.1f} psi")
print(f"        ({shifts} shifts; spark cut during a shift: {'yes' if cut_seen else 'no - coordinator still placeholders'})")

# coast down: pedal off. A real automatic upshifts on lift-off, then steps
# back down as speed bleeds away; engine braking has to be doing the bleeding.
sim.pedal = 0.0
v0 = sim._channels["speed"]; g_hi = 0
for _ in range(6000):
    sim._step(); g_hi = max(g_hi, int(sim._channels["gear"]))
check("engine braking slows the car", sim._channels["speed"] < v0 - 30, f"{v0:.0f} -> {sim._channels['speed']:.0f} km/h")
check("downshifts as speed falls", int(sim._channels["gear"]) < g_hi, f"peak gear {g_hi}, now {int(sim._channels['gear'])}")

# dyno mode holds rpm
sim.reset(); sim.mode = "dyno"; sim.dyno_rpm = 4000; sim.pedal = 1.0
for _ in range(400): sim._step()
c = sim._channels
check("dyno holds the setpoint", abs(c["rpm"] - 4000) < 60, f"{c['rpm']:.0f}")
check("WOT on the dyno: boost near target", c["boost"] > 10, f"{c['boost']:.1f} psi")
check("authority is a fraction of torque", 0 < c["authority"] < c["torque"], f"{c['authority']:.0f} of {c['torque']:.0f}")

# editing the tune changes the engine
ve_before = c["torque"]
sim.tune.tables["ve"].values *= 0.85
for _ in range(50): sim._step()
check("lowering VE lowers torque on the next steps", sim._channels["torque"] < ve_before * 0.95,
      f"{ve_before:.0f} -> {sim._channels['torque']:.0f}")

print(f"\n{'all passed' if not fails else str(fails) + ' failed'}")
sys.exit(1 if fails else 0)
