"""Main window: menus, toolbar, status bar, docks, tabbed centre."""
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QLabel, QMainWindow,
                               QHBoxLayout, QMessageBox, QSizePolicy, QStyle,
                               QTabWidget, QToolBar, QWidget)

from tqmodel.synth import generate
from tqmodel.units import kpa_abs_to_boost_psi
from .. import APP_NAME, APP_VERSION, ORG_NAME
import time

from ..core.audio_out import AudioOutput
from ..core.connection import DemoConnection
from ..core.sim_ecu import SimulatedECU
from ..core.tune import Tune, default_tune
from .datalog_view import DatalogView
from .gauges import GaugePanel
from .mimic import MimicPage
from .nav_tree import TREE, NavTree
from .sim_dock import SimulatorDock
from .settings_page import PlaceholderPage, SettingsPage
from .table_editor import TableEditor

INK = QColor("#303030")


def _glyph(kind: str) -> QIcon:
    """Tiny monochrome 16 px toolbar glyphs, drawn rather than shipped."""
    pm = QPixmap(16, 16); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(INK, 1.6)); p.setBrush(Qt.NoBrush)
    if kind == "connect":       # a plug
        p.drawRoundedRect(2, 5, 8, 6, 1, 1)
        p.drawLine(10, 8, 14, 8)
        p.drawLine(4, 2, 4, 5); p.drawLine(8, 2, 8, 5)
    elif kind == "burn":        # a chip
        p.setBrush(INK); p.drawRect(4, 4, 8, 8); p.setBrush(Qt.NoBrush)
        for k in (5, 8, 11):
            p.drawLine(k, 1, k, 4); p.drawLine(k, 12, k, 15)
            p.drawLine(1, k, 4, k); p.drawLine(12, k, 15, k)
    elif kind == "gauge":       # a dial
        p.drawEllipse(2, 2, 12, 12); p.drawLine(8, 8, 12, 5)
    elif kind == "log":         # a trace
        p.drawPolyline([__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(*xy)
                        for xy in ((1, 12), (4, 6), (7, 10), (10, 3), (13, 8), (15, 6))])
    p.end()
    return QIcon(pm)


class _ElidedLabel(QLabel):
    """A label that shortens its text with an ellipsis instead of having
    it cut off mid-word. Used for the keyboard hint, which is the one
    piece of status text allowed to lose its tail when space runs out."""

    def setText(self, text):
        self._full = text
        super().setText(text)

    def minimumSizeHint(self):
        h = super().minimumSizeHint()
        h.setWidth(0)
        return h

    def paintEvent(self, ev):
        full = getattr(self, "_full", self.text())
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(full, Qt.ElideRight, self.width())
        painter = QPainter(self)
        self.style().drawItemText(
            painter, self.rect(), int(self.alignment()), self.palette(),
            self.isEnabled(), elided, self.foregroundRole())
        painter.end()
        if ev is not None:
            ev.accept()


class MainWindow(QMainWindow):
    def __init__(self, tune: Tune | None = None, persist_layout: bool = True):
        super().__init__()
        self.persist_layout = persist_layout
        self.tune = tune or default_tune()
        self.armed = False           # live write is off until deliberately armed
        self.sim = SimulatedECU(self.tune)
        self.audio = AudioOutput()
        self.demo = DemoConnection()
        self.conn = self.sim
        self._t0 = time.monotonic()
        self.editors = {}           # key -> widget
        self.boost_psi = True

        self.setWindowTitle(APP_NAME)
        self.resize(1400, 860)
        self.setIconSize(QSize(16, 16))
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks
                            | QMainWindow.AllowTabbedDocks)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_docks()
        self._build_central()
        self._build_statusbar()

        for c in (self.sim, self.demo):
            c.state_changed.connect(self._on_conn_state)
            c.error.connect(self._on_conn_error)
            c.channels_updated.connect(self._on_channels)
        self._on_conn_state(False)
        self._refresh_title()

        self.open_item("table", "ve", "VE Table")
        self._load_demo_log()
        if not self._restore_layout():
            # first run: dock sizes only stick once the window has laid out
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._default_dock_sizes)

    # ----------------------------------------------------------------- build
    def _build_actions(self):
        st = self.style()
        A = QAction
        self.a_new = A("&New Tune", self, shortcut=QKeySequence.New, triggered=self.new_tune)
        self.a_open = A(st.standardIcon(QStyle.SP_DialogOpenButton), "&Open Tune…", self,
                        shortcut=QKeySequence.Open, triggered=self.open_tune)
        self.a_save = A(st.standardIcon(QStyle.SP_DialogSaveButton), "&Save Tune", self,
                        shortcut=QKeySequence.Save, triggered=self.save_tune)
        self.a_save_as = A("Save Tune &As…", self, shortcut=QKeySequence.SaveAs,
                           triggered=self.save_tune_as)
        self.a_exit = A("E&xit", self, shortcut=QKeySequence.Quit, triggered=self.close)

        self.a_connect = A(_glyph("connect"), "&Connect", self, shortcut="F2",
                           triggered=self.toggle_connect)
        self.a_burn = A(_glyph("burn"), "&Burn to ECU", self, shortcut="F5",
                        triggered=self.burn)
        self.a_read = A("&Read from ECU", self, triggered=self.read_from_ecu)
        self.a_send = A("&Send to ECU RAM", self, shortcut="F4", triggered=self.send_all)
        self.a_arm = A("Arm &live write", self, checkable=True,
                       triggered=self.set_armed)
        self.a_burn.setEnabled(False)
        self.a_read.setEnabled(False)
        self.a_send.setEnabled(False)
        self.a_arm.setEnabled(False)

        # Edit / Tools act on the current table editor. Their shortcuts are
        # shown in the menus but only live in the table view itself, so they
        # never steal Ctrl+C or Ctrl+Z from a text field elsewhere.
        def ed_action(label, method, key=None):
            a = A(label, self, enabled=False)
            if key: a.setShortcut(QKeySequence(key)); a.setShortcutContext(Qt.WidgetShortcut)
            a.triggered.connect(lambda: self._with_editor(method))
            return a
        self.a_undo = ed_action("&Undo", "undo", QKeySequence.Undo)
        self.a_redo = ed_action("&Redo", "redo", QKeySequence.Redo)
        self.a_copy = ed_action("&Copy", "copy", QKeySequence.Copy)
        self.a_paste = ed_action("&Paste", "paste", QKeySequence.Paste)
        self.a_interp = ed_action("&Interpolate Selection", "interpolate", "I")
        self.a_smooth = ed_action("&Smooth Selection", "smooth", "S")
        self.a_scale = ed_action("Sc&ale Selection…", "scale_dialog", "*")
        self.a_set = ed_action("Set Selection &Value…", "set_dialog", "=")
        self.a_axes = ed_action("Set &Axis Breakpoints…", "edit_axes")
        self.a_view3d = ed_action("Show &3D Surface", "show_3d")
        self.a_view2d = ed_action("Show &Table", "show_2d")

        self.a_conn_sim = A("&Simulated engine", self, checkable=True, checked=True)
        self.a_conn_demo = A("&Demo point", self, checkable=True)
        self.a_conn_sim.triggered.connect(lambda: self._set_connection(self.sim))
        self.a_conn_demo.triggered.connect(lambda: self._set_connection(self.demo))

        self.a_units_psi = A("Boost in &psi", self, checkable=True, checked=True)
        self.a_units_kpa = A("MAP in &kPa", self, checkable=True)
        self.a_units_psi.triggered.connect(lambda: self._set_units(True))
        self.a_units_kpa.triggered.connect(lambda: self._set_units(False))
        self.a_theme_classic = A("&Classic", self, checkable=True, checked=True)
        self.a_theme_dark = A("&Dark", self, checkable=True, enabled=False)
        self.a_about = A("&About…", self, triggered=self.about)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_new, self.a_open, self.a_save, self.a_save_as):
            m.addAction(a)
        m.addSeparator(); m.addAction(self.a_exit)

        m = mb.addMenu("&Edit")
        m.addAction(self.a_undo); m.addAction(self.a_redo); m.addSeparator()
        m.addAction(self.a_copy); m.addAction(self.a_paste)

        m = mb.addMenu("&ECU")
        m.addAction(self.a_connect)
        sub = m.addMenu("Connect &to"); sub.addAction(self.a_conn_sim); sub.addAction(self.a_conn_demo)
        m.addSeparator(); m.addAction(self.a_read); m.addAction(self.a_send)
        m.addAction(self.a_burn); m.addSeparator(); m.addAction(self.a_arm)

        self.m_view = mb.addMenu("&View")

        m = mb.addMenu("&Tools")
        for a in (self.a_interp, self.a_smooth, self.a_scale, self.a_set):
            m.addAction(a)
        m.addSeparator(); m.addAction(self.a_axes)
        m.addSeparator(); m.addAction(self.a_view2d); m.addAction(self.a_view3d)

        m = mb.addMenu("&Help")
        m.addAction(self.a_about)

    def _build_toolbar(self):
        tb = QToolBar("Main"); tb.setObjectName("main_toolbar")
        tb.setMovable(False); tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.addAction(self.a_connect); tb.addAction(self.a_burn); tb.addSeparator()
        tb.addAction(self.a_open); tb.addAction(self.a_save); tb.addSeparator()
        self.addToolBar(tb)
        self.toolbar = tb

    def _build_docks(self):
        self.nav = NavTree()
        self.nav.activated_item.connect(self.open_item)
        d = QDockWidget("Navigator", self); d.setObjectName("dock_nav")
        d.setWidget(self.nav); d.setMinimumWidth(190)
        d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.LeftDockWidgetArea, d); self.dock_nav = d

        self.sim_dock = SimulatorDock(self.sim, self.audio)
        d = QDockWidget("Simulator", self); d.setObjectName("dock_sim")
        d.setWidget(self.sim_dock); d.setMinimumWidth(230)
        self.addDockWidget(Qt.LeftDockWidgetArea, d); self.dock_sim = d
        self.splitDockWidget(self.dock_nav, self.dock_sim, Qt.Vertical)

        self.gauges = GaugePanel()
        d = QDockWidget("Gauges", self); d.setObjectName("dock_gauges")
        d.setWidget(self.gauges); d.setMinimumWidth(270)
        self.addDockWidget(Qt.RightDockWidgetArea, d); self.dock_gauges = d

        self.datalog = DatalogView()
        d = QDockWidget("Datalog", self); d.setObjectName("dock_log")
        d.setWidget(self.datalog); d.setMinimumHeight(180)
        self.addDockWidget(Qt.BottomDockWidgetArea, d); self.dock_log = d

        for dock, glyph in ((self.dock_nav, None), (self.dock_sim, None), (self.dock_gauges, "gauge"), (self.dock_log, "log")):
            a = dock.toggleViewAction()
            if glyph: a.setIcon(_glyph(glyph))
            self.m_view.addAction(a)
            if glyph: self.toolbar.addAction(a)
        self.m_view.addSeparator()
        self.m_view.addAction(self.a_units_psi); self.m_view.addAction(self.a_units_kpa)
        self.m_view.addSeparator()
        self.m_view.addAction(self.a_theme_classic); self.m_view.addAction(self.a_theme_dark)

    def _build_central(self):
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True); self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._update_edit_actions)
        self.setCentralWidget(self.tabs)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.l_conn = QLabel(); self.l_tune = QLabel(); self.l_burn = QLabel()
        self.l_arm = QLabel()
        # A status label must never be squeezed below its own text. The
        # hint in the middle is the only thing allowed to absorb slack,
        # and it elides; everything else is a fact the tuner needs to be
        # able to read, so it keeps its width.
        for lbl in (self.l_conn, self.l_tune, self.l_burn, self.l_arm):
            lbl.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
            lbl.setTextFormat(Qt.RichText)
        self.l_live = QLabel(); self.l_live.setMinimumWidth(240)
        self.l_hint = _ElidedLabel(); self.l_hint.setObjectName("dim")

        # One container with a real layout, rather than four widgets added
        # to the status bar directly. QStatusBar positions its items when
        # they are added and on resize, not when a child's size hint
        # changes, so labels that start empty and gain text later end up
        # drawn on top of each other.
        self._status_row = bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        for lbl in (self.l_conn, self.l_tune, self.l_burn, self.l_arm):
            row.addWidget(lbl)
        row.addWidget(self.l_hint, 1)
        sb.addWidget(bar, 1)
        sb.addPermanentWidget(self.l_live)

    # ----------------------------------------------------------------- items
    def open_item(self, kind: str, key: str, label: str):
        if key in self.editors:
            self.tabs.setCurrentWidget(self.editors[key]); return
        if kind == "table":
            w = TableEditor(self.tune.tables[key], boost_psi=self.boost_psi)
            w.changed.connect(lambda k=key: self._on_table_changed(k))
            w.undo_changed.connect(self._update_edit_actions)
            if self.conn.is_connected():
                ch = self.conn.channels()
                w.set_cursor(ch["rpm"], self._y_for(key, ch))
        elif kind == "course":
            from .course_page import CoursePage
            w = CoursePage(lambda: self.tune, lambda: self.sim)
            w.load_student_tune.connect(self._load_course_tune)
        elif kind == "settings":
            w = SettingsPage(key, self.tune.engine)
            w.changed.connect(self._engine_changed)
        elif kind == "page" and key == "datalog":
            self.dock_log.show(); self.dock_log.raise_(); return
        elif kind == "page" and key == "simdock":
            self.dock_sim.show(); self.dock_sim.raise_(); return
        elif kind == "page" and key == "mimic":
            w = MimicPage()
            w.maximize_toggled.connect(self.set_mimic_maximized)
            if self.conn.is_connected(): w.update_channels(self.conn.channels())
        else:
            phase = {"torque_page": "Phase 4", "shift_cut": "Phase 4",
                     "shift_sched": "Phase 4"}.get(key, "Phase 2")
            w = PlaceholderPage(label, phase)
        self.editors[key] = w
        self.tabs.addTab(w, label); self.tabs.setCurrentWidget(w)
        self._update_edit_actions()

    def _close_tab(self, i):
        w = self.tabs.widget(i)
        for k, v in list(self.editors.items()):
            if v is w: del self.editors[k]
        self.tabs.removeTab(i); w.deleteLater()
        self._update_edit_actions()

    def _current_editor(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, TableEditor) else None

    def _with_editor(self, method: str):
        ed = self._current_editor()
        if ed: getattr(ed, method)()

    def _update_edit_actions(self, *_):
        ed = self._current_editor()
        for a in (self.a_copy, self.a_paste, self.a_interp, self.a_smooth, self.a_scale,
                  self.a_set, self.a_axes, self.a_view2d, self.a_view3d):
            a.setEnabled(ed is not None)
        self.a_undo.setEnabled(bool(ed and ed.undo_stack))
        self.a_redo.setEnabled(bool(ed and ed.redo_stack))
        self.l_hint.setText("+ / −  bump    Ctrl  ×10    *  scale    =  set    I  interpolate    "
                            "S  smooth    Ctrl+C / V  copy, paste    Ctrl+Z  undo" if ed else "")

    def set_mimic_maximized(self, on: bool):
        if on:
            self._docks_before = [d for d in (self.dock_gauges, self.dock_log, self.dock_sim, self.dock_nav) if d.isVisible()]
            for d in (self.dock_gauges, self.dock_log, self.dock_nav): d.hide()
        else:
            for d in getattr(self, "_docks_before", []): d.show()
        if "mimic" in self.editors: self.editors["mimic"].b_max.setChecked(on)

    def open_key(self, key: str):
        for _group, children in TREE:
            for label, kind, k in children:
                if k == key:
                    self.open_item(kind, k, label); return

    def _y_for(self, key, ch):
        t = self.tune.tables.get(key)
        if t is None: return 0.0
        if t.y_unit == "kPa": return ch.get("map", 0.0)
        if t.y_unit == "%": return ch.get("tps", 0.0)
        if t.y_unit == "g/cyl": return ch.get("air", 0.0)
        return 0.0

    # ----------------------------------------------------------------- tune
    def new_tune(self):
        if not self._confirm_discard(): return
        self._replace_tune(default_tune())

    def open_tune(self):
        if not self._confirm_discard(): return
        path, _ = QFileDialog.getOpenFileName(self, "Open Tune", "", "Tune files (*.tune);;All files (*)")
        if path:
            try:
                tune = Tune.load(path)
            except Exception as e:
                QMessageBox.critical(self, "Open Tune", f"Could not open tune:\n{e}")
                return
            self._replace_tune(tune)
            if tune.upgraded:
                # Safety limits among them, so this is said out loud
                # rather than applied quietly behind the tuner's back.
                QMessageBox.information(
                    self, "Open Tune",
                    "This tune was saved by an older version and did not "
                    "contain:\n\n  " + "\n  ".join(tune.upgraded) +
                    "\n\nDefaults have been filled in. Check them under "
                    "Engine Setup and Safety before running the engine, then "
                    "save the tune.")

    def save_tune(self):
        if self.tune.path is None:
            return self.save_tune_as()
        self.tune.save(self.tune.path); self._refresh_title(); return True

    def save_tune_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Tune As", str(self.tune.path or "tune.tune"),
                                              "Tune files (*.tune)")
        if not path: return False
        self.tune.save(path); self._refresh_title(); return True

    def _replace_tune(self, tune: Tune):
        tune.validate()                 # never swap in something unrunnable
        self.tune = tune
        self.sim.tune = tune.copy()     # the ECU gets its own image, as over a wire
        self.sim.flash = tune.copy()
        while self.tabs.count(): self._close_tab(0)
        self.editors.clear()
        self.open_item("table", "ve", "VE Table")
        self._refresh_title()

    def _load_course_tune(self):
        """Swap in the deliberately flawed tune the course starts from."""
        from ..core.course import student_tune
        if not self._confirm_discard():
            return
        self._replace_tune(student_tune())
        # _replace_tune closes every tab, including the Course page the
        # button was pressed on. Put it back, or the page vanishes the
        # moment it is used.
        self.open_key("course")
        self.statusBar().showMessage(
            "TQ-101 starting tune loaded. Open the Course page and mark "
            "Lab 1 to see where it stands.", 8000)

    def _confirm_discard(self) -> bool:
        # the question is whether work would be LOST, which is the file
        # state. Whether the ECU has it is a different question entirely.
        if not self.tune.file_dirty: return True
        r = QMessageBox.question(self, APP_NAME, "The tune has unsaved changes. Save first?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save: return bool(self.save_tune())
        return r == QMessageBox.Discard

    def _engine_changed(self):
        self.tune.touch_engine(); self._refresh_title()

    def _refresh_title(self, *_):
        name = self.tune.path.name if self.tune.path else self.tune.name
        star = "*" if self.tune.file_dirty else ""
        self.setWindowTitle(f"{name}{star} — {APP_NAME}")
        self._status(self.l_tune, f"Tune: {name}{star}")
        self._status(self.l_burn,
                     "<span style='color:#A00000'>Burn required</span>"
                     if self.tune.ecu_dirty else "")

    # ----------------------------------------------------------------- ecu
    def toggle_connect(self):
        if self.conn.is_connected(): self.conn.disconnect_ecu()
        else: self.conn.connect_ecu()

    def use_simulator(self):
        self._set_connection(self.sim)

    def _set_connection(self, conn):
        if conn is self.conn: return
        if self.conn.is_connected(): self.conn.disconnect_ecu()
        self.conn = conn
        self.a_conn_sim.setChecked(conn is self.sim); self.a_conn_demo.setChecked(conn is self.demo)
        self.dock_sim.setVisible(conn is self.sim)
        self._on_conn_state(False)

    def _status(self, label, html: str):
        """Set a status label and keep it wide enough to show what it says.

        The explicit activate() is not decoration: a label that grows
        after the row was first laid out does not get the row re-run on
        its own, and the result is text drawn over its neighbour."""
        label.setText(html)
        label.setMinimumWidth(label.sizeHint().width() if html else 0)
        row = getattr(self, "_status_row", None)
        if row is not None and row.layout() is not None:
            row.layout().invalidate()
            row.layout().activate()

    def set_armed(self, on: bool):
        """Armed means keystrokes go to the running engine. Unarmed, edits
        stay in the tuner until they are sent. This is a deliberate act,
        because the alternative is typing into a running engine by accident."""
        on = bool(on)
        changed = on != self.armed
        self.armed = on
        self.a_arm.setChecked(self.armed)
        # Blank is the wrong way to say "off". A tuner whose edits are
        # not reaching the engine needs to be told that, not left to
        # discover it by watching nothing happen.
        if self.armed:
            self._status(self.l_arm,
                         "<span style='color:#A00000'><b>LIVE WRITE ARMED</b></span>")
        elif self.conn.is_connected() and self.conn.writable:
            self._status(self.l_arm,
                         "<span style='color:#666666'>Live write off "
                         "(F4 send, F5 burn)</span>")
        else:
            self._status(self.l_arm, "")
        # Only say so when it actually changed. Disarming something that
        # was never armed is not news, and at start-up it puts a
        # temporary message over the status bar for no reason.
        if changed:
            self.statusBar().showMessage(
                "Live write armed: edits go straight to the ECU" if self.armed
                else "Live write disarmed: edits stay in the tuner", 4000)

    def send_all(self):
        """Push the tuner's whole image into ECU RAM."""
        if not (self.conn.is_connected() and self.conn.writable):
            QMessageBox.information(self, "Send", "Connect to a writable ECU first.")
            return False
        try:
            for key, t in self.tune.tables.items():
                self.conn.write_table(key, t.values, t.x, t.y)
                t.mark_sent()
            self.conn.tune.engine.update(self.tune.engine)
        except Exception as e:                        # noqa: BLE001
            QMessageBox.critical(self, "Send", f"The ECU refused the tune:\n{e}")
            return False
        self._refresh_open_editors(); self._refresh_title()
        self.statusBar().showMessage("Tune sent to ECU RAM", 3000)
        return True

    def burn(self):
        if not (self.conn.is_connected() and self.conn.writable):
            QMessageBox.information(self, "Burn", "Connect to a writable ECU first.")
            return
        # Anything still LOCAL has not reached the ECU, so burning now would
        # commit an image the tuner is not showing.
        if not self.send_all():
            return
        try:
            committed = self.conn.burn()
        except Exception as e:                        # noqa: BLE001
            QMessageBox.critical(self, "Burn", f"The burn failed:\n{e}")
            return
        # Verify: the CRC the ECU reports over what it committed must equal
        # the CRC the tuner computes over what it meant to send. Anything
        # else and the tune in the ECU is not the tune on screen.
        mine = self.tune.crcs()
        bad = [k for k, c in mine.items() if committed.get(k) != c]
        if bad:
            QMessageBox.critical(
                self, "Burn",
                "The ECU committed something different from what was sent.\n"
                "Mismatched tables: " + ", ".join(sorted(bad)) +
                "\n\nDo not run the engine on this tune. Read the ECU back.")
            return
        self.tune.mark_burned()
        self._refresh_open_editors(); self._refresh_title()
        self.statusBar().showMessage(
            f"Burned and verified: {len(mine)} tables, CRC match", 4000)

    def read_from_ecu(self):
        """Replace the tuner's image with what the ECU actually has."""
        if not self.conn.is_connected():
            QMessageBox.information(self, "Read", "Connect first.")
            return
        if not self._confirm_discard():
            return
        try:
            for key, t in self.tune.tables.items():
                t.values[:] = self.conn.read_table(key)
                t.mark_burned()
        except Exception as e:                        # noqa: BLE001
            QMessageBox.critical(self, "Read", f"Could not read the ECU:\n{e}")
            return
        self._refresh_open_editors(); self._refresh_title()
        self.statusBar().showMessage("Read from ECU", 3000)

    def _refresh_open_editors(self):
        for ed in self.editors.values():
            ed.model.refresh()

    def _on_table_changed(self, key: str):
        """A cell changed in the editor. Armed, it goes to the ECU now."""
        t = self.tune.tables.get(key)
        if t is None:
            return
        if self.armed and self.conn.is_connected() and self.conn.writable:
            try:
                self.conn.write_table(key, t.values, t.x, t.y)
                t.mark_sent()
            except Exception as e:                    # noqa: BLE001
                self.statusBar().showMessage(f"ECU refused the write: {e}", 6000)
        self._refresh_title()

    def _on_conn_error(self, message: str):
        """Something stopped the ECU talking. Say so loudly: the previous
        behaviour was for the simulation to stop and the screen to look
        exactly as if the engine were idling."""
        self.statusBar().showMessage(message, 0)
        self._status(self.l_conn,
                     f"<span style='color:#A00000'>●</span> {message}")
        QMessageBox.critical(self, APP_NAME, message)

    def _on_conn_state(self, connected: bool):
        writable = connected and self.conn.writable
        self.a_burn.setEnabled(writable)
        self.a_send.setEnabled(writable)
        self.a_arm.setEnabled(writable)
        self.a_read.setEnabled(connected)
        # Re-run either way: the indicator has to appear when a writable
        # ECU connects, not only when the arming changes.
        self.set_armed(self.armed and writable)
        self.datalog.set_live(connected and self.conn is self.sim)
        if connected:
            self._t0 = time.monotonic()
            self._status(self.l_conn,
                         f"<span style='color:#2E9E44'>●</span> Connected: {self.conn.name}")
            self.a_connect.setText("&Disconnect")
        else:
            self.audio.update(dict(rpm=0.0, map=30.0, boost=0.0, tps=0.0, cut_deg=0.0))
            self._status(self.l_conn,
                         "<span style='color:#9A9A9A'>●</span> Not connected")
            self.a_connect.setText("&Connect"); self.l_live.setText("")
            for w in self.editors.values():
                if isinstance(w, TableEditor): w.clear_cursor()
            self.gauges.update_channels({k: 0 for k in ("rpm", "boost", "tps", "iat", "spark",
                                                        "mbt", "torque", "torque_req", "authority", "batt")}
                                        | {"lambda": 1.0, "clt": 40})

    def _on_channels(self, ch: dict):
        self.gauges.update_channels(ch)
        self.l_live.setText(f"{ch['rpm']:.0f} rpm    {ch['boost']:.1f} psi    λ {ch['lambda']:.3f}    "
                            f"{ch['torque']:.0f} Nm")
        for key, w in self.editors.items():
            if isinstance(w, TableEditor):
                w.set_cursor(ch["rpm"], self._y_for(key, ch))
            elif isinstance(w, MimicPage):
                w.update_channels(ch)
        if self.conn is self.sim:
            self.sim_dock.update_channels(ch)
            self.datalog.append(time.monotonic() - self._t0, ch)
            self.audio.update(ch)

    # ----------------------------------------------------------------- misc
    def _set_units(self, psi: bool):
        self.boost_psi = psi
        self.a_units_psi.setChecked(psi); self.a_units_kpa.setChecked(not psi)
        for w in self.editors.values():
            if isinstance(w, TableEditor):
                w.set_units(psi)

    def _load_demo_log(self):
        log = generate(n=1200, seed=3)
        self.datalog.set_log(log["time_s"], {
            "rpm": log["rpm"], "boost": kpa_abs_to_boost_psi(log["map_kpa"]),
            "lambda": log["lam"], "torque": log["torque_ref"]})

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME}</b> {APP_VERSION}<br>Tuner application for a "
                          f"torque-structured engine controller.<br><br>Build: Phase 3 — "
                          f"simulated engine and 8HP, live powertrain view.")

    def _default_dock_sizes(self):
        self.resizeDocks([self.dock_log], [min(330, int(self.height() * 0.30))], Qt.Vertical)
        self.resizeDocks([self.dock_nav, self.dock_gauges], [200, 300], Qt.Horizontal)
        self.resizeDocks([self.dock_nav, self.dock_sim], [200, 520], Qt.Vertical)

    def _restore_layout(self) -> bool:
        if not self.persist_layout:
            return False
        s = QSettings(ORG_NAME, APP_NAME)
        ok = False
        if s.value("geometry"): ok = self.restoreGeometry(s.value("geometry")) or ok
        if s.value("state_v2"): ok = self.restoreState(s.value("state_v2")) or ok
        return ok

    def closeEvent(self, ev):
        if not self._confirm_discard():
            ev.ignore(); return
        self.audio.stop()
        if self.persist_layout:
            s = QSettings(ORG_NAME, APP_NAME)
            s.setValue("geometry", self.saveGeometry()); s.setValue("state_v2", self.saveState())
        super().closeEvent(ev)
