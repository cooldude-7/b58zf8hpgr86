"""Grouped-form settings pages, and a placeholder for what is not built."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDoubleSpinBox, QFormLayout, QGroupBox, QLabel,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

# key -> (label, unit, min, max, decimals, step)
FIELDS = {
    "n_cyl": ("Cylinders", "", 1, 16, 0, 1),
    "displacement_l": ("Displacement", "L", 0.5, 10.0, 3, 0.1),
    "compression_ratio": ("Compression ratio", ":1", 6.0, 16.0, 1, 0.1),
    "stroke_m": ("Stroke", "m", 0.040, 0.150, 4, 0.001),
    "afr_stoich": ("Stoichiometric AFR", "", 5.0, 20.0, 2, 0.1),
    "rev_limit": ("Rev limit", "rpm", 3000, 12000, 0, 100),
    "injector_flow_cc_min": ("Injector flow", "cc/min", 100, 5000, 0, 10),
    "injector_deadtime_ms": ("Injector deadtime", "ms", 0.0, 3.0, 2, 0.05),
    "fuel_pressure_kpa": ("Base fuel pressure", "kPa", 100, 30000, 0, 10),
    "trigger_teeth": ("Teeth on the wheel", "", 4, 120, 0, 1),
    "trigger_missing": ("Missing teeth", "", 0, 4, 0, 1),
    "trigger_gap_to_tdc_deg": ("First tooth after gap, BTDC", "°", 0.0, 360.0, 1, 1.0),
    "cam_edge_angle_deg": ("Cam edge angle", "°", 0.0, 720.0, 1, 1.0),
    "cam_tolerance_deg": ("Cam tolerance", "°", 1.0, 90.0, 1, 1.0),
    "dwell_ms": ("Dwell", "ms", 0.5, 8.0, 2, 0.1),
    "soi_btdc_deg": ("Start of injection, BTDC", "°", 0.0, 720.0, 1, 5.0),
    "boost_max_kpa": ("Boost ceiling", "kPa abs", 100.0, 400.0, 0, 5.0),
    "overboost_cut_kpa": ("Overboost cut", "kPa abs", 100.0, 450.0, 0, 5.0),
    "max_cut_retard": ("Max cut retard", "°", 5.0, 60.0, 1, 1.0),
}

# Shown at the top of a page when the numbers on it are not yet
# measurements. Better a banner than a footnote nobody reads.
WARNINGS = {
    "trigger": ("These are placeholders, not measurements. The crank wheel, "
                "the gap position and both cam patterns must be confirmed "
                "with a scope on the real engine before the ECU is allowed "
                "to fire a coil."),
}

PAGES = {
    "engine": [("Geometry", ["n_cyl", "displacement_l", "compression_ratio", "stroke_m"]),
               ("Fuel", ["afr_stoich"]),
               ("Limits", ["rev_limit"])],
    "injectors": [("Injector characterisation",
                   ["injector_flow_cc_min", "injector_deadtime_ms", "fuel_pressure_kpa"])],
    "friction": [],
    "trigger": [("Crank wheel", ["trigger_teeth", "trigger_missing",
                                 "trigger_gap_to_tdc_deg"]),
                ("Cam phase", ["cam_edge_angle_deg", "cam_tolerance_deg"]),
                ("Event timing", ["dwell_ms", "soi_btdc_deg"])],
    "limits": [("Boost", ["boost_max_kpa", "overboost_cut_kpa"]),
               ("Torque cut", ["max_cut_retard"])],
}


class SettingsPage(QWidget):
    changed = Signal()

    def __init__(self, key: str, engine: dict, parent=None):
        super().__init__(parent)
        self.engine = engine
        inner = QWidget()
        lay = QVBoxLayout(inner); lay.setContentsMargins(8, 6, 8, 6); lay.setSpacing(8)
        if key in WARNINGS:
            warn = QLabel(WARNINGS[key])
            warn.setWordWrap(True)
            warn.setStyleSheet("QLabel { background: #FFF4D6; border: 1px solid "
                               "#D9B24C; padding: 6px; }")
            lay.addWidget(warn)
        for group, keys in PAGES.get(key, []):
            box = QGroupBox(group)
            form = QFormLayout(box); form.setHorizontalSpacing(12); form.setVerticalSpacing(4)
            for k in keys:
                label, unit, lo, hi, dec, step = FIELDS[k]
                if dec == 0:
                    w = QSpinBox(); w.setRange(int(lo), int(hi)); w.setSingleStep(int(step))
                    w.setValue(int(engine.get(k, lo)))
                else:
                    w = QDoubleSpinBox(); w.setRange(lo, hi); w.setDecimals(dec)
                    w.setSingleStep(step); w.setValue(float(engine.get(k, lo)))
                w.setFixedWidth(110)
                if unit: w.setSuffix(f"  {unit}")
                w.valueChanged.connect(lambda v, k=k: self._set(k, v))
                form.addRow(label + ":", w)
            lay.addWidget(box)
        if key == "friction":
            box = QGroupBox("Chen-Flynn coefficients")
            form = QFormLayout(box)
            cf = engine.get("chen_flynn", [0, 0, 0, 0])
            for n, name in enumerate(("A  (constant, bar)", "B  (× peak pressure)",
                                      "C  (× piston speed)", "D  (× piston speed²)")):
                w = QDoubleSpinBox(); w.setDecimals(5); w.setRange(0, 5); w.setSingleStep(0.001)
                w.setValue(float(cf[n])); w.setFixedWidth(110)
                w.valueChanged.connect(lambda v, n=n: self._set_cf(n, v))
                form.addRow(name + ":", w)
            lay.addWidget(box)
        lay.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(inner)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.addWidget(scroll)

    def _set(self, k, v):
        self.engine[k] = v
        self.changed.emit()

    def _set_cf(self, n, v):
        self.engine.setdefault("chen_flynn", [0, 0, 0, 0])[n] = v
        self.changed.emit()


class PlaceholderPage(QWidget):
    def __init__(self, label: str, phase: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        t = QLabel(f"<b>{label}</b>")
        s = QLabel(f"Not available in this build ({phase})."); s.setObjectName("dim")
        lay.addWidget(t); lay.addWidget(s); lay.addStretch()
        lay.setContentsMargins(10, 8, 10, 8)
