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
from .surface_paint import project as _project

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
        return _project(X, Y, Z, w, h, self.az, self.el, self.zoom)

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

        # base plate; the corner nearest the viewer decides where labels go
        CX, CY = np.array([-.5, .5, .5, -.5]), np.array([-.5, -.5, .5, .5])
        bx, by, bd = self._project(CX, CY, np.full(4, -ZS / 2), w, h)
        tx, ty, _ = self._project(CX, CY, np.full(4, ZS / 2), w, h)
        near = int(np.argmin(bd))
        p.setPen(QPen(BASE, 1)); p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(bx[k], by[k]) for k in range(4)]))
        p.setPen(QPen(BASE, 1, Qt.DotLine))
        for k in range(4):
            if k != near:
                p.drawLine(QPointF(bx[k], by[k]), QPointF(tx[k], ty[k]))

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

        # the near corner's vertical edge, drawn over the surface as a z reference
        p.setPen(QPen(BASE, 1, Qt.DotLine))
        p.drawLine(QPointF(bx[near], by[near]), QPointF(tx[near], ty[near]))

        # labels on the two base edges that meet at the near corner -- these
        # are always in front of the surface, whatever the rotation
        f = QFont(self.font()); f.setPointSize(8); p.setFont(f); p.setPen(TEXT)
        model = self.editor.model
        ex, ey = float(np.sign(CX[near])), float(np.sign(CY[near]))   # outward directions

        def text_at(X, Y, Z, label, align_out_x=False, cx_hint=None):
            lx, ly, _ = self._project(np.array([X]), np.array([Y]), np.array([Z]), w, h)
            if align_out_x:
                if lx[0] < w / 2:
                    p.drawText(QRectF(lx[0] - 64, ly[0] - 7, 64, 14), Qt.AlignRight | Qt.AlignVCenter, label)
                else:
                    p.drawText(QRectF(lx[0], ly[0] - 7, 64, 14), Qt.AlignLeft | Qt.AlignVCenter, label)
            else:
                p.drawText(QRectF(lx[0] - 30, ly[0] - 7, 60, 14), Qt.AlignCenter, label)

        step_x = max(1, int(np.ceil(nx / 8)))
        for i in range(0, nx, step_x):
            text_at(X[0, i], CY[near] + ey * 0.08, -ZS / 2, f"{t.x[i]:g}")
        text_at(0.0, CY[near] + ey * 0.22, -ZS / 2, t.x_name)

        step_y = max(1, int(np.ceil(ny / 6)))
        corner_j = 0 if CY[near] < 0 else ny - 1       # the y tick that would land on the corner
        for j in range(0, ny, step_y):
            if j == corner_j:
                continue
            text_at(CX[near] + ex * 0.06, Y[j, 0], -ZS / 2,
                    str(model.headerData(model.row_of(j), Qt.Vertical)), align_out_x=True)
        text_at(CX[near] + ex * 0.32, 0.0, -ZS / 2, model.y_header_title(), align_out_x=True)

        # colour bar legend: the z range, on the dark background where it is readable
        bar = QRectF(w - 34, 34, 12, max(80, h * 0.30))
        for k in range(int(bar.height())):
            p.setPen(heat(1.0 - k / bar.height()))
            p.drawLine(QPointF(bar.left(), bar.top() + k), QPointF(bar.right(), bar.top() + k))
        p.setPen(QPen(BASE, 1)); p.setBrush(Qt.NoBrush); p.drawRect(bar)
        p.setPen(TEXT)
        p.drawText(QRectF(bar.left() - 70, bar.top() - 7, 66, 14), Qt.AlignRight | Qt.AlignVCenter, t.fmt.format(vmax))
        p.drawText(QRectF(bar.left() - 70, bar.bottom() - 7, 66, 14), Qt.AlignRight | Qt.AlignVCenter, t.fmt.format(vmin))
        if t.unit:
            p.drawText(QRectF(bar.left() - 70, bar.bottom() + 8, 78, 14), Qt.AlignRight | Qt.AlignVCenter, t.unit)

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
