"""Projection and quad painting for the 3D surface.

Lifted out of Surface3D so the start-up screen draws with the same maths
and the same heat scale as the table view. One implementation means the
two cannot drift apart: change the projection and both move.
"""
import math

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPolygonF

from .colors import heat


def project(X, Y, Z, w, h, az, el, zoom, y_bias=0.05):
    """Model coordinates in a 1 x 1 x zs box to screen pixels.

    Returns (x, y, depth); depth is larger for points further away, which
    is what the painter's algorithm sorts on.
    """
    a, e = math.radians(az), math.radians(el)
    xr = X * math.cos(a) - Y * math.sin(a)
    yr = X * math.sin(a) + Y * math.cos(a)
    sy = Z * math.cos(e) + yr * math.sin(e)
    depth = yr * math.cos(e) - Z * math.sin(e)
    s = min(w, h) * 0.66 * zoom
    return w / 2 + xr * s, h / 2 + h * y_bias - sy * s, depth


def quad_polys(px, py, pd, zn):
    """Cell quads as (polygon, colour), sorted far to near."""
    ny, nx = zn.shape
    out = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            d = (pd[j, i] + pd[j, i + 1] + pd[j + 1, i] + pd[j + 1, i + 1]) / 4
            t = (zn[j, i] + zn[j, i + 1] + zn[j + 1, i] + zn[j + 1, i + 1]) / 4
            out.append((d, QPolygonF([QPointF(px[j, i], py[j, i]),
                                      QPointF(px[j, i + 1], py[j, i + 1]),
                                      QPointF(px[j + 1, i + 1], py[j + 1, i + 1]),
                                      QPointF(px[j + 1, i], py[j + 1, i])]),
                        heat(t)))
    out.sort(key=lambda q: -q[0])
    return [(poly, c) for _, poly, c in out]


def unit_grid(values, zs):
    """Normalise a table to the unit box: x and y in [-0.5, 0.5], z scaled
    to zs, plus the 0..1 heights the colour scale wants."""
    ny, nx = values.shape
    lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
    zn = (values - lo) / max(hi - lo, 1e-9)
    I, J = np.meshgrid(np.arange(nx), np.arange(ny))
    return (I / max(nx - 1, 1) - 0.5, J / max(ny - 1, 1) - 0.5,
            zn * zs - zs / 2, zn, lo, hi)
