"""Back-calculate VE from logged data -- "VE autotune".

Given what the injectors actually delivered and what lambda actually came
back, you can work out how much air was really in the cylinder, and
therefore what VE really was.

This is how a measured VE surface comes out of road or dyno logs rather
than being authored cell by cell.
"""
import numpy as np
from .model import Engine, ve_from_air


def air_from_fuel(pulse_width_ms, deadtime_ms, flow_g_per_ms, lambda_meas,
                  eng: Engine):
    """Charge mass per cylinder per cycle implied by delivered fuel.

    Accuracy here is entirely limited by injector characterisation. If the
    flow rate or deadtime is wrong, that error lands in the VE table and
    fueling still comes out correct -- which is exactly how a wrong VE
    number hides in a conventional ECU. In torque mode it does not hide.
    """
    fuel_g = (np.asarray(pulse_width_ms) - deadtime_ms) * flow_g_per_ms
    return np.maximum(fuel_g, 0.0) * eng.afr_stoich * np.asarray(lambda_meas)


def ve_from_log(pulse_width_ms, deadtime_ms, flow_g_per_ms, lambda_meas,
                map_kpa, t_charge_k, eng: Engine):
    air = air_from_fuel(pulse_width_ms, deadtime_ms, flow_g_per_ms,
                        lambda_meas, eng)
    return ve_from_air(air, map_kpa, t_charge_k, eng)


def bin_surface(x, y, z, x_edges, y_edges, min_count=3):
    """Bin scattered log samples onto a regular grid.

    Returns (grid, counts). Cells with fewer than min_count samples come
    back as NaN -- deliberately, so thin coverage shows up as a hole in the
    plot instead of being silently interpolated over.
    """
    x, y, z = np.asarray(x), np.asarray(y), np.asarray(z)
    grid = np.full((len(y_edges) - 1, len(x_edges) - 1), np.nan)
    counts = np.zeros_like(grid)
    xi = np.digitize(x, x_edges) - 1
    yi = np.digitize(y, y_edges) - 1
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            m = (xi == j) & (yi == i)
            n = int(m.sum())
            counts[i, j] = n
            if n >= min_count:
                grid[i, j] = float(np.mean(z[m]))
    return grid, counts
