"""Render the TorqueTune cover art, splash and application icon.

    python tools/make_cover.py

The picture is the VE surface drawn the way the app itself draws it -- the
projection of tuner/ui/surface3d.py and the colour scale of
tuner/ui/colors.py -- over the truth surface the simulator calibrates
against. Regenerate rather than editing the PNGs by hand: the art then
stays honest about the model behind it.

Outputs:
    docs/assets/cover.png            1600x900  README header
    tuner/ui/assets/splash.png        880x420  About box
    tuner/ui/assets/icon.png          512x512  source for the icon
    tuner/ui/assets/torquetune.ico             16..256 px, for Windows
"""
import math
import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt                      # noqa: E402
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage,   # noqa: E402
                           QPainter, QPen, QPolygonF)

from tqmodel.synth import truth_ve                                   # noqa: E402
from tuner.ui.colors import heat                                     # noqa: E402

BG, EDGE, BASE, TEXT, DIM = "#202020", "#3A3A3A", "#5A5A5A", "#C8C8C8", "#8E8E8E"
RPM_LO, RPM_HI, MAP_LO, MAP_HI = 800.0, 7200.0, 30.0, 240.0


def surface(nx=24, ny=18):
    """The truth VE surface, plus the local structure a real head has:
    a resonance band low-mid and the fall-off past peak power."""
    gx, gy = np.meshgrid(np.linspace(RPM_LO, RPM_HI, nx), np.linspace(MAP_LO, MAP_HI, ny))
    return (np.asarray(truth_ve(gx, gy))
            + 0.045 * np.sin(gx / 900.0) * np.cos(gy / 95.0)
            + 0.030 * np.exp(-((gx - 3100.0) / 900.0) ** 2) * np.sin(gy / 60.0)
            - 0.035 * np.exp(-((gx - 6200.0) / 700.0) ** 2))


class Cam:
    """The app's projection, then a fit of everything added to a target rect."""

    def __init__(self, az, el, rect):
        self.az, self.el, self.rect, self.items = az, el, rect, []

    def _raw(self, X, Y, Z):
        a, e = math.radians(self.az), math.radians(self.el)
        X, Y, Z = (np.asarray(v, float) for v in (X, Y, Z))
        xr = X * math.cos(a) - Y * math.sin(a)
        yr = X * math.sin(a) + Y * math.cos(a)
        return xr, -(Z * math.cos(e) + yr * math.sin(e)), yr * math.cos(e) - Z * math.sin(e)

    def add(self, X, Y, Z):
        self.items.append(self._raw(X, Y, Z))
        return len(self.items) - 1

    def fit(self):
        xs = np.concatenate([i[0].ravel() for i in self.items])
        ys = np.concatenate([i[1].ravel() for i in self.items])
        r = self.rect
        self.s = min(r.width() / max(np.ptp(xs), 1e-9), r.height() / max(np.ptp(ys), 1e-9))
        self.ox = r.center().x() - self.s * (xs.min() + xs.max()) / 2
        self.oy = r.center().y() - self.s * (ys.min() + ys.max()) / 2

    def _place(self, t):
        x, y, d = t
        return self.ox + x * self.s, self.oy + y * self.s, d

    def get(self, k):
        return self._place(self.items[k])

    def at(self, X, Y, Z):
        return self._place(self._raw(X, Y, Z))


def normalise(v, zs):
    ny, nx = v.shape
    lo, hi = float(v.min()), float(v.max())
    zn = (v - lo) / max(hi - lo, 1e-9)
    I, J = np.meshgrid(np.arange(nx), np.arange(ny))
    return I / max(nx - 1, 1) - 0.5, J / max(ny - 1, 1) - 0.5, zn * zs - zs / 2, zn, lo, hi


def quads(px, py, pd, zn):
    """Painter's algorithm, exactly as the 3D view does it: far to near."""
    ny, nx = zn.shape
    out = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            d = (pd[j, i] + pd[j, i + 1] + pd[j + 1, i] + pd[j + 1, i + 1]) / 4
            t = (zn[j, i] + zn[j, i + 1] + zn[j + 1, i] + zn[j + 1, i + 1]) / 4
            out.append((d, QPolygonF([QPointF(px[j, i], py[j, i]),
                                      QPointF(px[j, i + 1], py[j, i + 1]),
                                      QPointF(px[j + 1, i + 1], py[j + 1, i + 1]),
                                      QPointF(px[j + 1, i], py[j + 1, i])]), heat(t)))
    out.sort(key=lambda q: -q[0])
    return out


def font(px, bold=False, mono=False):
    f = QFont("DejaVu Sans Mono" if mono else "Liberation Sans")
    f.setPixelSize(px)
    f.setBold(bold)
    return f


CX, CY = np.array([-.5, .5, .5, -.5]), np.array([-.5, -.5, .5, .5])


def draw_surface(p, rect, nx, ny, az=-50.0, el=27.0, zs=0.62, box=True, edges=True, labels=True):
    v = surface(nx, ny)
    X, Y, Z, zn, lo, hi = normalise(v, zs)
    cam = Cam(az, el, rect)
    ks = cam.add(X, Y, Z)
    kb = cam.add(CX, CY, np.full(4, -zs / 2))
    kt = cam.add(CX, CY, np.full(4, zs / 2))
    cam.fit()
    px, py, pd = cam.get(ks)
    bx, by, bd = cam.get(kb)
    tx, ty, _ = cam.get(kt)
    near = int(np.argmin(bd))

    if box:
        p.setPen(QPen(QColor(BASE), 1)); p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(bx[k], by[k]) for k in range(4)]))
        p.setPen(QPen(QColor("#4A4A4A"), 1, Qt.DotLine))
        for k in range(4):
            if k != near:
                p.drawLine(QPointF(bx[k], by[k]), QPointF(tx[k], ty[k]))

    p.setPen(QPen(QColor(EDGE), 1) if edges else Qt.NoPen)
    for _, poly, c in quads(px, py, pd, zn):
        p.setBrush(c)
        p.drawPolygon(poly)

    if box:
        p.setPen(QPen(QColor("#4A4A4A"), 1, Qt.DotLine))
        p.drawLine(QPointF(bx[near], by[near]), QPointF(tx[near], ty[near]))

    if labels:
        ex, ey = float(np.sign(CX[near])), float(np.sign(CY[near]))
        p.setFont(font(15, mono=True)); p.setPen(QColor(DIM))
        for f in np.linspace(0, 1, 5):
            x, y, _ = cam.at([f - 0.5], [ey * 0.56], [-zs / 2])
            p.drawText(QRectF(x[0] - 50, y[0] - 10, 100, 20), Qt.AlignCenter,
                       f"{RPM_LO + f * (RPM_HI - RPM_LO):.0f}")
        x, y, _ = cam.at([0.0], [ey * 0.70], [-zs / 2])
        p.drawText(QRectF(x[0] - 90, y[0] - 10, 180, 20), Qt.AlignCenter, "rpm")
        align = Qt.AlignRight if ex < 0 else Qt.AlignLeft
        for f in np.linspace(0, 1, 4):
            x, y, _ = cam.at([ex * 0.55], [f - 0.5], [-zs / 2])
            p.drawText(QRectF(x[0] - (96 if ex < 0 else 0), y[0] - 10, 96, 20),
                       align | Qt.AlignVCenter, f"{MAP_LO + f * (MAP_HI - MAP_LO):.0f}")
        x, y, _ = cam.at([ex * 0.72], [0.0], [-zs / 2])
        p.drawText(QRectF(x[0] - (120 if ex < 0 else 0), y[0] - 10, 120, 20),
                   align | Qt.AlignVCenter, "kPa")
    return lo, hi


def colour_bar(p, bar, lo, hi):
    for k in range(int(bar.height())):
        p.setPen(heat(1.0 - k / bar.height()))
        p.drawLine(QPointF(bar.left(), bar.top() + k), QPointF(bar.right(), bar.top() + k))
    p.setPen(QPen(QColor(BASE), 1)); p.setBrush(Qt.NoBrush); p.drawRect(bar)
    p.setPen(QColor(TEXT)); p.setFont(font(15, mono=True))
    p.drawText(QRectF(bar.left() - 110, bar.top() - 9, 100, 18), Qt.AlignRight, f"{hi:.2f}")
    p.drawText(QRectF(bar.left() - 110, bar.bottom() - 9, 100, 18), Qt.AlignRight, f"{lo:.2f}")
    p.drawText(QRectF(bar.left() - 110, bar.bottom() + 14, 100, 18), Qt.AlignRight, "VE")


def canvas(w, h):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(BG))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    return img, p


def cover(path, w=1600, h=900):
    img, p = canvas(w, h)
    lo, hi = draw_surface(p, QRectF(150, 250, w - 430, h - 360), 24, 18)
    colour_bar(p, QRectF(w - 78, 300, 14, 250), lo, hi)
    p.setPen(QColor("#F0F0F0")); p.setFont(font(56, bold=True))
    p.drawText(QRectF(70, 74, 900, 66), Qt.AlignLeft | Qt.AlignVCenter, "TorqueTune")
    p.setPen(QColor("#9A9A9A")); p.setFont(font(19, mono=True))
    p.drawText(QRectF(72, 142, 900, 26), Qt.AlignLeft | Qt.AlignVCenter,
               "volumetric efficiency  ·  f(rpm, MAP)")
    p.setPen(QColor("#6A6A6A")); p.setFont(font(15, mono=True))
    p.drawText(QRectF(72, h - 66, 1200, 20), Qt.AlignLeft,
               "torque-structure ECU  ·  B48 + ZF 8HP  ·  speed density")
    p.end()
    img.save(str(path))


def splash(path, w=880, h=420):
    """Same picture, tighter: it sits next to text in the About box."""
    img, p = canvas(w, h)
    draw_surface(p, QRectF(30, 120, w - 60, h - 150), 20, 14,
                 az=-46.0, el=16.0, zs=0.45, box=False, labels=False)
    p.setPen(QColor("#F0F0F0")); p.setFont(font(40, bold=True))
    p.drawText(QRectF(40, 40, w - 80, 46), Qt.AlignLeft | Qt.AlignVCenter, "TorqueTune")
    p.setPen(QColor("#9A9A9A")); p.setFont(font(15, mono=True))
    p.drawText(QRectF(42, 88, w - 80, 22), Qt.AlignLeft | Qt.AlignVCenter,
               "volumetric efficiency  ·  f(rpm, MAP)")
    p.end()
    img.save(str(path))


def icon(path_png, path_ico, size=512):
    """No text, a coarse mesh and no cell edges -- the shape has to survive
    being drawn at 16 px."""
    img, p = canvas(size, size)
    draw_surface(p, QRectF(-size * 0.10, size * 0.02, size * 1.20, size * 0.96),
                 12, 9, az=-46.0, el=38.0, zs=1.05, box=False, edges=False, labels=False)
    p.end()
    img.save(str(path_png))
    from PIL import Image
    Image.open(path_png).save(path_ico, sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])


def main():
    app = QGuiApplication([])                      # noqa: F841  (Qt needs one)
    (ROOT / "docs" / "assets").mkdir(parents=True, exist_ok=True)
    assets = ROOT / "tuner" / "ui" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    cover(ROOT / "docs" / "assets" / "cover.png")
    splash(assets / "splash.png")
    icon(assets / "icon.png", assets / "torquetune.ico")
    print("wrote docs/assets/cover.png, tuner/ui/assets/{splash.png,icon.png,torquetune.ico}")


if __name__ == "__main__":
    main()
