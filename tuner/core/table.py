"""A calibration table: two axes and a grid of values.

Storage convention: values[j, i] is the cell at y[j], x[i], with both axes
stored ASCENDING. Display (load increasing upward) is the view's problem,
not the table's.
"""
from dataclasses import dataclass, field

import numpy as np


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
    dirty: np.ndarray = field(default=None)

    def __post_init__(self):
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)
        self.values = np.asarray(self.values, dtype=float)
        assert self.values.shape == (len(self.y), len(self.x)), \
            f"{self.key}: values {self.values.shape} vs axes ({len(self.y)}, {len(self.x)})"
        if self.dirty is None:
            self.dirty = np.zeros_like(self.values, dtype=bool)

    @property
    def n_x(self) -> int:
        return len(self.x)

    @property
    def n_y(self) -> int:
        return len(self.y)

    def set(self, j: int, i: int, value: float):
        if self.values[j, i] != value:
            self.values[j, i] = value
            self.dirty[j, i] = True

    def clear_dirty(self):
        self.dirty[:] = False

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

    def to_dict(self) -> dict:
        return {
            "key": self.key, "title": self.title,
            "x_name": self.x_name, "x_unit": self.x_unit,
            "y_name": self.y_name, "y_unit": self.y_unit,
            "unit": self.unit, "fmt": self.fmt, "step": self.step,
            "x": self.x.tolist(), "y": self.y.tolist(),
            "values": self.values.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Table":
        return cls(**{k: d[k] for k in ("key", "title", "x_name", "x_unit",
                                        "y_name", "y_unit", "unit", "fmt",
                                        "step", "x", "y", "values")})


def _locate(axis: np.ndarray, v: float):
    """Index of the lower breakpoint and the fraction toward the next."""
    n = len(axis)
    if v <= axis[0]:
        return 0, 0.0
    if v >= axis[-1]:
        return n - 2, 1.0
    i = int(np.searchsorted(axis, v, side="right") - 1)
    i = min(max(i, 0), n - 2)
    span = axis[i + 1] - axis[i]
    return i, float((v - axis[i]) / span) if span > 0 else 0.0
