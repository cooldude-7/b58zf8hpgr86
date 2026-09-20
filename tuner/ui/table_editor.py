"""The table editor: heat-map grid, keyboard operations, undo, 2D/3D."""
import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import (QAction, QBrush, QFont, QGuiApplication, QKeySequence,
                           QColor, QPen, QPolygon)
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QMenu, QMessageBox,
                               QPushButton, QStackedWidget, QStyledItemDelegate,
                               QTableView, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from tqmodel.units import kpa_abs_to_boost_psi
from ..core import tableops as ops
from ..core.table import Table
from .colors import heat
from .surface3d import Surface3D


class TableModel(QAbstractTableModel):
    """Presents a Table with load increasing UPWARD: row 0 is the top y."""

    def __init__(self, table: Table, boost_psi: bool = True):
        super().__init__()
        self.table = table
        self.boost_psi = boost_psi
        self.before_change = lambda: None       # editor hooks undo in here
        self._rescale()

    def j_of(self, row: int) -> int:
        return self.table.n_y - 1 - row

    def row_of(self, j: int) -> int:
        return self.table.n_y - 1 - j

    def ji(self, index: QModelIndex):
        return self.j_of(index.row()), index.column()

    def decimals(self) -> int:
        f = self.table.fmt
        return int(f[f.index(".") + 1:f.index("f")]) if "." in f else 0

    def _rescale(self):
        v = self.table.values
        self._vmin, self._vmax = float(np.nanmin(v)), float(np.nanmax(v))
        if self._vmax - self._vmin < 1e-9:
            self._vmax = self._vmin + 1.0

    def refresh(self):
        self._rescale()
        self.dataChanged.emit(self.index(0, 0),
                              self.index(self.rowCount() - 1, self.columnCount() - 1))

    def reset_axes(self):
        self.beginResetModel(); self._rescale(); self.endResetModel()

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
        if role == Qt.ToolTipRole:
            st = self.table.state()[j, i]
            return {Table.LOCAL: "Edited here. Not in the ECU yet: "
                                 "F4 sends it, F5 sends and burns it.",
                    Table.RAM: "In ECU RAM. Lost on key-off until you burn (F5).",
                    Table.FLASH: "Committed to the ECU."}[int(st)]
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole:
            return False
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        j, i = self.ji(index)
        if self.table.values[j, i] == v:
            return True
        if not self.table.accepts(v):
            return False        # out of physical bounds: the cell keeps its value
        self.before_change()
        self.table.set(j, i, v)
        self.refresh()
        return True

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter)
        if role != Qt.DisplayRole:
            return None
        t = self.table
        if orientation == Qt.Horizontal:
            return f"{t.x[section]:g}"
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
    """Default painting plus the live cursor block and dirty markers, and a
    spinbox editor with the table's own precision."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def createEditor(self, parent, option, index):
        e = QDoubleSpinBox(parent)
        e.setDecimals(index.model().decimals())
        e.setRange(-1e6, 1e6)
        e.setButtonSymbols(QDoubleSpinBox.NoButtons)
        e.setFrame(False)
        e.setAlignment(Qt.AlignCenter)
        return e

    def setEditorData(self, editor, index):
        editor.setValue(float(index.data(Qt.EditRole)))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        editor.interpretText()
        model.setData(index, editor.value(), Qt.EditRole)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        model = index.model()
        j, i = model.ji(index)
        r = option.rect

        # Three states, three markers, because "edited" and "in the
        # engine" are different facts and a tuner has to be able to tell
        # them apart at a glance. Red means the ECU has never seen this
        # number; amber means it is in RAM and will be lost on key-off.
        state = model.table.state()[j, i]
        if state != Table.FLASH:
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#C00000" if state == Table.LOCAL else "#D08A00"))
            painter.drawPolygon(QPolygon([QPoint(r.right() - 6, r.top() + 1),
                                          QPoint(r.right(), r.top() + 1),
                                          QPoint(r.right(), r.top() + 7)]))
            painter.restore()

        # Three corners, three facts. Top right is what the ECU has seen,
        # bottom left is what the marker said, and bottom right is whether
        # the engine has ever run here -- which is what tells you whether
        # the number in this cell was measured or guessed.
        seen = self.editor.coverage.get((j, i))
        if seen:
            painter.save()
            painter.setPen(Qt.NoPen)
            f = min(seen / TableEditor.COVER_FULL, 1.0)
            painter.setBrush(QColor(60, 60, 60, 45 + int(f * 125)))
            d = 3 + int(f * 3)
            painter.drawEllipse(r.right() - d - 2, r.bottom() - d - 2, d, d)
            painter.restore()

        # What the marker said, on the cell rather than in a list: a wedge
        # pointing the way the number has to move, sized by how far out it
        # is. Drawn bottom-left, where the dirty markers are not.
        mark = self.editor.findings.get((j, i))
        if mark is not None:
            error, sev, unsafe = mark
            painter.save()
            painter.setPen(Qt.NoPen)
            if unsafe:
                painter.setBrush(QColor("#C00000"))
            else:
                painter.setBrush(QColor(40, 70, 190, min(90 + int(sev * 110), 235)))
            n = min(5 + int(sev * 4), 11)
            x0, y0 = r.left() + 2, r.bottom() - 2
            if error > 0:       # too high: bring it down
                painter.drawPolygon(QPolygon([QPoint(x0, y0 - n), QPoint(x0 + n, y0 - n),
                                              QPoint(x0 + n // 2, y0)]))
            else:               # too low: take it up
                painter.drawPolygon(QPolygon([QPoint(x0 + n // 2, y0 - n),
                                              QPoint(x0, y0), QPoint(x0 + n, y0)]))
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


class TableView(QTableView):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: editor.show_menu(self.viewport().mapToGlobal(pos)))

    def keyPressEvent(self, ev):
        if not self.editor.handle_key(ev):
            super().keyPressEvent(ev)


class AxisDialog(QDialog):
    """Edit breakpoints. Values are re-sampled from the old surface on OK."""

    fixed_layout = False        # set when a connected ECU pins the dimensions

    def _expected(self, g):
        return self.table.n_x if g is self.tx else self.table.n_y

    def __init__(self, table: Table, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Axis Breakpoints — {table.title}")
        self.table = table
        self.tx = self._grid(table.x_name, table.x)
        self.ty = self._grid(table.y_name, table.y)
        row = QHBoxLayout()
        for name, grid in ((f"{table.x_name} ({table.x_unit})", self.tx),
                           (f"{table.y_name} ({table.y_unit})", self.ty)):
            col = QVBoxLayout(); col.addWidget(QLabel(name)); col.addWidget(grid)
            btns = QHBoxLayout()
            b_add = QPushButton("Add"); b_del = QPushButton("Remove")
            b_add.clicked.connect(lambda _, g=grid: self._add(g))
            b_del.clicked.connect(lambda _, g=grid: g.removeRow(g.currentRow()))
            btns.addWidget(b_add); btns.addWidget(b_del); col.addLayout(btns)
            row.addLayout(col)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(row); lay.addWidget(bb)
        self.result_x = self.result_y = None

    def _grid(self, name, values):
        g = QTableWidget(len(values), 1)
        g.setHorizontalHeaderLabels([name]); g.verticalHeader().setVisible(False)
        g.horizontalHeader().setStretchLastSection(True); g.setFixedWidth(130)
        for r, v in enumerate(values):
            g.setItem(r, 0, QTableWidgetItem(f"{v:g}"))
        return g

    def _add(self, g):
        r = g.currentRow() + 1 if g.currentRow() >= 0 else g.rowCount()
        g.insertRow(r); g.setItem(r, 0, QTableWidgetItem(""))
        g.setCurrentCell(r, 0); g.editItem(g.item(r, 0))

    def _read(self, g):
        vals = []
        for r in range(g.rowCount()):
            it = g.item(r, 0)
            txt = it.text().strip() if it else ""
            if txt:
                v = float(txt)
                if not np.isfinite(v):
                    raise ValueError("a breakpoint must be a finite number")
                vals.append(v)
        if len(vals) < 2 or any(b <= a for a, b in zip(vals, vals[1:])):
            raise ValueError("breakpoints must be strictly increasing, at least two")
        if self.fixed_layout and (len(vals) != self._expected(g)):
            raise ValueError("the connected ECU has a fixed table layout: you can "
                             "move breakpoints but not add or remove them")
        return np.asarray(vals, dtype=float)

    def _accept(self):
        try:
            self.result_x, self.result_y = self._read(self.tx), self._read(self.ty)
        except ValueError as e:
            QMessageBox.warning(self, "Axis Breakpoints", str(e)); return
        self.accept()


class TableEditor(QWidget):
    changed = Signal()          # table values or axes changed
    undo_changed = Signal()     # undo/redo availability changed

    def __init__(self, table: Table, boost_psi: bool = True, parent=None):
        super().__init__(parent)
        self.table = table
        self.cursor = None
        self.cursor_xy = None
        self.findings = {}   # (j, i) -> (signed error, severity, unsafe)
        self.coverage = {}   # (j, i) -> samples the engine has spent there
        self.undo_stack, self.redo_stack = [], []

        self.model = TableModel(table, boost_psi)
        self.model.before_change = self.push_undo
        self.model.dataChanged.connect(self._on_data_changed)

        head = QHBoxLayout(); head.setContentsMargins(4, 3, 4, 2)
        self.title = QLabel(f"<b>{table.title}</b>")
        self.info = QLabel(); self.info.setObjectName("dim"); self._refresh_info()
        self.b2d = QPushButton("2D"); self.b3d = QPushButton("3D")
        for b in (self.b2d, self.b3d):
            b.setCheckable(True); b.setFixedWidth(34)
        self.b2d.setChecked(True)
        self.b2d.clicked.connect(self.show_2d); self.b3d.clicked.connect(self.show_3d)
        head.addWidget(self.title); head.addSpacing(10); head.addWidget(self.info)
        head.addStretch(); head.addWidget(self.b2d); head.addWidget(self.b3d)

        self.view = TableView(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(HeatDelegate(self))
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.view.setEditTriggers(QAbstractItemView.DoubleClicked
                                  | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.AnyKeyPressed)
        for hdr in (self.view.horizontalHeader(), self.view.verticalHeader()):
            hdr.setSectionResizeMode(QHeaderView.Fixed); hdr.setHighlightSections(False)
        self.view.horizontalHeader().setDefaultSectionSize(54)
        self.view.verticalHeader().setDefaultSectionSize(20)
        self.view.verticalHeader().setFixedWidth(56)
        self.view.setCornerButtonEnabled(False)
        f = QFont(self.font()); f.setPointSize(8)
        for w in (self.view, self.view.horizontalHeader(), self.view.verticalHeader()):
            w.setFont(f)

        self.surface = Surface3D(self)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.view); self.stack.addWidget(self.surface)

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addLayout(head); lay.addWidget(self.stack)

    # ---- views ----------------------------------------------------------
    def show_2d(self):
        self.b2d.setChecked(True); self.b3d.setChecked(False)
        self.stack.setCurrentWidget(self.view); self.view.setFocus()

    def show_3d(self):
        self.b2d.setChecked(False); self.b3d.setChecked(True)
        self.stack.setCurrentWidget(self.surface); self.surface.setFocus()

    def set_units(self, boost_psi: bool):
        self.model.boost_psi = boost_psi
        self.model.headerDataChanged.emit(Qt.Vertical, 0, self.model.rowCount() - 1)
        self._refresh_info(); self.surface.update()

    def _refresh_info(self):
        t = self.table
        self.info.setText(f"{t.x_name} × {self.model.y_header_title()}"
                          f"{'  —  ' + t.unit if t.unit else ''}")

    def _on_data_changed(self, *_):
        self.changed.emit(); self.surface.update()

    # ---- live cursor ----------------------------------------------------
    def set_findings(self, findings):
        """Where the marker says this table is still wrong.

        The marker samples between breakpoints on purpose, so a finding
        does not land on a cell. It is attributed to the nearest corner --
        the cell a student would actually edit to move that point -- and
        several findings can land on one cell, in which case the worst of
        them wins, because that is the one still failing.
        """
        marks = {}
        for f in findings or ():
            cell = self.table.cell_of(float(f.rpm), float(f.load))
            if cell is None:
                continue
            cj, ci, fy, fx = cell
            j = min(cj + (1 if fy >= 0.5 else 0), self.table.n_y - 1)
            i = min(ci + (1 if fx >= 0.5 else 0), self.table.n_x - 1)
            sev = abs(f.error) / f.tol if f.tol else 1.0
            prev = marks.get((j, i))
            if prev is None or (f.unsafe, sev) > (prev[2], abs(prev[1])):
                marks[(j, i)] = (f.error, sev, f.unsafe)
        self.findings = marks
        self.view.viewport().update()

    def clear_findings(self):
        self.findings = {}
        self.view.viewport().update()

    def clear_coverage(self):
        """Forget where the engine has been. Between pulls, or when the
        point is to see what THIS pull touched."""
        self.coverage = {}
        self.view.viewport().update()

    # Channels publish at 25 Hz, so this many samples is a little under half
    # a second in one cell -- about what a pull spends crossing one.
    COVER_FULL = 10

    def set_cursor(self, xv: float, yv: float):
        new = self.table.cell_of(xv, yv)
        old = self.cursor
        self.cursor, self.cursor_xy = new, (xv, yv)
        if new is not None:
            # Where the engine has actually been. Not what it found there:
            # coverage says which cells you have data for, and the reading
            # and the decision stay yours.
            cj, ci, fy, fx = new
            j = min(cj + (1 if fy >= 0.5 else 0), self.table.n_y - 1)
            i = min(ci + (1 if fx >= 0.5 else 0), self.table.n_x - 1)
            self.coverage[(j, i)] = self.coverage.get((j, i), 0) + 1
        for c in (old, new):
            if c is None: continue
            cj, ci, *_ = c
            tl = self.model.index(self.model.row_of(cj + 1), ci)
            br = self.model.index(self.model.row_of(cj), ci + 1)
            self.view.viewport().update(self.view.visualRect(tl).united(self.view.visualRect(br)))
        if self.stack.currentWidget() is self.surface:
            self.surface.update()

    def clear_cursor(self):
        self.cursor = self.cursor_xy = None
        self.view.viewport().update(); self.surface.update()

    # ---- selection ------------------------------------------------------
    def _selection(self):
        idx = self.view.selectionModel().selectedIndexes()
        if not idx:
            cur = self.view.currentIndex()
            idx = [cur] if cur.isValid() else []
        if not idx:
            return None
        mask = np.zeros_like(self.table.values, dtype=bool)
        js, is_ = [], []
        for ix in idx:
            j, i = self.model.ji(ix); mask[j, i] = True; js.append(j); is_.append(i)
        return mask, (min(js), max(js), min(is_), max(is_))

    # ---- undo -----------------------------------------------------------
    def _snapshot(self):
        t = self.table
        return dict(x=t.x.copy(), y=t.y.copy(), values=t.values.copy(),
                    burned=t.burned.copy(), saved=t.saved.copy(),
                    sent=t.sent.copy())

    def _restore(self, s):
        t = self.table
        axes_changed = (s["x"].shape != t.x.shape or s["y"].shape != t.y.shape
                        or not np.array_equal(s["x"], t.x) or not np.array_equal(s["y"], t.y))
        t.x, t.y, t.values = s["x"].copy(), s["y"].copy(), s["values"].copy()
        # the baselines travel with the snapshot, so the dirty marks after an
        # undo are recomputed from them and can never go stale
        t.burned, t.saved, t.sent = (s["burned"].copy(), s["saved"].copy(),
                                     s["sent"].copy())
        if axes_changed: self.model.reset_axes()
        else: self.model.refresh()
        self._refresh_info(); self.changed.emit(); self.surface.update()

    def push_undo(self):
        self.undo_stack.append(self._snapshot()); del self.undo_stack[:-200]
        self.redo_stack.clear(); self.undo_changed.emit()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._snapshot()); self._restore(self.undo_stack.pop())
            self.undo_changed.emit()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._snapshot()); self._restore(self.redo_stack.pop())
            self.undo_changed.emit()

    # ---- operations -----------------------------------------------------
    def _apply(self, fn):
        sel = self._selection()
        if sel is None: return
        self.push_undo()
        fn(sel)
        # bulk operations clamp rather than refuse: a scale that would push a
        # few cells past the limit still does the useful thing
        self.table.values[:] = self.table.clip(self.table.values)
        self.model.refresh()

    def bump(self, sign: int, big: bool = False):
        step = self.table.step * (10 if big else 1) * sign
        self._apply(lambda sel: ops.bump(self.table.values, sel[0], step))

    def scale_dialog(self):
        pct, ok = QInputDialog.getDouble(self, "Scale Selection", "Scale by (%):",
                                         100.0, 1.0, 1000.0, 1)
        if ok: self._apply(lambda sel: ops.scale(self.table.values, sel[0], pct / 100.0))

    def set_dialog(self):
        cur = self.view.currentIndex()
        v0 = float(cur.data(Qt.EditRole)) if cur.isValid() else 0.0
        v, ok = QInputDialog.getDouble(self, "Set Selection",
                                       f"Value ({self.table.unit or self.table.title}):",
                                       v0, self.table.lo, self.table.hi,
                                       self.model.decimals())
        if ok: self._apply(lambda sel: ops.set_value(self.table.values, sel[0], v))

    def interpolate(self):
        self._apply(lambda sel: ops.interpolate(self.table.values, *sel[1]))

    def smooth(self):
        self._apply(lambda sel: ops.smooth(self.table.values, sel[0]))

    def copy(self):
        sel = self._selection()
        if sel: QGuiApplication.clipboard().setText(
            ops.to_tsv(self.table.values, *sel[1], self.table.fmt))

    def paste(self):
        block = ops.from_tsv(QGuiApplication.clipboard().text())
        sel = self._selection()
        if block is None or sel is None:
            return
        j_top, i_left = sel[1][1], sel[1][2]         # top-left of the selection on screen
        t = self.table
        block = t.clip(block)
        self.push_undo()
        for r in range(block.shape[0]):
            for c in range(block.shape[1]):
                j, i = j_top - r, i_left + c
                if 0 <= j < t.n_y and 0 <= i < t.n_x:
                    t.values[j, i] = block[r, c]
        self.model.refresh()

    def edit_axes(self):
        dlg = AxisDialog(self.table, self)
        if dlg.exec() != QDialog.Accepted: return
        t = self.table
        self.push_undo()
        new_values = t.clip(ops.regrid(t.values, t.x, t.y,
                                       dlg.result_x, dlg.result_y, t.lookup))
        t.x, t.y, t.values = dlg.result_x, dlg.result_y, new_values
        t.invalidate_baselines()
        self.model.reset_axes(); self._refresh_info()
        self.changed.emit(); self.surface.update()

    # ---- keys and menu --------------------------------------------------
    def handle_key(self, ev) -> bool:
        k, mods = ev.key(), ev.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if k in (Qt.Key_Plus, Qt.Key_PageUp) or (k == Qt.Key_Equal and mods & Qt.ShiftModifier):
            self.bump(+1, ctrl); return True
        if k in (Qt.Key_Minus, Qt.Key_PageDown):
            self.bump(-1, ctrl); return True
        if k in (Qt.Key_Asterisk, Qt.Key_Slash):
            self.scale_dialog(); return True
        if k == Qt.Key_Equal:
            self.set_dialog(); return True
        if k == Qt.Key_I and not ctrl:
            self.interpolate(); return True
        if k == Qt.Key_S and not ctrl:
            self.smooth(); return True
        if ev.matches(QKeySequence.Copy):
            self.copy(); return True
        if ev.matches(QKeySequence.Paste):
            self.paste(); return True
        if ev.matches(QKeySequence.Undo):
            self.undo(); return True
        if ev.matches(QKeySequence.Redo):
            self.redo(); return True
        return False

    def show_menu(self, global_pos):
        m = QMenu(self)
        def add(label, slot, key=None, enabled=True):
            a = QAction(label, m)
            if key: a.setShortcut(QKeySequence(key)); a.setShortcutVisibleInContextMenu(True)
            a.setEnabled(enabled); a.triggered.connect(slot); m.addAction(a)
        add("Interpolate", self.interpolate, "I")
        add("Smooth", self.smooth, "S")
        add("Scale…", self.scale_dialog, "*")
        add("Set Value…", self.set_dialog, "=")
        m.addSeparator()
        add("Increase", lambda: self.bump(+1), "+")
        add("Decrease", lambda: self.bump(-1), "-")
        m.addSeparator()
        add("Copy", self.copy, "Ctrl+C")
        add("Paste", self.paste, "Ctrl+V")
        m.addSeparator()
        add("Undo", self.undo, "Ctrl+Z", bool(self.undo_stack))
        add("Redo", self.redo, "Ctrl+Y", bool(self.redo_stack))
        m.addSeparator()
        add("Axis Breakpoints…", self.edit_axes)
        m.exec(global_pos)
