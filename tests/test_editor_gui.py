"""Drive the table editor with synthetic key events, offscreen.

    QT_QPA_PLATFORM=offscreen python tests/test_editor_gui.py     (Linux)
    python tests\\test_editor_gui.py                              (Windows, opens nothing visible)
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])
from tuner.core.tune import default_tune
from tuner.ui.table_editor import TableEditor

tb = default_tune().tables["ve"]
ed = TableEditor(tb); ed.show(); app.processEvents()
v, m, sm = ed.view, ed.model, ed.view.selectionModel()
fails = 0


def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def select(r0, c0, r1, c1):
    # Set current with NoUpdate first: QAbstractItemView.setCurrentIndex()
    # applies a selection command derived from cached keyboard modifiers,
    # which after a Ctrl+key click still reads as Ctrl held.
    sm.clear()
    sm.setCurrentIndex(m.index(r0, c0), QItemSelectionModel.NoUpdate)
    sm.select(QItemSelection(m.index(r0, c0), m.index(r1, c1)), QItemSelectionModel.Select)


base = tb.values.copy()

select(2, 2, 4, 4); QTest.keyClick(v, Qt.Key_Plus)
d = tb.values - base
check("+ bumps every selected cell by one step", int((d != 0).sum()) == 9 and np.allclose(d[d != 0], tb.step))
check("bumped cells are marked dirty", int(tb.dirty.sum()) == 9)

QTest.keyClick(v, Qt.Key_Minus, Qt.ControlModifier)
check("Ctrl - bumps by ten steps", np.allclose((tb.values - base)[d != 0], tb.step - 10 * tb.step))

QTest.keyClick(v, Qt.Key_Z, Qt.ControlModifier); QTest.keyClick(v, Qt.Key_Z, Qt.ControlModifier)
check("undo twice restores values and clears dirty", np.array_equal(tb.values, base) and not tb.dirty.any())
QTest.keyClick(v, Qt.Key_Y, Qt.ControlModifier)
check("redo re-applies", not np.array_equal(tb.values, base))
QTest.keyClick(v, Qt.Key_Z, Qt.ControlModifier)

select(2, 2, 6, 8)
j0, j1, i0, i1 = m.j_of(6), m.j_of(2), 2, 8
tb.values[j0, i0], tb.values[j0, i1], tb.values[j1, i0], tb.values[j1, i1] = 0.0, 1.0, 2.0, 3.0
QTest.keyClick(v, Qt.Key_I)
check("I interpolates the rectangle from its corners",
      abs(tb.values[(j0 + j1) // 2, (i0 + i1) // 2] - 1.5) < 1e-9 and abs(tb.values[j0, (i0 + i1) // 2] - 0.5) < 1e-9)
before = tb.values.copy(); QTest.keyClick(v, Qt.Key_S)
check("S smooths only the selection", np.array_equal(tb.values[0], before[0]) and not np.array_equal(tb.values, before))
tb.values[:] = base; tb.dirty[:] = False; m.refresh(); ed.undo_stack.clear()

select(0, 0, 1, 2); QTest.keyClick(v, Qt.Key_C, Qt.ControlModifier)
txt = QGuiApplication.clipboard().text()
check("Ctrl+C copies the block in display order, tab separated",
      txt.split("\n")[0].split("\t") == [tb.fmt.format(base[m.j_of(0), c]) for c in range(3)] and len(txt.split("\n")) == 2)
select(5, 5, 5, 5); QTest.keyClick(v, Qt.Key_V, Qt.ControlModifier)
check("Ctrl+V pastes anchored at the selection, rows downward on screen",
      abs(tb.values[m.j_of(5), 5] - base[m.j_of(0), 0]) < 1e-3 and abs(tb.values[m.j_of(6), 7] - base[m.j_of(1), 2]) < 1e-3)
check("pasted cells are dirty", bool(tb.dirty[m.j_of(5), 5]) and bool(tb.dirty[m.j_of(6), 7]))
QTest.keyClick(v, Qt.Key_Z, Qt.ControlModifier)
check("undo reverts the paste", np.array_equal(tb.values, base))

select(3, 3, 3, 3); QTest.keyClick(v, Qt.Key_7); app.processEvents()
editor = v.focusWidget()
check("typing a digit opens the cell editor with that digit", editor is not v and getattr(editor, "text", lambda: "")() == "7")
QTest.keyClick(editor, Qt.Key_Return); app.processEvents()
check("Enter commits it", tb.values[m.j_of(3), 3] == 7.0 and bool(tb.dirty[m.j_of(3), 3]))

ed.show_3d(); app.processEvents()
check("3D toggle switches the view", ed.stack.currentWidget() is ed.surface and ed.b3d.isChecked())
ed.set_cursor(3450, 158); app.processEvents()
check("cursor reaches the 3D view", ed.cursor is not None and ed.cursor_xy == (3450, 158))

print(f"\n{'all passed' if not fails else str(fails) + ' failed'}")
sys.exit(1 if fails else 0)
