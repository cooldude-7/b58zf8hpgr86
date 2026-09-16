"""Software-rendered 3D surface. QPainter only -- no OpenGL, no driver risk.

Painter's algorithm: project every cell quad, sort far-to-near, fill with
the heat colour. At table sizes (a few hundred quads) this is instant, and
it is how tuning software of the period drew its surfaces.
"""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .colors import heat

BG = QColor("#202020")
EDGE = QColor("#3A3A3A")
BASE = QColor("#5A5A5A")
TEXT = QColor("#C8C8C8")
CURSOR = QColor("#FF3030")
ZS = 0.55           # height of the surface in model units (the box is 1 x 1)


class Surface3D(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.az, self.el, self.zoom = -52.0, 30.0, 1.0
        self._drag = None
        self.setMinimumSize(200, 150)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---- projection ---------------------------------------------------
    def _project(self, X, Y, Z, w, h):
        az, el = math.radians(self.az), math.radians(self.el)
        xr = X * math.cos(az) - Y * math.sin(az)
        yr = X * math.sin(az) + Y * math.cos(az)
        sx = xr
        sy = Z * math.cos(el) + yr * math.sin(el)
        depth = yr * math.cos(el) - Z * math.sin(el)
        S = min(w, h) * 0.66 * self.zoom
        return w / 2 + sx * S, h / 2 + h * 0.05 - sy * S, depth

    # ---- painting -----------------------------------------------------
    def paintEvent(self, ev):
        t = self.editor.table
        v = t.values
        ny, nx = v.shape
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), BG)

        vmin, vmax = float(np.nanmin(v)), float(np.nanmax(v))
        rng = max(vmax - vmin, 1e-9)
        zn = (v - vmin) / rng
        I, J = np.meshgrid(np.arange(nx), np.arange(ny))
        X = (I / max(nx - 1, 1)) - 0.5
        Y = (J / max(ny - 1, 1)) - 0.5
        Z = zn * ZS - ZS / 2
        px, py, pd = self._project(X, Y, Z, w, h)

        # base plate
        bx, by, _ = self._project(np.array([-.5, .5, .5, -.5]), np.array([-.5, -.5, .5, .5]),
                                  np.full(4, -ZS / 2), w, h)
        p.setPen(QPen(BASE, 1)); p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(bx[k], by[k]) for k in range(4)]))
        # vertical edges at the back corners help the eye read height
        for k in range(4):
            tx, ty, _ = self._project(np.array([bx[k] * 0 + [-.5, .5, .5, -.5][k]]),
                                      np.array([[-.5, -.5, .5, .5][k]]), np.array([ZS / 2]), w, h)
            p.setPen(QPen(BASE, 1, Qt.DotLine))
            p.drawLine(QPointF(bx[k], by[k]), QPointF(tx[0], ty[0]))

        # surface quads, far to near
        quads = []
        for j in range(ny - 1):
            for i in range(nx - 1):
                d = (pd[j, i] + pd[j, i + 1] + pd[j + 1, i] + pd[j + 1, i + 1]) / 4
                c = heat((zn[j, i] + zn[j, i + 1] + zn[j + 1, i] + zn[j + 1, i + 1]) / 4)
                poly = QPolygonF([QPointF(px[j, i], py[j, i]), QPointF(px[j, i + 1], py[j, i + 1]),
                                  QPointF(px[j + 1, i + 1], py[j + 1, i + 1]),
                                  QPointF(px[j + 1, i], py[j + 1, i])])
                quads.append((d, poly, c))
        quads.sort(key=lambda q: -q[0])
        p.setPen(QPen(EDGE, 1))
        for _, poly, c in quads:
            p.setBrush(c); p.drawPolygon(poly)

        # axis labels: x breakpoints along the y=min edge, y along the x=min edge
        f = QFont(self.font()); f.setPointSize(8); p.setFont(f); p.setPen(TEXT)
        sx = max(1, nx // 8); sy = max(1, ny // 6)
        for i in range(0, nx, sx):
            lx, ly, _ = self._project(np.array([X[0, i]]), np.array([-0.56]), np.array([-ZS / 2]), w, h)
            p.drawText(QRectF(lx[0] - 24, ly[0] - 7, 48, 14), Qt.AlignCenter, f"{t.x[i]:g}")
        model = self.editor.model
        for j in range(0, ny, sy):
            lx, ly, _ = self._project(np.array([-0.56]), np.array([Y[j, 0]]), np.array([-ZS / 2]), w, h)
            p.drawText(QRectF(lx[0] - 40, ly[0] - 7, 48, 14), Qt.AlignRight | Qt.AlignVCenter,
                       str(model.headerData(model.row_of(j), Qt.Vertical)))
        lx, ly, _ = self._project(np.array([0.0]), np.array([-0.70]), np.array([-ZS / 2]), w, h)
        p.drawText(QRectF(lx[0] - 60, ly[0] - 7, 120, 14), Qt.AlignCenter, t.x_name)
        lx, ly, _ = self._project(np.array([-0.78]), np.array([0.0]), np.array([-ZS / 2]), w, h)
        p.drawText(QRectF(lx[0] - 60, ly[0] - 7, 120, 14), Qt.AlignCenter, model.y_header_title())
        # z range beside the x=max, y=min corner edge, clear of the y labels
        for zv, lab in ((-ZS / 2, t.fmt.format(vmin)), (ZS / 2, t.fmt.format(vmax))):
            lx, ly, _ = self._project(np.array([0.5]), np.array([-0.5]), np.array([zv]), w, h)
            p.drawText(QRectF(lx[0] + 6, ly[0] - 7, 64, 14), Qt.AlignLeft | Qt.AlignVCenter, lab)

        # live cursor
        if self.editor.cursor is not None and self.editor.cursor_xy is not None:
            xv, yv = self.editor.cursor_xy
            cj, ci, fy, fx = self.editor.cursor
            cx = ((ci + fx) / max(nx - 1, 1)) - 0.5
            cy = ((cj + fy) / max(ny - 1, 1)) - 0.5
            cz = (t.lookup(xv, yv) - vmin) / rng * ZS - ZS / 2
            ax, ay, _ = self._project(np.array([cx, cx]), np.array([cy, cy]), np.array([-ZS / 2, cz]), w, h)
            p.setPen(QPen(QColor("#FFFFFF"), 1, Qt.DashLine))
            p.drawLine(QPointF(ax[0], ay[0]), QPointF(ax[1], ay[1]))
            p.setPen(QPen(QColor("#FFFFFF"), 1.5)); p.setBrush(CURSOR)
            p.drawEllipse(QPointF(ax[1], ay[1]), 5, 5)

        p.setPen(TEXT)
        p.drawText(QRectF(8, 6, w - 16, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{t.title}    drag to rotate · wheel to zoom")

    # ---- interaction --------------------------------------------------
    def mousePressEvent(self, ev):
        self._drag = (ev.position(), self.az, self.el); self.setFocus()

    def mouseMoveEvent(self, ev):
        if self._drag:
            p0, az0, el0 = self._drag
            d = ev.position() - p0
            self.az = az0 + d.x() * 0.5
            self.el = min(max(el0 + d.y() * 0.5, 5.0), 85.0)
            self.update()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def wheelEvent(self, ev):
        self.zoom = min(max(self.zoom * (1.1 ** (ev.angleDelta().y() / 120.0)), 0.4), 3.0)
        self.update()

    def keyPressEvent(self, ev):
        if not self.editor.handle_key(ev):
            super().keyPressEvent(ev)
