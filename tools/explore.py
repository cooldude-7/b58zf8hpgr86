"""Cell-based exploration -- the VS Code workflow.

This is a normal .py file, but the `# %%` markers make VS Code's Python
extension treat each block as a notebook cell with a "Run Cell" button
above it. Plots appear inline in the Interactive Window, and you can
re-run one cell after changing a value without rerunning everything.

Plain .py rather than .ipynb on purpose: it diffs properly in git.

Requires the Python extension (ms-python.python). Jupyter support comes
with it; VS Code will offer to `pip install ipykernel` the first time.
"""

# %% setup -- run this cell once
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import matplotlib.pyplot as plt

from tqmodel.model import (Engine, brake_torque, air_mass, spark_efficiency,
                           lambda_efficiency, required_air, authority)
from tqmodel.ve import ve_from_log, bin_surface
from tqmodel.units import kpa_abs_to_boost_psi, boost_psi_to_kpa_abs
from tqmodel.synth import generate
from tqmodel import plots

eng = Engine()
print(eng)


# %% [1] the spark efficiency curve -- flat on top, cliff after ~10 deg
d = np.linspace(0, 40, 200)
plt.figure(figsize=(7, 4))
plt.plot(d, spark_efficiency(d), lw=2)
for x in (5, 10, 20, 30):
    plt.plot(x, spark_efficiency(x), "ro")
    plt.annotate(f"{x} deg -> {float(spark_efficiency(x)):.2f}",
                 (x, float(spark_efficiency(x))), textcoords="offset points",
                 xytext=(8, 8), fontsize=9)
plt.xlabel("retard from MBT (deg)"); plt.ylabel("torque fraction")
plt.title("Why small retard is useless for a shift cut")
plt.grid(alpha=.3); plt.show()


# %% [2] one operating point -- change these numbers and re-run this cell
rpm, boost_psi, ve, retard = 4000, 12.0, 0.98, 0.0

map_kpa = boost_psi_to_kpa_abs(boost_psi)
mbt = 22.0
t = brake_torque(ve, map_kpa, 315, rpm, mbt - retard, mbt, 0.88, eng)
a = authority(ve, map_kpa, 315, rpm, mbt - retard, mbt, 0.88, eng)
print(f"air      {float(air_mass(ve, map_kpa, 315, eng)):.3f} g/cyl/cycle")
print(f"torque   {float(t):.1f} Nm")
print(f"authority{float(a):7.1f} Nm  ({100*float(a)/float(t):.0f}% of current)")


# %% [3] the inverse model -- and where torque reserve comes from
target = 250.0
for planned_retard in (0, 5, 10, 15):
    req = required_air(target, rpm, mbt - planned_retard, mbt, 0.88,
                       map_kpa, eng)
    print(f"planned retard {planned_retard:2d} deg -> "
          f"air required {float(req):.3f} g  "
          f"({100*(float(req)/float(required_air(target, rpm, mbt, mbt, 0.88, map_kpa, eng)) - 1):+.0f}%)")
print("\nMore retard planned -> more air demanded for the same torque.")
print("Deliberately planning retard IS torque reserve.")


# %% [4] full validation run -- change the injected error and re-run
INJECTED_ERROR = 0.07        # <-- try 0.0, then -0.12

log = generate(n=6000, eng=eng, injector_flow_error=INJECTED_ERROR)
ve_meas = ve_from_log(log["pulse_width_ms"], log["deadtime_ms"],
                      log["assumed_flow_g_per_ms"], log["lam"],
                      log["map_kpa"], log["t_charge_k"], eng)
t_model = brake_torque(ve_meas, log["map_kpa"], log["t_charge_k"], log["rpm"],
                       log["spark"], log["mbt"], log["lam"], eng)
resid = t_model - log["torque_ref"]
print(f"mean error {resid.mean():+.1f} Nm    RMS {np.sqrt((resid**2).mean()):.1f} Nm")

plots.torque_validation(t_model, log["torque_ref"], log["time_s"])
plt.show()


# %% [5] residuals -- the diagnostic. a slope names the broken term
plots.residual_grid(resid, {
    "spark delta from MBT (deg)": log["mbt"] - log["spark"],
    "air mass (g/cyl/cycle)": air_mass(ve_meas, log["map_kpa"],
                                       log["t_charge_k"], eng),
    "RPM": log["rpm"],
    "boost (psi)": kpa_abs_to_boost_psi(log["map_kpa"]),
})
plt.show()


# %% [6] break the friction model instead, and watch WHICH panel reacts
eng_bad = Engine(cf_c=0.14)          # was 0.09
log2 = generate(n=6000, eng=eng, injector_flow_error=0.0)
ve2 = ve_from_log(log2["pulse_width_ms"], log2["deadtime_ms"],
                  log2["assumed_flow_g_per_ms"], log2["lam"],
                  log2["map_kpa"], log2["t_charge_k"], eng)
t2 = brake_torque(ve2, log2["map_kpa"], log2["t_charge_k"], log2["rpm"],
                  log2["spark"], log2["mbt"], log2["lam"], eng_bad)
resid2 = t2 - log2["torque_ref"]

plots.residual_grid(resid2, {
    "air mass (g/cyl/cycle)": air_mass(ve2, log2["map_kpa"],
                                       log2["t_charge_k"], eng),
    "RPM": log2["rpm"],
})
plt.show()
print("Air mass panel stays clean. RPM panel now slopes.")
print("Same symptom (model is wrong), different fault, different panel.")


# %% [7] the coloured VE table
rpm_edges = np.linspace(1000, 7200, 15)
map_edges = np.linspace(30, 240, 13)
grid, counts = bin_surface(log["rpm"], log["map_kpa"], ve_meas,
                           rpm_edges, map_edges, min_count=3)
plots.table_heatmap(grid,
                    ((rpm_edges[:-1] + rpm_edges[1:]) / 2).round(0),
                    kpa_abs_to_boost_psi((map_edges[:-1] + map_edges[1:]) / 2).round(1),
                    title="Measured VE table", ylabel="boost (psi)")
plt.show()
