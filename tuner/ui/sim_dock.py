"""Simulator controls: the virtual pedal, dyno/road mode, test shift."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

PHASE_NAMES = {0: "idle", 1: "fill", 2: "torque phase", 3: "inertia phase"}
COORD_NAMES = {0: "idle", 1: "cutting", 2: "holding", 3: "restoring"}


class SimulatorDock(QScrollArea):
    def __init__(self, sim, parent=None):
        super().__init__(parent)
        self.sim = sim
        self.setWidgetResizable(True); self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget(); self.setWidget(inner)
        lay = QVBoxLayout(inner); lay.setContentsMargins(6, 2, 6, 2); lay.setSpacing(4)

        # pedal
        box = QGroupBox("Virtual pedal"); g = QGridLayout(box)
        self.pedal = QSlider(Qt.Vertical); self.pedal.setRange(0, 100); self.pedal.setValue(0)
        self.pedal.setTickPosition(QSlider.TicksBothSides); self.pedal.setTickInterval(25)
        self.pedal.setMinimumHeight(80)
        self.l_pedal = QLabel("0 %"); self.l_pedal.setAlignment(Qt.AlignCenter)
        f = self.l_pedal.font(); f.setPointSize(14); f.setBold(True); self.l_pedal.setFont(f)
        g.addWidget(self.pedal, 0, 0, 1, 1, Qt.AlignHCenter); g.addWidget(self.l_pedal, 1, 0)
        hint = QLabel("drag, or click and use ↑ ↓"); hint.setObjectName("dim"); hint.setAlignment(Qt.AlignCenter); hint.setWordWrap(True)
        g.addWidget(hint, 2, 0)
        lay.addWidget(box)

        # mode
        box = QGroupBox("Load"); v = QVBoxLayout(box)
        self.r_road = QRadioButton("Road — drive the car"); self.r_dyno = QRadioButton("Dyno — hold RPM")
        self.r_road.setChecked(True)
        row = QHBoxLayout(); row.addWidget(QLabel("Setpoint")); self.rpm_set = QSpinBox()
        self.rpm_set.setRange(800, 7500); self.rpm_set.setSingleStep(100); self.rpm_set.setValue(3000)
        self.rpm_set.setSuffix(" rpm"); self.rpm_set.setEnabled(False); row.addWidget(self.rpm_set); row.addStretch()
        v.addWidget(self.r_road); v.addWidget(self.r_dyno); v.addLayout(row)
        lay.addWidget(box)

        # shifting
        box = QGroupBox("Transmission"); v = QVBoxLayout(box)
        row = QHBoxLayout()
        self.b_up = QPushButton("Shift up"); self.b_down = QPushButton("Shift down"); self.b_reset = QPushButton("Stop car")
        row.addWidget(self.b_up); row.addWidget(self.b_down); row.addWidget(self.b_reset)
        self.c_bug = QCheckBox("Air-chase bug")
        self.c_bug.setToolTip("Let the air path compensate for the shift cut, diluting it -- the classic mistake")
        self.l_phase = QLabel("Shift: idle"); self.l_phase.setWordWrap(True)
        self.l_coord = QLabel(); self.l_coord.setWordWrap(True)
        self.l_coord.setObjectName("dim")
        self.b_reload = QPushButton("Reload coordinator.py")
        v.addLayout(row); v.addWidget(self.c_bug); v.addWidget(self.l_phase); v.addWidget(self.l_coord)
        v.addWidget(self.b_reload)
        lay.addWidget(box)
        lay.addStretch()

        self.pedal.valueChanged.connect(self._pedal)
        self.r_dyno.toggled.connect(self._mode)
        self.rpm_set.valueChanged.connect(lambda v: setattr(self.sim, "dyno_rpm", float(v)))
        self.b_up.clicked.connect(lambda: self.sim.request_shift(True))
        self.b_down.clicked.connect(lambda: self.sim.request_shift(False))
        self.b_reset.clicked.connect(self._reset)
        self.c_bug.toggled.connect(self.sim.set_bug)
        self.b_reload.clicked.connect(self._reload)
        self._coord_status()

    def _pedal(self, v):
        self.sim.pedal = v / 100.0; self.l_pedal.setText(f"{v} %")

    def _mode(self, dyno):
        self.sim.mode = "dyno" if dyno else "road"
        self.rpm_set.setEnabled(dyno); self.b_up.setEnabled(not dyno); self.b_down.setEnabled(not dyno)
        if dyno: self.sim.dyno_rpm = float(self.rpm_set.value())

    def _reset(self):
        self.sim.reset(); self.pedal.setValue(0)

    def _reload(self):
        self.sim.load_coordinator(); self._coord_status()

    def _coord_status(self):
        if self.sim.coord is None:
            self.l_coord.setText(f"Coordinator: not loaded — {self.sim.coord_error}")
        else:
            self.l_coord.setText("Coordinator: tools/shift/coordinator.py loaded")

    def update_channels(self, ch: dict):
        ph = PHASE_NAMES.get(int(ch.get("shift_phase", 0)), "idle")
        cp = COORD_NAMES.get(int(ch.get("coord_phase", 0)), "idle")
        if ph != "idle":
            self.l_phase.setText(f"Shift {int(ch.get('shift_from', 0))} → {int(ch.get('shift_to', 0))}: {ph}   "
                                 f"coordinator: {cp}   target {ch.get('torque_req', 0):.0f} Nm")
        else:
            self.l_phase.setText(f"Shift: idle    gear {int(ch.get('gear', 1))}    coordinator: {cp}")
