"""A calibration table: two axes and a grid of values.

Storage convention: values[j, i] is the cell at y[j], x[i], with both axes
stored ASCENDING. Display (load increasing upward) is the view's problem,
not the table's.

Two baselines travel with the table: `burned` is the last image the ECU
confirmed, `saved` is the last image written to disk. The dirty masks are
computed from those, never tracked by hand, so undo cannot leave a stale
mask behind and a burn cannot clear the unsaved state.
"""
from dataclasses import dataclass, field

import numpy as np


class TableError(ValueError):
    """A table was given values or axes it cannot represent."""


def check_finite(a, what: str):
    a = np.asarray(a, dtype=float)
    if not np.isfinite(a).all():
        raise TableError(f"{what}: NaN or infinity is not a calibration value")
    return a


def check_axis(a, what: str):
    a = check_finite(a, what)
    if a.ndim != 1 or len(a) < 2:
        raise TableError(f"{what}: an axis needs at least two breakpoints")
    if not np.all(np.diff(a) > 0):
        raise TableError(f"{what}: breakpoints must strictly increase")
    return a


@dataclass
class Table:
    key: str
    title: str
    x_name: str
    x_unit: str
    y_name: str
    y_unit: str
    x: np.ndarray
    y: np.ndarray
    values: np.ndarray
    unit: str = ""
    fmt: str = "{:.2f}"
    step: float = 0.01          # bump step for + / -
    lo: float = -1e9            # physical bounds; values outside are refused
    hi: float = 1e9
    burned: np.ndarray = field(default=None, repr=False)   # in ECU flash
    saved: np.ndarray = field(default=None, repr=False)    # on disk
    sent: np.ndarray = field(default=None, repr=False)     # echoed by ECU RAM

    def __post_init__(self):
        self.x = check_axis(self.x, f"{self.key}.x")
        self.y = check_axis(self.y, f"{self.key}.y")
        self.values = check_finite(self.values, f"{self.key}.values")
        if self.values.shape != (len(self.y), len(self.x)):
            raise TableError(f"{self.key}: values {self.values.shape} vs "
                             f"axes ({len(self.y)}, {len(self.x)})")
        if self.hi <= self.lo:
            raise TableError(f"{self.key}: empty bound range")
        self.check_bounds(self.values)
        if self.burned is None:
            self.burned = self.values.copy()
        if self.saved is None:
            self.saved = self.values.copy()
        if self.sent is None:
            self.sent = self.values.copy()

    # -- validation -----------------------------------------------------
    def check_bounds(self, a):
        a = np.asarray(a, dtype=float)
        if not np.isfinite(a).all():
            raise TableError(f"{self.key}: NaN or infinity is not a calibration value")
        if a.size and (a.min() < self.lo or a.max() > self.hi):
            raise TableError(f"{self.key}: value outside {self.lo:g}..{self.hi:g} "
                             f"{self.unit}".rstrip())
        return a

    def clip(self, a):
        """Bring an array inside the bounds. Used by the bulk operations,
        where clamping is friendlier than refusing the whole selection."""
        return np.clip(np.asarray(a, dtype=float), self.lo, self.hi)

    def accepts(self, value: float) -> bool:
        return bool(np.isfinite(value)) and self.lo <= value <= self.hi

    # -- shape ----------------------------------------------------------
    @property
    def n_x(self) -> int:
        return len(self.x)

    @property
    def n_y(self) -> int:
        return len(self.y)

    # -- state ----------------------------------------------------------
    @property
    def dirty(self) -> np.ndarray:
        """Cells that differ from what the ECU last confirmed."""
        return _differs(self.values, self.burned)

    @property
    def unsaved(self) -> np.ndarray:
        """Cells that differ from what is on disk."""
        return _differs(self.values, self.saved)

    # A cell is in one of three states, and a tuner must be able to see
    # which: LOCAL means typed but not in the ECU, RAM means the ECU echoed
    # it back but it is lost on key-off, FLASH means committed.
    LOCAL, RAM, FLASH = 0, 1, 2

    def state(self) -> np.ndarray:
        st = np.full(self.values.shape, self.FLASH, dtype=np.int8)
        st[_differs(self.values, self.burned)] = self.RAM
        st[_differs(self.values, self.sent)] = self.LOCAL
        return st

    def mark_sent(self):
        self.sent = self.values.copy()

    def mark_burned(self):
        self.burned = self.values.copy()
        self.sent = self.values.copy()

    def mark_saved(self):
        self.saved = self.values.copy()

    def invalidate_baselines(self):
        """After an axis change the old grid means nothing: every cell is
        both unburned and unsaved."""
        nan = np.full(self.values.shape, np.nan)
        self.burned, self.saved, self.sent = nan, nan.copy(), nan.copy()

    def set(self, j: int, i: int, value: float):
        value = float(value)
        if not self.accepts(value):
            raise TableError(f"{self.key}: {value:g} is outside "
                             f"{self.lo:g}..{self.hi:g}")
        self.values[j, i] = value

    # -- lookup ---------------------------------------------------------
    def lookup(self, xv: float, yv: float) -> float:
        """Bilinear interpolation, clamped to the axis range."""
        i, fx = _locate(self.x, xv)
        j, fy = _locate(self.y, yv)
        v = self.values
        return float((v[j, i] * (1 - fx) + v[j, i + 1] * fx) * (1 - fy)
                     + (v[j + 1, i] * (1 - fx) + v[j + 1, i + 1] * fx) * fy)

    def cell_of(self, xv: float, yv: float):
        """(j, i, fy, fx): the lower-left cell of the interpolation square
        and the fractional position inside it. Used for the live cursor."""
        i, fx = _locate(self.x, xv)
        j, fy = _locate(self.y, yv)
        return j, i, fy, fx

    # -- persistence ----------------------------------------------------
    def crc(self) -> int:
        """CRC over the exact bytes a burn would send: axes then values,
        little-endian float64. The ECU computes the same number over what
        it committed, and the two are compared."""
        import zlib
        b = (np.ascontiguousarray(self.x, dtype="<f8").tobytes()
             + np.ascontiguousarray(self.y, dtype="<f8").tobytes()
             + np.ascontiguousarray(self.values, dtype="<f8").tobytes())
        return zlib.crc32(self.key.encode() + b) & 0xFFFFFFFF

    def to_dict(self) -> dict:
        return {
            "key": self.key, "title": self.title,
            "x_name": self.x_name, "x_unit": self.x_unit,
            "y_name": self.y_name, "y_unit": self.y_unit,
            "unit": self.unit, "fmt": self.fmt, "step": self.step,
            "lo": self.lo, "hi": self.hi,
            "x": self.x.tolist(), "y": self.y.tolist(),
            "values": self.values.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Table":
        need = ("key", "title", "x_name", "x_unit", "y_name", "y_unit",
                "unit", "fmt", "step", "x", "y", "values")
        missing = [k for k in need if k not in d]
        if missing:
            raise TableError(f"table {d.get('key', '?')}: missing "
                             + ", ".join(missing))
        kw = {k: d[k] for k in need}
        for opt in ("lo", "hi"):
            if opt in d:
                kw[opt] = float(d[opt])
        return cls(**kw)


def _differs(a: np.ndarray, base: np.ndarray) -> np.ndarray:
    if base is None or base.shape != a.shape:
        return np.ones_like(a, dtype=bool)
    with np.errstate(invalid="ignore"):
        return ~np.isclose(a, base, rtol=0.0, atol=0.0, equal_nan=True)


def _locate(axis: np.ndarray, v: float):
    """Index of the lower breakpoint and the fraction toward the next."""
    if not np.isfinite(v):
        return 0, 0.0
    n = len(axis)
    if v <= axis[0]:
        return 0, 0.0
    if v >= axis[-1]:
        return n - 2, 1.0
    i = int(np.searchsorted(axis, v, side="right") - 1)
    i = min(max(i, 0), n - 2)
    span = axis[i + 1] - axis[i]
    return i, float((v - axis[i]) / span) if span > 0 else 0.0
