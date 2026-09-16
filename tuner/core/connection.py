"""The one boundary the UI is allowed to talk to the ECU through.

Everything on the UI side consumes ECUConnection. DemoConnection is the
first implementation: a fixed operating point so the UI has something to
display. SimulatedECU (Phase 3) and a real serial/CAN transport (later)
drop in behind the same interface with no UI change.
"""
from PySide6.QtCore import QObject, QTimer, Signal


CHANNELS = [
    # key,        label,         unit,      decimals
    ("rpm",       "RPM",         "rpm",     0),
    ("map",       "MAP",         "kPa",     0),
    ("boost",     "Boost",       "psi",     1),
    ("tps",       "TPS",         "%",       0),
    ("lambda",    "Lambda",      "λ",       3),
    ("clt",       "Coolant",     "°C",      0),
    ("iat",       "IAT",         "°C",      0),
    ("spark",     "Spark",       "° BTDC",  1),
    ("mbt",       "MBT",         "° BTDC",  1),
    ("torque",    "Torque",      "Nm",      0),
    ("torque_req", "Torque req", "Nm",      0),
    ("authority", "Authority",   "Nm",      0),
    ("batt",      "Battery",     "V",       1),
]


class ECUConnection(QObject):
    channels_updated = Signal(dict)     # {channel_key: value}
    state_changed = Signal(bool)        # connected?

    name = "None"

    def __init__(self):
        super().__init__()
        self._connected = False
        self._channels = {k: 0.0 for k, *_ in CHANNELS}

    def is_connected(self) -> bool:
        return self._connected

    def channels(self) -> dict:
        return dict(self._channels)

    def connect_ecu(self):
        self._connected = True
        self.state_changed.emit(True)

    def disconnect_ecu(self):
        self._connected = False
        self.state_changed.emit(False)

    # For Phase 2+: read/write tables, burn. Deliberately absent for now so
    # nothing in the UI grows a dependency on them before they exist.


class DemoConnection(ECUConnection):
    """A single fixed operating point, republished at 5 Hz.

    Exists so the gauges, readouts and table cursor show a plausible engine
    instead of a dead screen. It is labelled Demo everywhere it appears.
    """
    name = "Demo"

    POINT = dict(rpm=3450, map=158.0, boost=8.2, tps=62, lambda_=0.882,
                 clt=88, iat=31, spark=17.5, mbt=21.0, torque=312,
                 torque_req=318, authority=141, batt=13.9)

    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)

    def connect_ecu(self):
        p = dict(self.POINT)
        p["lambda"] = p.pop("lambda_")
        self._channels.update(p)
        super().connect_ecu()
        self._tick()
        self._timer.start()

    def disconnect_ecu(self):
        self._timer.stop()
        self._channels = {k: 0.0 for k in self._channels}
        self.channels_updated.emit(self.channels())
        super().disconnect_ecu()

    def _tick(self):
        self.channels_updated.emit(self.channels())
