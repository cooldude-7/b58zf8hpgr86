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
# Tables the engine cannot run without and which no version has ever
# been without. A tune missing one of these is corrupt, not old, and is
# refused rather than quietly patched: defaulting someone's knock table
# is not a kindness.
CORE_TABLES = ("ve", "mbt", "knock", "lambda", "base_torque", "boost")

# Tables added after the first release. A tune written before they
# existed is merely old, so these are filled from the defaults and the
# user is told which.
ADDED_TABLES = ("rail_target", "soi", "inj_split")

REQUIRED_TABLES = CORE_TABLES + ADDED_TABLES

# Physical bounds per table. Outside these a value is not a calibration
# choice, it is a typo.
LIMITS = {
    "ve":          (0.05, 2.00),
    "mbt":         (-20.0, 60.0),
    "knock":       (-20.0, 60.0),
    "lambda":      (0.50, 1.60),
    "base_torque": (-200.0, 1200.0),
    "boost":       (0.0, 45.0),
    # direct injection. Rail pressure in kPa absolute: a B48 runs up to
    # about 200 bar, and the injector flow scales with the square root of
    # what is left after cylinder pressure is subtracted.
    "rail_target": (3000.0, 25000.0),
    "soi":         (60.0, 480.0),      # degrees BTDC of firing TDC
    "inj_split":   (0.0, 0.6),         # fraction of the charge in the pilot
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
    # trigger wheel and cam. These decide where every spark lands, so
    # they are engine constants, not preferences.
    "trigger_teeth": (4, 120), "trigger_missing": (0, 4),
    "trigger_gap_to_tdc_deg": (0.0, 360.0),
    "cam_edge_angle_deg": (0.0, 720.0), "cam_tolerance_deg": (1.0, 90.0),
    "dwell_ms": (0.5, 8.0), "soi_btdc_deg": (0.0, 720.0),
    # direct injector drive. A DI injector is opened by a current spike
    # from a boosted supply, not by switching battery voltage at it.
    "inj_boost_v": (30.0, 120.0), "inj_peak_ma": (2000.0, 25000.0),
    "inj_peak_us": (50.0, 2000.0), "inj_hold_ma": (500.0, 8000.0),
    "inj_recharge_us": (0.0, 3000.0), "split_gap_deg": (10.0, 180.0),
    # high pressure pump
    "hpfp_lobes": (1.0, 6.0), "hpfp_lobe_span_deg": (30.0, 240.0),
    "hpfp_first_lobe_deg": (0.0, 720.0), "msv_hold_us": (200.0, 5000.0),
    "hpfp_capacity_g_s": (1.0, 60.0), "rail_volume_cc": (1.0, 200.0),
    "inj_window_deg": (60.0, 480.0),
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
    # Engine scalars that were absent from the file and filled from the
    # defaults on load. Reported to the user rather than applied quietly,
    # because some of them are safety limits.
    upgraded: list = field(default_factory=list)

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
        # A tune written by an older version will not have scalars that
        # were added since. Refusing it outright makes every saved tune
        # disposable on upgrade, so the missing ones are filled from the
        # defaults and named, and the file is still checked afterwards.
        engine = dict(d["engine"])
        defaults = default_engine()
        upgraded = []
        for name in list(ENGINE_LIMITS) + ["chen_flynn"]:
            if name not in engine and name in defaults:
                engine[name] = defaults[name]
                upgraded.append(name)
        core_missing = [k for k in CORE_TABLES if k not in tables]
        if core_missing:
            raise TuneError("tune is missing required tables: "
                            + ", ".join(core_missing))
        missing_tables = [k for k in ADDED_TABLES if k not in tables]
        if missing_tables:
            stock = default_tune()
            for k in missing_tables:
                tables[k] = Table.from_dict(stock.tables[k].to_dict())
                upgraded.append(f"table {k}")
        t = cls(name=str(d["name"]), engine=engine, tables=tables, path=path,
                upgraded=upgraded)
        t.validate()
        if upgraded:
            # the file on disk does not have these yet
            t.engine_unsaved = True
        return t


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

    # Direct injection tables. Rail pressure rises with load because the
    # injector has less time and more cylinder pressure to fight; start
    # of injection moves earlier with speed for the same reason.
    rail = np.clip(5000.0 + 45.0 * (M - 30.0) + 0.7 * R, 4000.0, 20000.0)
    soi = np.clip(300.0 + 0.004 * R - 0.05 * (M - 100.0), 240.0, 340.0)
    # a pilot pulse only where mixing time is short: high load, high speed
    split = np.where((M > 140.0) & (R > 3000.0), 0.30, 0.0)

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
        "rail_target": Table("rail_target", "Rail Pressure Target", "RPM", "rpm",
                             "MAP", "kPa", RPM_AXIS, MAP_AXIS, rail,
                             unit="kPa", fmt="{:.0f}", step=100.0,
                             lo=LIMITS["rail_target"][0], hi=LIMITS["rail_target"][1]),
        "soi": Table("soi", "Injection Timing", "RPM", "rpm", "MAP", "kPa",
                     RPM_AXIS, MAP_AXIS, soi, unit="° BTDC", fmt="{:.0f}",
                     step=5.0, lo=LIMITS["soi"][0], hi=LIMITS["soi"][1]),
        "inj_split": Table("inj_split", "Pilot Fraction", "RPM", "rpm",
                           "MAP", "kPa", RPM_AXIS, MAP_AXIS, split,
                           unit="", fmt="{:.2f}", step=0.05,
                           lo=LIMITS["inj_split"][0], hi=LIMITS["inj_split"][1]),
    }
    engine = default_engine(eng)
    return Tune(name="B48 base", engine=engine, tables=tables).validate()


def default_engine(eng=None) -> dict:
    eng = eng or Engine()
    return {
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
        # PROVISIONAL: 60-2 is the usual BMW wheel, but the gap position
        # and both cam patterns must come from a scope capture on the
        # real engine before this drives anything. See docs/hardware.md.
        "trigger_teeth": 60, "trigger_missing": 2,
        "trigger_gap_to_tdc_deg": 114.0,
        "cam_edge_angle_deg": 90.0, "cam_tolerance_deg": 25.0,
        "dwell_ms": 2.5, "soi_btdc_deg": 300.0,
        # direct injection, PROVISIONAL like the trigger numbers
        "inj_boost_v": 65.0, "inj_peak_ma": 12000.0, "inj_peak_us": 400.0,
        "inj_hold_ma": 3500.0, "inj_recharge_us": 300.0,
        "split_gap_deg": 60.0,
        "hpfp_lobes": 3.0, "hpfp_lobe_span_deg": 120.0,
        "hpfp_first_lobe_deg": 0.0, "msv_hold_us": 1500.0,
        "hpfp_capacity_g_s": 22.0, "rail_volume_cc": 22.0,
        "inj_window_deg": 240.0,
    }
