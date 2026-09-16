"""Datalog strip chart: stacked traces on a shared time axis."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

pg.setConfigOptions(antialias=False, background="#1B1B1B", foreground="#C8C8C8")

STRIPS = [
    # key,     label,          colour,    (ymin, ymax) or None
    ("rpm",    "RPM",     "#5DA5FF", (0, 8000)),
    ("boost",  "Boost",   "#FFB347", (-15, 25)),
    ("lambda", "Lambda",  "#7BE07B", (0.7, 1.3)),
    ("torque", "Torque",  "#FF6B6B", None),
]


class DatalogView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        bar = QHBoxLayout(); bar.setContentsMargins(4, 2, 4, 2)
        self.b_rec = QPushButton("Record"); self.b_stop = QPushButton("Stop")
        self.b_clear = QPushButton("Clear")
        for b in (self.b_rec, self.b_stop, self.b_clear):
            b.setFixedWidth(60); b.setEnabled(False)
            b.setToolTip("Live logging — Phase 3")
        self.status = QLabel("Demo log — not recording"); self.status.setObjectName("dim")
        bar.addWidget(self.b_rec); bar.addWidget(self.b_stop); bar.addWidget(self.b_clear)
        bar.addSpacing(12); bar.addWidget(self.status); bar.addStretch()

        self.glw = pg.GraphicsLayoutWidget()
        self.plots, self.curves = {}, {}
        first = None
        for n, (key, label, colour, yr) in enumerate(STRIPS):
            p = self.glw.addPlot(row=n, col=0)
            p.setLabel("left", label); p.showGrid(x=True, y=True, alpha=0.18)
            p.getAxis("left").setWidth(64)
            p.setMouseEnabled(x=True, y=False)
            if yr: p.setYRange(*yr, padding=0)
            if first is None: first = p
            else: p.setXLink(first)
            if n < len(STRIPS) - 1: p.hideAxis("bottom")
            else: p.setLabel("bottom", "time (s)")
            self.plots[key] = p
            self.curves[key] = p.plot(pen=pg.mkPen(colour, width=1))
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addLayout(bar); lay.addWidget(self.glw)

    def set_log(self, t: np.ndarray, channels: dict):
        for key, curve in self.curves.items():
            if key in channels:
                curve.setData(t, channels[key])
