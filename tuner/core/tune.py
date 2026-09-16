"""The tune: every table and scalar the ECU runs on, plus load/save.

JSON on disk, on purpose -- it is readable and diffs in git, so a tune has a
history. The binary layout the ECU wants is produced from this on burn and
is the ECU's problem, not the tuner's.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from tqmodel.model import Engine, base_torque
from tqmodel.synth import truth_ve, truth_mbt
from .table import Table

SCHEMA_VERSION = 1


@dataclass
class Tune:
    name: str = "Untitled"
    engine: dict = field(default_factory=dict)
    tables: dict = field(default_factory=dict)
    path: Path | None = None
    engine_dirty: bool = False

    # -- state ----------------------------------------------------------
    @property
    def dirty(self) -> bool:
        return self.engine_dirty or any(t.dirty.any() for t in self.tables.values())

    def clear_dirty(self):
        self.engine_dirty = False
        for t in self.tables.values():
            t.clear_dirty()

    # -- persistence ----------------------------------------------------
    def to_json(self) -> str:
        return json.dumps({
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "engine": self.engine,
            "tables": {k: t.to_dict() for k, t in self.tables.items()},
        }, indent=1)

    def save(self, path: Path | str):
        path = Path(path)
        path.write_text(self.to_json())
        self.path = path
        self.clear_dirty()

    @classmethod
    def load(cls, path: Path | str) -> "Tune":
        path = Path(path)
        d = json.loads(path.read_text())
        if d.get("schema") != SCHEMA_VERSION:
            raise ValueError(f"unsupported tune schema {d.get('schema')}")
        t = cls(name=d["name"], engine=d["engine"],
                tables={k: Table.from_dict(v) for k, v in d["tables"].items()},
                path=path)
        return t


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

    tables = {
        "ve": Table("ve", "VE Table", "RPM", "rpm", "MAP", "kPa",
                    RPM_AXIS, MAP_AXIS, ve, unit="", fmt="{:.3f}", step=0.005),
        "mbt": Table("mbt", "MBT Spark", "RPM", "rpm", "MAP", "kPa",
                     RPM_AXIS, MAP_AXIS, mbt, unit="° BTDC", fmt="{:.1f}", step=0.5),
        "knock": Table("knock", "Knock Limit", "RPM", "rpm", "MAP", "kPa",
                       RPM_AXIS, MAP_AXIS, knock, unit="° BTDC", fmt="{:.1f}", step=0.5),
        "lambda": Table("lambda", "Lambda Target", "RPM", "rpm", "MAP", "kPa",
                        RPM_AXIS, MAP_AXIS, lam, unit="λ", fmt="{:.3f}", step=0.005),
        "base_torque": Table("base_torque", "Base Torque", "RPM", "rpm",
                             "Air mass", "g/cyl", RPM_AXIS, AIR_AXIS, bt,
                             unit="Nm", fmt="{:.0f}", step=1.0),
    }
    engine = {
        "n_cyl": eng.n_cyl, "displacement_l": eng.displacement_l,
        "compression_ratio": eng.compression_ratio,
        "afr_stoich": eng.afr_stoich, "stroke_m": eng.stroke_m,
        "injector_flow_cc_min": 1050.0, "injector_deadtime_ms": 0.90,
        "fuel_pressure_kpa": 350.0, "rev_limit": 7200,
        "chen_flynn": [eng.cf_a, eng.cf_b, eng.cf_c, eng.cf_d],
    }
    return Tune(name="B48 base", engine=engine, tables=tables)
