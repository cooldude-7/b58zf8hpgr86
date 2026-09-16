"""Heat-map colour scale shared by the 2D grid and the 3D surface."""
import numpy as np
from PySide6.QtGui import QColor

# Excel's classic three-colour scale. Green low, yellow mid, red high.
_LO, _MID, _HI = QColor("#63BE7B"), QColor("#FFEB84"), QColor("#F8696B")


def heat(t: float) -> QColor:
    t = 0.0 if np.isnan(t) else min(max(float(t), 0.0), 1.0)
    a, b, f = (_LO, _MID, t * 2) if t < 0.5 else (_MID, _HI, (t - 0.5) * 2)
    return QColor(int(a.red() + (b.red() - a.red()) * f),
                  int(a.green() + (b.green() - a.green()) * f),
                  int(a.blue() + (b.blue() - a.blue()) * f))
