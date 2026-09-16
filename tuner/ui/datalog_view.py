"""Datalog strip chart: stacked traces on a shared time axis."""
import csv
from collections import deque

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

WINDOW_S = 30.0          # rolling live window

pg.setConfigOptions(antialias=False, background="#1B1B1B", foreground="#C8C8C8")

STRIPS = [
    # key,     label,          colour,    (ymin, ymax) or None
    ("rpm",    "RPM",     "#5DA5FF", (0, 8000)),
    ("boost",  "Boost",   "#FFB347", (-15, 25)),
    ("lambda", "Lambda",  "#7BE07B", (0.7, 1.3)),
    ("torque", "Torque",  "#FF6B6B", None),
    ("spark",  "Spark",   "#C99BFF", (-10, 40)),
]


class DatalogView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        bar = QHBoxLayout(); bar.setContentsMargins(4, 2, 4, 2)
        self.b_rec = QPushButton("Record"); self.b_stop = QPushButton("Stop")
        self.b_clear = QPushButton("Clear"); self.b_save = QPushButton("Save…")
        for b in (self.b_rec, self.b_stop, self.b_clear, self.b_save):
            b.setFixedWidth(60)
        self.status = QLabel("Demo log"); self.status.setObjectName("dim")
        legend = QLabel("   ".join(f"<span style='color:{c}'>■</span> {lab}" for _k, lab, c, _r in STRIPS))
        bar.addWidget(self.b_rec); bar.addWidget(self.b_stop); bar.addWidget(self.b_clear)
        bar.addWidget(self.b_save); bar.addSpacing(12); bar.addWidget(self.status); bar.addStretch()
        bar.addWidget(legend)
        self.live = False; self.recording = False
        self._buf = {k: deque() for k in ("t",) + tuple(k for k, *_ in STRIPS)}
        self._rec = []; self._keys = None
        self.b_rec.clicked.connect(self._record); self.b_stop.clicked.connect(self._stop)
        self.b_clear.clicked.connect(self.clear); self.b_save.clicked.connect(self._save)
        self._set_buttons()

        self.glw = pg.GraphicsLayoutWidget()
        self.plots, self.curves = {}, {}
        first = None
        for n, (key, label, colour, yr) in enumerate(STRIPS):
            p = self.glw.addPlot(row=n, col=0)
            p.showGrid(x=True, y=True, alpha=0.18)
            p.getAxis("left").setWidth(56); p.getAxis("left").setPen(pg.mkPen(colour))
            p.getAxis("left").setTextPen(pg.mkPen(colour))
            p.setMouseEnabled(x=True, y=False)
            if yr: p.setYRange(*yr, padding=0)
            if first is None: first = p
            else: p.setXLink(first)
            p.getAxis("bottom").enableAutoSIPrefix(False)
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

    # ---- live ------------------------------------------------------------
    def set_live(self, live: bool):
        self.live = live
        if live: self.clear()
        self.status.setText("Live" if live else "Demo log")
        self._set_buttons()

    def append(self, t: float, ch: dict):
        if not self.live: return
        self._buf["t"].append(t)
        for k in self._buf:
            if k != "t": self._buf[k].append(ch.get(k, 0.0))
        while self._buf["t"] and t - self._buf["t"][0] > WINDOW_S:
            for q in self._buf.values(): q.popleft()
        if self.recording:
            if self._keys is None: self._keys = ["t"] + sorted(ch.keys())
            self._rec.append([t] + [ch.get(k, 0.0) for k in self._keys[1:]])
            self.status.setText(f"Recording — {len(self._rec)} samples")
        tt = np.fromiter(self._buf["t"], float)
        for key, curve in self.curves.items():
            curve.setData(tt, np.fromiter(self._buf[key], float))

    def clear(self):
        for q in self._buf.values(): q.clear()
        for c in self.curves.values(): c.setData([], [])

    def _record(self):
        self._rec, self._keys, self.recording = [], None, True
        self._set_buttons()

    def _stop(self):
        self.recording = False; self.status.setText(f"Stopped — {len(self._rec)} samples")
        self._set_buttons()

    def _save(self):
        if not self._rec: return
        path, _ = QFileDialog.getSaveFileName(self, "Save Datalog", "datalog.csv", "CSV (*.csv)")
        if not path: return
        with open(path, "w", newline="") as f:
            w = csv.writer(f); w.writerow(self._keys); w.writerows(self._rec)
        self.status.setText(f"Saved {len(self._rec)} samples")

    def _set_buttons(self):
        self.b_rec.setEnabled(self.live and not self.recording)
        self.b_stop.setEnabled(self.recording)
        self.b_clear.setEnabled(self.live)
        self.b_save.setEnabled(bool(self._rec) and not self.recording)
