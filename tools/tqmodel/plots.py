"""Validation plots for the torque model.

The ones that earn their keep. Residual plots are the important ones: an
overlay tells you the model is wrong, residuals against each input tell you
WHICH term is wrong.
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm

from .units import kpa_abs_to_boost_psi

TUNE_CMAP = "RdYlGn_r"   # the familiar green-low / red-high tuning palette


def ve_surface_3d(rpm_grid, map_grid, ve_grid, title="VE surface", path=None,
                  boost_axis=True):
    """3D surface. The physical plausibility audit.

    Look for: a smooth surface, peak in a sensible place, values in a sane
    range. Spikes are absorbed error, not volumetric efficiency.
    """
    fig = plt.figure(figsize=(9, 6))
    ax = fig.add_subplot(111, projection="3d")
    y = kpa_abs_to_boost_psi(map_grid) if boost_axis else map_grid
    ax.plot_surface(rpm_grid, y, ve_grid, cmap=cm.viridis,
                    edgecolor="none", alpha=0.95, rstride=1, cstride=1)
    ax.set_xlabel("RPM")
    ax.set_ylabel("boost (psi)" if boost_axis else "MAP (kPa)")
    ax.set_zlabel("VE")
    ax.set_title(title)
    ax.view_init(elev=28, azim=-125)
    return _out(fig, path)


def table_heatmap(grid, x_ticks, y_ticks, title="VE table",
                  xlabel="RPM", ylabel="MAP (kPa)", fmt="{:.2f}",
                  cmap=TUNE_CMAP, path=None):
    """Coloured cell table, the tuning-software view.

    Values annotated in each cell, colour-scaled across the range. Empty
    (NaN) cells show as grey -- those are places your logs never visited.
    """
    fig, ax = plt.subplots(figsize=(1.0 + 0.72 * len(x_ticks),
                                    1.2 + 0.42 * len(y_ticks)))
    masked = np.ma.masked_invalid(grid)
    cmap_obj = plt.get_cmap(cmap).copy()
    cmap_obj.set_bad("#3a3a3a")
    im = ax.imshow(masked, cmap=cmap_obj, aspect="auto", origin="lower")

    ax.set_xticks(range(len(x_ticks)), [f"{v:g}" for v in x_ticks], rotation=45)
    ax.set_yticks(range(len(y_ticks)), [f"{v:g}" for v in y_ticks])
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title)

    lo, hi = np.nanmin(grid), np.nanmax(grid)
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = grid[i, j]
            if np.isnan(v):
                continue
            shade = (v - lo) / (hi - lo + 1e-9)
            ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=7,
                    color="white" if shade > 0.72 or shade < 0.12 else "black")
    fig.colorbar(im, ax=ax, shrink=0.8)
    return _out(fig, path)


def torque_validation(t_model, t_ref, time_s=None, path=None):
    """Computed torque against the reference. Overlay plus 1:1 scatter."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5))
    t = np.arange(len(t_model)) if time_s is None else time_s
    a1.plot(t, t_ref, lw=1.2, label="reference (DME)", color="#888")
    a1.plot(t, t_model, lw=1.0, label="model", color="#c0392b")
    a1.set_xlabel("time (s)"); a1.set_ylabel("torque (Nm)")
    a1.set_title("Torque: model vs reference"); a1.legend(); a1.grid(alpha=.3)

    a2.scatter(t_ref, t_model, s=4, alpha=.3, color="#2980b9")
    lim = [min(np.min(t_ref), np.min(t_model)), max(np.max(t_ref), np.max(t_model))]
    a2.plot(lim, lim, "k--", lw=1, label="1:1")
    err = t_model - t_ref
    a2.set_xlabel("reference (Nm)"); a2.set_ylabel("model (Nm)")
    a2.set_title(f"mean err {err.mean():+.1f} Nm   RMS {np.sqrt((err**2).mean()):.1f} Nm")
    a2.legend(); a2.grid(alpha=.3)
    fig.tight_layout()
    return _out(fig, path)


def residual_grid(residual, inputs: dict, path=None):
    """Residual against each model input -- the diagnostic that matters.

    A flat cloud means that term is fine. A SLOPE tells you which term is
    wrong:
        vs spark delta from MBT -> the SparkEff curve
        vs air mass             -> BaseTorque scaling
        vs RPM                  -> friction coefficients
        vs lambda               -> the LambdaEff curve
    """
    n = len(inputs)
    cols = min(3, n); rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.6 * cols, 3.6 * rows))
    axes = np.atleast_1d(axes).ravel()
    for ax, (name, vals) in zip(axes, inputs.items()):
        vals = np.asarray(vals, dtype=float)
        ok = np.isfinite(vals) & np.isfinite(residual)
        v, r = vals[ok], np.asarray(residual)[ok]
        ax.scatter(v, r, s=4, alpha=.25, color="#16a085")
        # real logs contain NaNs and channels that never vary; either one
        # makes the fit singular, so guard rather than crash
        if v.size > 2 and np.ptp(v) > 1e-9:
            z = np.polyfit(v, r, 1)
            xs = np.linspace(v.min(), v.max(), 50)
            ax.plot(xs, np.polyval(z, xs), "r-", lw=1.6,
                    label=f"slope {z[0]:+.3g}")
        else:
            ax.plot([], [], " ", label="constant - no fit")
        ax.axhline(0, color="k", lw=.8, ls="--")
        ax.set_xlabel(name); ax.set_ylabel("residual (Nm)")
        ax.legend(fontsize=8); ax.grid(alpha=.3)
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle("Residual vs each input  —  a slope names the broken term")
    fig.tight_layout()
    return _out(fig, path)


def coverage(rpm, load, path=None, boost_axis=True):
    """Where the logs actually went. Finds the holes you will extrapolate into."""
    fig, ax = plt.subplots(figsize=(7, 5))
    y = kpa_abs_to_boost_psi(load) if boost_axis else load
    h = ax.hist2d(rpm, y, bins=[24, 18], cmap="magma")
    fig.colorbar(h[3], ax=ax, label="samples")
    ax.set_xlabel("RPM")
    ax.set_ylabel("boost (psi)" if boost_axis else "MAP (kPa)")
    ax.set_title("Data coverage")
    return _out(fig, path)


def _out(fig, path):
    if path:
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    return fig
