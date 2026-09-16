"""Table operations as pure numpy, so they are testable without Qt.

Every function mutates `values` in place. `mask` is a boolean array the
same shape as `values` marking the selected cells; the rectangle
(j0, j1, i0, i1) is the inclusive bounding box of the selection.
"""
import numpy as np


def bump(values: np.ndarray, mask: np.ndarray, step: float):
    values[mask] += step


def scale(values: np.ndarray, mask: np.ndarray, factor: float):
    values[mask] *= factor


def set_value(values: np.ndarray, mask: np.ndarray, v: float):
    values[mask] = v


def interpolate(values: np.ndarray, j0: int, j1: int, i0: int, i1: int):
    """Fill the rectangle bilinearly from its four corner cells.

    A single row or column degrades to linear; a single cell is a no-op.
    This is the operation a tuner reaches for after setting a few anchor
    cells and wanting everything in between to follow.
    """
    if j0 == j1 and i0 == i1:
        return
    for j in range(j0, j1 + 1):
        fy = 0.0 if j1 == j0 else (j - j0) / (j1 - j0)
        for i in range(i0, i1 + 1):
            fx = 0.0 if i1 == i0 else (i - i0) / (i1 - i0)
            top = values[j0, i0] * (1 - fx) + values[j0, i1] * fx
            bot = values[j1, i0] * (1 - fx) + values[j1, i1] * fx
            values[j, i] = top * (1 - fy) + bot * fy


def smooth(values: np.ndarray, mask: np.ndarray):
    """Replace each selected cell with the mean of its 3x3 neighbourhood,
    computed from a snapshot so the result does not depend on order.
    Edges are padded with their own values so borders are not dragged down."""
    src = np.pad(values.copy(), 1, mode="edge")
    ny, nx = values.shape
    acc = np.zeros_like(values)
    for dj in range(3):
        for di in range(3):
            acc += src[dj:dj + ny, di:di + nx]
    values[mask] = (acc / 9.0)[mask]


def to_tsv(values: np.ndarray, j0: int, j1: int, i0: int, i1: int, fmt: str) -> str:
    """Rows in DISPLAY order (highest load first), tab-separated. Pastes
    straight into a spreadsheet looking like the screen."""
    lines = []
    for j in range(j1, j0 - 1, -1):
        lines.append("\t".join(fmt.format(values[j, i]) for i in range(i0, i1 + 1)))
    return "\n".join(lines)


def from_tsv(text: str) -> np.ndarray | None:
    """Parse tab/comma/space separated numbers; rows as given. None if the
    block is empty or ragged."""
    rows = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p for p in line.replace(",", "\t").replace(" ", "\t").split("\t") if p]
        try:
            rows.append([float(p) for p in parts])
        except ValueError:
            return None
    if not rows or any(len(r) != len(rows[0]) for r in rows):
        return None
    return np.asarray(rows, dtype=float)


def regrid(values: np.ndarray, x: np.ndarray, y: np.ndarray,
           new_x: np.ndarray, new_y: np.ndarray, lookup) -> np.ndarray:
    """Values on a new set of breakpoints, sampled from the old surface so
    the shape is preserved when a tuner moves an axis."""
    out = np.empty((len(new_y), len(new_x)))
    for j, yv in enumerate(new_y):
        for i, xv in enumerate(new_x):
            out[j, i] = lookup(xv, yv)
    return out
