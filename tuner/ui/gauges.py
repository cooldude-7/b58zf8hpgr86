"""Round black-face gauges and numeric readouts."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

FACE = QColor("#101010")
RING = QColor("#3A3A3A")
TICK = QColor("#E8E8E8")
NEEDLE = QColor("#E03030")
REDZONE = QColor("#B02020")
SWEEP_START = 225.0     # degrees, standard 270-degree sweep
SWEEP = 270.0


class RoundGauge(QWidget):
    def __init__(self, title, unit, vmin, vmax, major, redline=None,
                 decimals=0, label_div=1.0, label_every=1, parent=None):
        super().__init__(parent)
        self.title, self.unit = title, unit
        self.vmin, self.vmax, self.major = vmin, vmax, major
        self.redline, self.decimals = redline, decimals
        self.label_div, self.label_every = label_div, label_every
        self.value = vmin
        self.setMinimumSize(96, 96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_value(self, v):
        v = min(max(v, self.vmin), self.vmax)
        if v != self.value:
            self.value = v
            self.update()

    def _angle(self, v):
        f = (v - self.vmin) / (self.vmax - self.vmin)
        return SWEEP_START - f * SWEEP

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        d = min(w, h) - 4
        rect = QRectF((w - d) / 2, (h - d) / 2, d, d)
        cx, cy, r = rect.center().x(), rect.center().y(), d / 2

        p.setPen(QPen(RING, 2)); p.setBrush(FACE)
        p.drawEllipse(rect)

        if self.redline is not None:
            a0, a1 = self._angle(self.redline), self._angle(self.vmax)
            p.setPen(QPen(REDZONE, max(3, r * 0.07), Qt.SolidLine, Qt.FlatCap))
            arc = rect.adjusted(r * 0.10, r * 0.10, -r * 0.10, -r * 0.10)
            p.drawArc(arc, int(a0 * 16), int((a1 - a0) * 16))

        n_major = int(round((self.vmax - self.vmin) / self.major))
        f_small = QFont(self.font()); f_small.setPointSizeF(max(6.0, r * 0.10))
        p.setFont(f_small)
        for k in range(n_major * 5 + 1):
            v = self.vmin + k * self.major / 5
            a = math.radians(self._angle(v))
            is_major = k % 5 == 0
            l = r * (0.16 if is_major else 0.08)
            p.setPen(QPen(TICK, 2 if is_major else 1))
            p.drawLine(QPointF(cx + (r - r * 0.12) * math.cos(a), cy - (r - r * 0.12) * math.sin(a)),
                       QPointF(cx + (r - r * 0.12 - l) * math.cos(a), cy - (r - r * 0.12 - l) * math.sin(a)))
            if is_major and (k // 5) % self.label_every == 0:
                tx = cx + (r * 0.60) * math.cos(a)
                ty = cy - (r * 0.60) * math.sin(a)
                lv = v / self.label_div
                label = f"{lv:g}" if self.major / self.label_div >= 1 else f"{lv:.1f}"
                p.setPen(TICK)
                p.drawText(QRectF(tx - 18, ty - 8, 36, 16), Qt.AlignCenter, label)

        f_title = QFont(self.font()); f_title.setPointSizeF(max(7.0, r * 0.13))
        p.setFont(f_title); p.setPen(QColor("#B8B8B8"))
        p.drawText(QRectF(cx - r, cy - r * 0.50, 2 * r, r * 0.25), Qt.AlignCenter, self.title)

        a = math.radians(self._angle(self.value))
        tip = QPointF(cx + r * 0.80 * math.cos(a), cy - r * 0.80 * math.sin(a))
        base_l = QPointF(cx + r * 0.06 * math.cos(a + math.pi / 2), cy - r * 0.06 * math.sin(a + math.pi / 2))
        base_r = QPointF(cx + r * 0.06 * math.cos(a - math.pi / 2), cy - r * 0.06 * math.sin(a - math.pi / 2))
        tail = QPointF(cx - r * 0.14 * math.cos(a), cy + r * 0.14 * math.sin(a))
        p.setPen(Qt.NoPen); p.setBrush(NEEDLE)
        p.drawPolygon(QPolygonF([tip, base_l, tail, base_r]))
        p.setBrush(QColor("#505050")); p.setPen(QPen(QColor("#808080"), 1))
        p.drawEllipse(QPointF(cx, cy), r * 0.08, r * 0.08)

        f_val = QFont("Consolas"); f_val.setStyleHint(QFont.Monospace)
        f_val.setPointSizeF(max(8.0, r * 0.18)); f_val.setBold(True)
        p.setFont(f_val); p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(cx - r, cy + r * 0.56, 2 * r, r * 0.28), Qt.AlignCenter,
                   f"{self.value:.{self.decimals}f} {self.unit}".strip())


class ReadoutGrid(QWidget):
    """Label / value pairs in two columns, monospace values right-aligned."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items     # [(key, label, unit, decimals)]
        self.values = {}
        g = QGridLayout(self)
        g.setContentsMargins(6, 2, 6, 4); g.setHorizontalSpacing(8); g.setVerticalSpacing(1)
        mono = QFont("Consolas"); mono.setStyleHint(QFont.Monospace); mono.setPointSize(9)
        for n, (key, label, unit, dec) in enumerate(items):
            col, row = (n % 2) * 3, n // 2
            lab = QLabel(label); lab.setObjectName("dim")
            val = QLabel("—"); val.setFont(mono); val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setMinimumWidth(52)
            un = QLabel(unit); un.setObjectName("dim")
            g.addWidget(lab, row, col); g.addWidget(val, row, col + 1); g.addWidget(un, row, col + 2)
            self.values[key] = (val, dec)
        g.setColumnStretch(2, 1); g.setColumnStretch(5, 1)

    def update_channels(self, ch: dict):
        for key, (lab, dec) in self.values.items():
            if key in ch:
                lab.setText(f"{ch[key]:.{dec}f}")


class GaugePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.g_rpm = RoundGauge("RPM ×1000", "", 0, 8000, 1000, redline=7200, label_div=1000)
        self.g_boost = RoundGauge("BOOST", "psi", -20, 30, 10, redline=20, decimals=1)
        self.g_lambda = RoundGauge("LAMBDA", "", 0.70, 1.30, 0.10, decimals=3, label_every=2)
        self.g_clt = RoundGauge("COOLANT", "°C", 40, 140, 10, redline=110, label_every=2)
        grid = QGridLayout()
        grid.setContentsMargins(4, 4, 4, 0); grid.setSpacing(4)
        grid.addWidget(self.g_rpm, 0, 0); grid.addWidget(self.g_boost, 0, 1)
        grid.addWidget(self.g_lambda, 1, 0); grid.addWidget(self.g_clt, 1, 1)
        self.readouts = ReadoutGrid([
            ("tps", "TPS", "%", 0), ("iat", "IAT", "°C", 0),
            ("spark", "Spark", "°", 1), ("mbt", "MBT", "°", 1),
            ("torque", "Torque", "Nm", 0), ("torque_req", "Requested", "Nm", 0),
            ("authority", "Authority", "Nm", 0), ("batt", "Battery", "V", 1),
        ])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(2)
        lay.addLayout(grid, 1); lay.addWidget(self.readouts)

    def update_channels(self, ch: dict):
        self.g_rpm.set_value(ch.get("rpm", 0)); self.g_boost.set_value(ch.get("boost", 0))
        self.g_lambda.set_value(ch.get("lambda", 1.0)); self.g_clt.set_value(ch.get("clt", 40))
        self.readouts.update_channels(ch)
