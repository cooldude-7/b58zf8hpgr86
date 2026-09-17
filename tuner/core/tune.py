"""The tune: every table and scalar the ECU runs on, plus load/save.

JSON on disk, on purpose -- it is readable and diffs in git, so a tune has a
history. The binary layout the ECU wants is produced from this on burn and
is the ECU's problem, not the tuner's.
"""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from tqmodel.model import Engine, base_torque
from tqmodel.synth import truth_ve, truth_mbt
from .table import Table, TableError

SCHEMA_VERSION = 1

# Tables the ECU cannot run without. A tune missing any of these is refused
# at load rather than crashing the control loop a hundred times a second.
REQUIRED_TABLES = ("ve", "mbt", "knock", "lambda", "base_torque", "boost")

# Physical bounds per table. Outside these a value is not a calibration
# choice, it is a typo.
LIMITS = {
    "ve":          (0.05, 2.00),
    "mbt":         (-20.0, 60.0),
    "knock":       (-20.0, 60.0),
    "lambda":      (0.50, 1.60),
    "base_torque": (-200.0, 1200.0),
    "boost":       (0.0, 45.0),
}

# Engine scalars: (lo, hi) for each, all required.
ENGINE_LIMITS = {
    "n_cyl": (1, 16), "displacement_l": (0.1, 10.0),
    "compression_ratio": (5.0, 20.0), "afr_stoich": (5.0, 20.0),
    "stroke_m": (0.02, 0.20), "injector_flow_cc_min": (50.0, 5000.0),
    "injector_deadtime_ms": (0.0, 5.0), "fuel_pressure_kpa": (100.0, 30000.0),
    "rev_limit": (1000.0, 15000.0), "final_drive": (1.0, 8.0),
    "tire_radius_m": (0.15, 0.60), "vehicle_mass_kg": (200.0, 5000.0),
    "boost_max_kpa": (100.0, 400.0), "overboost_cut_kpa": (100.0, 450.0),
    "max_cut_retard": (5.0, 60.0),
}


class TuneError(ValueError):
    """A tune file cannot be trusted to run an engine."""


@dataclass
class Tune:
    name: str = "Untitled"
    engine: dict = field(default_factory=dict)
    tables: dict = field(default_factory=dict)
    path: Path | None = None
    engine_unsaved: bool = False
    engine_unburned: bool = False

    # -- state ----------------------------------------------------------
    # Two independent questions, and conflating them loses work: "does this
    # differ from the file on disk" (file_dirty, cleared only by save) and
    # "does this differ from what the ECU confirmed" (ecu_dirty, cleared
    # only by a burn or a verified read).
    @property
    def file_dirty(self) -> bool:
        return self.engine_unsaved or any(t.unsaved.any() for t in self.tables.values())

    @property
    def ecu_dirty(self) -> bool:
        return self.engine_unburned or any(t.dirty.any() for t in self.tables.values())

    def touch_engine(self):
        self.engine_unsaved = True
        self.engine_unburned = True

    def mark_saved(self):
        self.engine_unsaved = False
        for t in self.tables.values():
            t.mark_saved()

    def mark_burned(self):
        self.engine_unburned = False
        for t in self.tables.values():
            t.mark_burned()

    def copy(self) -> "Tune":
        """An independent image. The ECU holds one of these, the editor
        another; they meet only through the connection."""
        return Tune(name=self.name, engine=dict(self.engine),
                    tables={k: Table.from_dict(t.to_dict())
                            for k, t in self.tables.items()},
                    path=self.path)

    def crcs(self) -> dict:
        return {k: t.crc() for k, t in self.tables.items()}

    # -- validation -----------------------------------------------------
    def validate(self):
        """Everything that must be true before this tune drives anything.
        Raises TuneError with the first real problem."""
        missing = [k for k in REQUIRED_TABLES if k not in self.tables]
        if missing:
            raise TuneError("tune is missing required tables: " + ", ".join(missing))
        for key, t in self.tables.items():
            if t.key != key:
                raise TuneError(f"table stored under {key!r} calls itself {t.key!r}")
            try:
                t.check_bounds(t.values)
            except TableError as e:
                raise TuneError(str(e)) from None
        for name, (lo, hi) in ENGINE_LIMITS.items():
            if name not in self.engine:
                raise TuneError(f"engine scalar {name!r} is missing")
            v = self.engine[name]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                raise TuneError(f"engine scalar {name!r} is not a finite number")
            if not lo <= v <= hi:
                raise TuneError(f"engine scalar {name!r} = {v:g} outside {lo:g}..{hi:g}")
        cf = self.engine.get("chen_flynn")
        if not isinstance(cf, (list, tuple)) or len(cf) != 4 \
                or not all(isinstance(c, (int, float)) and math.isfinite(c) for c in cf):
            raise TuneError("engine scalar 'chen_flynn' must be four finite numbers")
        return self

    # -- persistence ----------------------------------------------------
    def to_json(self) -> str:
        return json.dumps({
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "engine": self.engine,
            "tables": {k: t.to_dict() for k, t in self.tables.items()},
        }, indent=1, allow_nan=False)

    def save(self, path: Path | str):
        self.validate()
        path = Path(path)
        path.write_text(self.to_json())
        self.path = path
        self.mark_saved()

    @classmethod
    def load(cls, path: Path | str) -> "Tune":
        path = Path(path)
        d = json.loads(path.read_text(), parse_constant=_no_constants)
        if d.get("schema") != SCHEMA_VERSION:
            raise TuneError(f"unsupported tune schema {d.get('schema')}")
        for field_name in ("name", "engine", "tables"):
            if field_name not in d:
                raise TuneError(f"tune file has no {field_name!r}")
        if not isinstance(d["tables"], dict) or not isinstance(d["engine"], dict):
            raise TuneError("tune file is malformed")
        tables = {}
        for k, v in d["tables"].items():
            lo, hi = LIMITS.get(k, (-1e9, 1e9))
            v = dict(v)
            v.setdefault("lo", lo)
            v.setdefault("hi", hi)
            try:
                tables[k] = Table.from_dict(v)
            except TableError as e:
                raise TuneError(str(e)) from None
        t = cls(name=str(d["name"]), engine=d["engine"], tables=tables, path=path)
        return t.validate()


def _no_constants(token):
    raise TuneError(f"tune file contains {token}, which is not a calibration value")


# ---------------------------------------------------------------------------
# Default tune, built from the model's synthetic engine so the app has real
# shaped data to show before any dyno exists.
# ---------------------------------------------------------------------------
RPM_AXIS = np.array([800, 1200, 1600, 2000, 2500, 3000, 3500, 4000, 4500,
                     5000, 5500, 6000, 6500, 7000, 7500], dtype=float)
MAP_AXIS = np.array([30, 45, 60, 75, 90, 100, 120, 140, 160, 180, 200, 220,
                     240], dtype=float)


def default_tune() -> Tune:
    eng = Engine()
    R, M = np.meshgrid(RPM_AXIS, MAP_AXIS)          # shape (n_map, n_rpm)

    ve = truth_ve(R, M)
    mbt = truth_mbt(R, M)
    knock = np.clip(24.0 - 0.28 * np.clip(M - 95.0, 0, None) + 0.0020 * R, 2.0, None)
    lam = np.where(M <= 100, 1.00, np.where(M >= 150, 0.86,
                   1.00 - 0.14 * (M - 100) / 50.0))

    # base torque is indexed by air mass, not MAP
    AIR_AXIS = np.linspace(0.15, 1.30, 12)
    A, R2 = np.meshgrid(AIR_AXIS, RPM_AXIS)          # (n_rpm, n_air)
    bt = base_torque(A, R2, eng).T                   # -> (n_air, n_rpm)

    # boost target by rpm and throttle, in psi gauge: nothing until the turbo
    # has exhaust energy, a plateau in the mid range, tapering up top
    TPS_AXIS = np.array([0.0, 40.0, 70.0, 100.0])
    rpm_curve = np.interp(RPM_AXIS, [800, 2000, 3000, 4500, 6000, 7500], [0, 2, 14, 16, 15, 12])
    boost = np.vstack([rpm_curve * f for f in (0.0, 0.15, 0.6, 1.0)])

    tables = {
        "boost": Table("boost", "Boost Target", "RPM", "rpm", "Throttle", "%",
                       RPM_AXIS, TPS_AXIS, boost, unit="psi", fmt="{:.1f}", step=0.5, lo=LIMITS["boost"][0], hi=LIMITS["boost"][1]),
        "ve": Table("ve", "VE Table", "RPM", "rpm", "MAP", "kPa",
                    RPM_AXIS, MAP_AXIS, ve, unit="", fmt="{:.3f}", step=0.005, lo=LIMITS["ve"][0], hi=LIMITS["ve"][1]),
        "mbt": Table("mbt", "MBT Spark", "RPM", "rpm", "MAP", "kPa",
                     RPM_AXIS, MAP_AXIS, mbt, unit="° BTDC", fmt="{:.1f}", step=0.5, lo=LIMITS["mbt"][0], hi=LIMITS["mbt"][1]),
        "knock": Table("knock", "Knock Limit", "RPM", "rpm", "MAP", "kPa",
                       RPM_AXIS, MAP_AXIS, knock, unit="° BTDC", fmt="{:.1f}", step=0.5, lo=LIMITS["knock"][0], hi=LIMITS["knock"][1]),
        "lambda": Table("lambda", "Lambda Target", "RPM", "rpm", "MAP", "kPa",
                        RPM_AXIS, MAP_AXIS, lam, unit="λ", fmt="{:.3f}", step=0.005, lo=LIMITS["lambda"][0], hi=LIMITS["lambda"][1]),
        "base_torque": Table("base_torque", "Base Torque", "RPM", "rpm",
                             "Air mass", "g/cyl", RPM_AXIS, AIR_AXIS, bt,
                             unit="Nm", fmt="{:.0f}", step=1.0, lo=LIMITS["base_torque"][0], hi=LIMITS["base_torque"][1]),
    }
    engine = {
        "n_cyl": eng.n_cyl, "displacement_l": eng.displacement_l,
        "compression_ratio": eng.compression_ratio,
        "afr_stoich": eng.afr_stoich, "stroke_m": eng.stroke_m,
        "injector_flow_cc_min": 1050.0, "injector_deadtime_ms": 0.90,
        "fuel_pressure_kpa": 350.0, "rev_limit": 7200,
        "chen_flynn": [eng.cf_a, eng.cf_b, eng.cf_c, eng.cf_d],
        # driveline, for the simulator: GR86 mass, a taller final drive to
        # suit the 8HP's spread, 215/45R17
        "final_drive": 3.46, "tire_radius_m": 0.318, "vehicle_mass_kg": 1400.0,
        # safety limits
        "boost_max_kpa": 240.0, "overboost_cut_kpa": 265.0,
        "max_cut_retard": 35.0,
    }
    return Tune(name="B48 base", engine=engine, tables=tables).validate()
