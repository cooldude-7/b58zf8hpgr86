"""Drive the simulator the way the app does: through the Qt event loop.

    python tests/test_live.py

Full throttle from standstill with the live view open, real wall-clock
time. Checks that the simulation keeps pace with the clock, that the car
launches and shifts, and that the live view is being fed.
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])
from tuner.ui.theme import apply_classic
apply_classic(app)
from tuner.ui.main_window import MainWindow

win = MainWindow(persist_layout=False)
win.use_simulator(); win.show()
win.open_key("mimic")
win.sim_dock.pedal.setValue(100)
win.conn.connect_ecu()

SECS = 8.0
t0 = time.monotonic(); gears, peak_rpm, frames = set(), 0.0, 0
last_sim_t = 0.0
while time.monotonic() - t0 < SECS:
    app.processEvents()
    time.sleep(0.001)
    ch = win.sim.channels()
    gears.add(int(ch["gear"])); peak_rpm = max(peak_rpm, ch["rpm"])
wall = time.monotonic() - t0
ch = win.sim.channels()
fails = 0
def check(name, ok, detail=""):
    global fails; fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

check("simulation keeps pace with the clock", abs(win.sim.t - wall) < 0.6, f"sim {win.sim.t:.2f} s in {wall:.2f} s wall")
check("car launches", ch["speed"] > 40, f"{ch['speed']:.0f} km/h")
check("upshifts happen", len(gears) >= 2, f"gears {sorted(gears)}")
check("engine is not parked on the rev limiter", peak_rpm < 7450, f"peak {peak_rpm:.0f} rpm")
check("live view is fed", win.editors["mimic"].trans.ch.get("rpm", 0) > 0)
check("datalog has live samples", len(win.datalog._buf["t"]) > 20, f"{len(win.datalog._buf['t'])} samples")
print(f"        gear {int(ch['gear'])}  {ch['speed']:.0f} km/h  {ch['rpm']:.0f} rpm  tc_lock {int(ch['tc_lock'])}")
print(f"\n{'all passed' if not fails else str(fails) + ' failed'}")
win.conn.disconnect_ecu()
sys.exit(1 if fails else 0)
