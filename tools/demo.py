"""End-to-end demo: synthetic log in, validation plots out.

Deliberately injects a 7% injector flow error so the residual plots have
something real to find -- which is the whole point of the technique.

    python3 tools/demo.py [outdir]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import matplotlib
matplotlib.use("Agg")          # demo writes PNGs, never opens a window

import numpy as np
from tqmodel.model import Engine, brake_torque, air_mass, spark_efficiency
from tqmodel.ve import ve_from_log, bin_surface
from tqmodel.units import kpa_abs_to_boost_psi
from tqmodel import plots

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(OUT, exist_ok=True)
eng = Engine()

from tqmodel.synth import generate
log = generate(n=6000, eng=eng, injector_flow_error=0.07)

# --- back-calculate VE from the log (VE autotune) -------------------------
ve_meas = ve_from_log(log["pulse_width_ms"], log["deadtime_ms"],
                      log["assumed_flow_g_per_ms"], log["lam"],
                      log["map_kpa"], log["t_charge_k"], eng)

# --- bin onto a grid and draw the tuning-table views ----------------------
rpm_edges = np.linspace(1000, 7200, 15)
map_edges = np.linspace(30, 240, 13)
grid, counts = bin_surface(log["rpm"], log["map_kpa"], ve_meas,
                           rpm_edges, map_edges, min_count=3)
rpm_c = (rpm_edges[:-1] + rpm_edges[1:]) / 2
map_c = (map_edges[:-1] + map_edges[1:]) / 2
boost_c = kpa_abs_to_boost_psi(map_c)

plots.table_heatmap(grid, rpm_c.round(0), boost_c.round(1),
                    title="Measured VE table (from log)",
                    ylabel="boost (psi)",
                    path=f"{OUT}/ve_table.png")

RG, MG = np.meshgrid(rpm_c, map_c)
filled = np.where(np.isnan(grid), np.nanmean(grid), grid)
plots.ve_surface_3d(RG, MG, filled, title="Measured VE surface",
                    path=f"{OUT}/ve_surface.png")

# --- run the forward model and compare against the reference --------------
t_model = brake_torque(ve_meas, log["map_kpa"], log["t_charge_k"], log["rpm"],
                       log["spark"], log["mbt"], log["lam"], eng)
plots.torque_validation(t_model, log["torque_ref"], log["time_s"],
                        path=f"{OUT}/torque_validation.png")

resid = t_model - log["torque_ref"]
plots.residual_grid(resid, {
    "spark delta from MBT (deg)": log["mbt"] - log["spark"],
    "air mass (g/cyl/cycle)": air_mass(ve_meas, log["map_kpa"],
                                       log["t_charge_k"], eng),
    "RPM": log["rpm"],
    "lambda": log["lam"],
    "boost (psi)": kpa_abs_to_boost_psi(log["map_kpa"]),
    "charge temp (K)": log["t_charge_k"],
}, path=f"{OUT}/residuals.png")

plots.coverage(log["rpm"], log["map_kpa"], path=f"{OUT}/coverage.png")

# --- console summary -------------------------------------------------------
ve_err = (ve_meas - log["ve_true"]) / log["ve_true"] * 100
print(f"samples                 {len(resid)}")
print(f"peak boost              {kpa_abs_to_boost_psi(log['map_kpa']).max():.1f} psi")
print(f"VE error vs truth       {ve_err.mean():+.2f} %  (injected: +7.00 %)")
print(f"torque mean error       {resid.mean():+.1f} Nm")
print(f"torque RMS error        {np.sqrt((resid**2).mean()):.1f} Nm")
print(f"plots written to        {OUT}/")
