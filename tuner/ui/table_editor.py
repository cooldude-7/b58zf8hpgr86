"""The table editor: heat-map grid with axis headers and a live cursor."""
import numpy as np
from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QPoint, Qt,
                            Signal)
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPolygon
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QStyledItemDelegate,
                               QTableView, QVBoxLayout, QWidget)

from tqmodel.units import kpa_abs_to_boost_psi
from ..core.table import Table

# Excel's classic three-colour scale. Green low, yellow mid, red high.
_LO, _MID, _HI = QColor("#63BE7B"), QColor("#FFEB84"), QColor("#F8696B")


def heat(t: float) -> QColor:
    t = 0.0 if np.isnan(t) else min(max(t, 0.0), 1.0)
    a, b, f = (_LO, _MID, t * 2) if t < 0.5 else (_MID, _HI, (t - 0.5) * 2)
    return QColor(int(a.red() + (b.red() - a.red()) * f),
                  int(a.green() + (b.green() - a.green()) * f),
                  int(a.blue() + (b.blue() - a.blue()) * f))


class TableModel(QAbstractTableModel):
    """Presents a Table with load increasing UPWARD: row 0 is the top y."""

    def __init__(self, table: Table, boost_psi: bool = True):
        super().__init__()
        self.table = table
        self.boost_psi = boost_psi
        self._rescale()

    # row <-> y index
    def j_of(self, row: int) -> int:
        return self.table.n_y - 1 - row

    def row_of(self, j: int) -> int:
        return self.table.n_y - 1 - j

    def ji(self, index: QModelIndex):
        return self.j_of(index.row()), index.column()

    def _rescale(self):
        v = self.table.values
        self._vmin, self._vmax = float(np.nanmin(v)), float(np.nanmax(v))
        if self._vmax - self._vmin < 1e-9:
            self._vmax = self._vmin + 1.0

    def rowCount(self, parent=QModelIndex()):
        return self.table.n_y

    def columnCount(self, parent=QModelIndex()):
        return self.table.n_x

    def flags(self, index):
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable

    def data(self, index, role=Qt.DisplayRole):
        j, i = self.ji(index)
        v = self.table.values[j, i]
        if role == Qt.DisplayRole:
            return self.table.fmt.format(v)
        if role == Qt.EditRole:
            return float(v)
        if role == Qt.BackgroundRole:
            return QBrush(heat((v - self._vmin) / (self._vmax - self._vmin)))
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter)
        if role == Qt.FontRole and self.table.dirty[j, i]:
            f = QFont(); f.setBold(True); return f
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole:
            return False
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        j, i = self.ji(index)
        self.table.set(j, i, v)
        self._rescale()
        self.dataChanged.emit(self.index(0, 0),
                              self.index(self.rowCount() - 1, self.columnCount() - 1))
        return True

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter)
        if role != Qt.DisplayRole:
            return None
        t = self.table
        if orientation == Qt.Horizontal:
            x = t.x[section]
            return f"{x:g}"
        y = t.y[self.j_of(section)]
        if t.y_unit == "kPa" and self.boost_psi:
            return f"{kpa_abs_to_boost_psi(y):.1f}"
        return f"{y:g}"

    def y_header_title(self) -> str:
        t = self.table
        if t.y_unit == "kPa" and self.boost_psi:
            return "Boost (psi)"
        return f"{t.y_name} ({t.y_unit})"


class HeatDelegate(QStyledItemDelegate):
    """Default painting, plus the live cursor block and dirty markers."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        model = index.model()
        j, i = model.ji(index)
        r = option.rect

        if model.table.dirty[j, i]:
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#C00000"))
            painter.drawPolygon(QPolygon([QPoint(r.right() - 6, r.top() + 1),
                                          QPoint(r.right(), r.top() + 1),
                                          QPoint(r.right(), r.top() + 7)]))
            painter.restore()

        cur = self.editor.cursor
        if cur is not None:
            cj, ci, fy, fx = cur
            if cj <= j <= cj + 1 and ci <= i <= ci + 1:
                nearest = (j == cj + (1 if fy >= 0.5 else 0)
                           and i == ci + (1 if fx >= 0.5 else 0))
                painter.save()
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor("#1040B0" if nearest else "#4A80D8"),
                                    3 if nearest else 1))
                painter.drawRect(r.adjusted(1, 1, -2, -2))
                painter.restore()


class TableEditor(QWidget):
    changed = Signal()

    def __init__(self, table: Table, boost_psi: bool = True, parent=None):
        super().__init__(parent)
        self.table = table
        self.cursor = None
        self.model = TableModel(table, boost_psi)
        self.model.dataChanged.connect(lambda *_: self.changed.emit())

        head = QHBoxLayout()
        head.setContentsMargins(4, 3, 4, 2)
        self.title = QLabel(f"<b>{table.title}</b>")
        self.info = QLabel(f"{table.x_name} × {self.model.y_header_title()}"
                           f"{'  —  ' + table.unit if table.unit else ''}")
        self.info.setObjectName("dim")
        b2d = QPushButton("2D"); b2d.setCheckable(True); b2d.setChecked(True)
        b3d = QPushButton("3D"); b3d.setCheckable(True); b3d.setEnabled(False)
        b3d.setToolTip("3D surface view — Phase 2")
        for b in (b2d, b3d):
            b.setFixedWidth(34)
        head.addWidget(self.title); head.addSpacing(10); head.addWidget(self.info)
        head.addStretch(); head.addWidget(b2d); head.addWidget(b3d)

        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(HeatDelegate(self))
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.view.setEditTriggers(QAbstractItemView.DoubleClicked
                                  | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.AnyKeyPressed)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.view.horizontalHeader().setDefaultSectionSize(54)
        self.view.verticalHeader().setDefaultSectionSize(20)
        self.view.verticalHeader().setFixedWidth(56)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.verticalHeader().setHighlightSections(False)
        self.view.setCornerButtonEnabled(False)
        self.view.setAlternatingRowColors(False)
        f = QFont(self.font()); f.setPointSize(8)
        self.view.setFont(f)
        self.view.horizontalHeader().setFont(f)
        self.view.verticalHeader().setFont(f)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addLayout(head)
        lay.addWidget(self.view)

    def set_cursor(self, xv: float, yv: float):
        """Called with the live operating point; repaints only the old and
        new cursor blocks rather than the whole grid."""
        new = self.table.cell_of(xv, yv)
        old = self.cursor
        self.cursor = new
        for c in (old, new):
            if c is None:
                continue
            cj, ci, *_ = c
            tl = self.model.index(self.model.row_of(cj + 1), ci)
            br = self.model.index(self.model.row_of(cj), ci + 1)
            self.view.viewport().update(self.view.visualRect(tl).united(
                self.view.visualRect(br)))

    def clear_cursor(self):
        self.cursor = None
        self.view.viewport().update()
