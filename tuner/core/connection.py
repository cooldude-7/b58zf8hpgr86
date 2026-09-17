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
    ("knock",     "Knock limit", "° BTDC",  1),
    ("cut_deg",   "Cut retard",  "°",       1),
    ("overrun",   "Overrun cut", "",        0),
    ("air",       "Air mass",    "g/cyl",   3),
    ("ve",        "VE",          "",        3),
    ("gear",      "Gear",        "",        0),
    ("ratio",     "Ratio",       "",        3),
    ("turbine_rpm", "Turbine",   "rpm",     0),
    ("output_rpm", "Output",     "rpm",     0),
    ("speed",     "Speed",       "km/h",    0),
    ("line_bar",  "Line press.", "bar",     1),
    ("tc_lock",   "TC lock",     "",        0),
    ("shift_phase", "Shift phase", "",      0),
    ("coord_phase", "Coord phase", "",      0),
    ("shift_from", "Shift from",  "",       0),
    ("shift_to",  "Shift to",    "",        0),
    ("p_a", "Element A", "bar", 1), ("p_b", "Element B", "bar", 1), ("p_c", "Element C", "bar", 1),
    ("p_d", "Element D", "bar", 1), ("p_e", "Element E", "bar", 1),
    # fuel path
    ("pw_ms",     "Pulse width", "ms",    2),
    ("inj_duty",  "Inj duty",    "%",     0),
    ("fuel_mass", "Fuel mass",   "mg",    1),
    ("rail_kpa",  "Rail press.", "kPa",   0),
    # knock
    ("knock_retard", "Knock ret.", "°",   1),
    ("knock_count",  "Knock ct",   "",    0),
    # safety and monitor
    ("pedal_a",   "Pedal A",     "%",     0),
    ("pedal_b",   "Pedal B",     "%",     0),
    ("tps_a",     "TPS A",       "%",     0),
    ("tps_b",     "TPS B",       "%",     0),
    ("torque_permissible", "Tq permis.", "Nm", 0),
    ("monitor_state", "Monitor",  "",     0),
    ("limp_level", "Limp",       "",      0),
    ("fault_code", "Fault",      "",      0),
    ("coord_fault", "Coord flt", "",      0),
    ("shift_inhibit", "Shift inh", "",    0),
]


class ProtocolError(RuntimeError):
    """The ECU rejected a request, or answered with something impossible."""


class ECUConnection(QObject):
    """The transport-agnostic contract between the tuner and an ECU.

    Every implementation answers the same questions: who are you, what is
    your table layout, what is in your RAM, take this cell, commit. A
    serial or CAN transport answers them over a wire; the simulator
    answers them in process. The UI knows only this class.
    """
    channels_updated = Signal(dict)     # {channel_key: value}
    state_changed = Signal(bool)        # connected?
    write_acked = Signal(str, int, int, float)   # key, j, i, value echoed back
    burn_done = Signal(dict)            # {table_key: crc} committed image
    error = Signal(str)                 # anything the tuner should see

    name = "None"
    writable = False                    # can this transport accept a tune?

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

    # -- the table protocol ---------------------------------------------
    # All of these raise ProtocolError rather than returning a status, so a
    # caller that forgets to check cannot carry on against a dead link.

    def identify(self) -> dict:
        """{ecu_id, firmware, protocol_version, layout_hash}."""
        raise ProtocolError(f"{self.name} cannot identify itself")

    def describe_tables(self) -> dict:
        """{key: {n_x, n_y, lo, hi, unit}} — the layout the ECU is built
        for. The tuner refuses to send anything that does not fit it."""
        raise ProtocolError(f"{self.name} has no table layout")

    def read_table(self, key: str):
        raise ProtocolError(f"{self.name} cannot be read")

    def write_cell(self, key: str, j: int, i: int, value: float):
        raise ProtocolError(f"{self.name} cannot be written")

    def write_table(self, key: str, values, x=None, y=None):
        raise ProtocolError(f"{self.name} cannot be written")

    def burn(self) -> dict:
        """Commit RAM to flash and return {table_key: crc} of what was
        actually committed, for the tuner to compare against its own."""
        raise ProtocolError(f"{self.name} has nothing to burn")

    def _require_connected(self):
        if not self._connected:
            raise ProtocolError(f"{self.name} is not connected")


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
