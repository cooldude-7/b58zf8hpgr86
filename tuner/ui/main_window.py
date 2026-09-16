"""Main window: menus, toolbar, status bar, docks, tabbed centre."""
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QLabel, QMainWindow,
                               QMessageBox, QStyle, QTabWidget, QToolBar)

from tqmodel.synth import generate
from tqmodel.units import kpa_abs_to_boost_psi
from .. import APP_NAME, APP_VERSION, ORG_NAME
from ..core.connection import DemoConnection
from ..core.tune import Tune, default_tune
from .datalog_view import DatalogView
from .gauges import GaugePanel
from .nav_tree import NavTree
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


class MainWindow(QMainWindow):
    def __init__(self, tune: Tune | None = None, persist_layout: bool = True):
        super().__init__()
        self.persist_layout = persist_layout
        self.tune = tune or default_tune()
        self.conn = DemoConnection()
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

        self.conn.state_changed.connect(self._on_conn_state)
        self.conn.channels_updated.connect(self._on_channels)
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
        self.a_read = A("&Read from ECU", self, enabled=False)
        self.a_burn.setEnabled(False)

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
        for label, sc in (("&Undo", QKeySequence.Undo), ("&Redo", QKeySequence.Redo)):
            a = QAction(label, self, shortcut=sc, enabled=False); m.addAction(a)
        m.addSeparator()
        for label, sc in (("Cu&t", QKeySequence.Cut), ("&Copy", QKeySequence.Copy),
                          ("&Paste", QKeySequence.Paste)):
            a = QAction(label, self, shortcut=sc, enabled=False); m.addAction(a)

        m = mb.addMenu("&ECU")
        m.addAction(self.a_connect); m.addSeparator()
        m.addAction(self.a_read); m.addAction(self.a_burn)

        self.m_view = mb.addMenu("&View")

        m = mb.addMenu("&Tools")
        for label in ("&Interpolate Selection", "&Smooth Selection", "Sc&ale Selection…",
                      "Set &Axis Breakpoints…"):
            a = QAction(label, self, enabled=False); m.addAction(a)

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

        self.gauges = GaugePanel()
        d = QDockWidget("Gauges", self); d.setObjectName("dock_gauges")
        d.setWidget(self.gauges); d.setMinimumWidth(270)
        self.addDockWidget(Qt.RightDockWidgetArea, d); self.dock_gauges = d

        self.datalog = DatalogView()
        d = QDockWidget("Datalog", self); d.setObjectName("dock_log")
        d.setWidget(self.datalog); d.setMinimumHeight(180)
        self.addDockWidget(Qt.BottomDockWidgetArea, d); self.dock_log = d

        for dock, glyph in ((self.dock_nav, None), (self.dock_gauges, "gauge"), (self.dock_log, "log")):
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
        self.setCentralWidget(self.tabs)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.l_conn = QLabel(); self.l_tune = QLabel(); self.l_burn = QLabel()
        self.l_live = QLabel(); self.l_live.setMinimumWidth(240)
        sb.addWidget(self.l_conn); sb.addWidget(self.l_tune); sb.addWidget(self.l_burn)
        sb.addPermanentWidget(self.l_live)

    # ----------------------------------------------------------------- items
    def open_item(self, kind: str, key: str, label: str):
        if key in self.editors:
            self.tabs.setCurrentWidget(self.editors[key]); return
        if kind == "table":
            w = TableEditor(self.tune.tables[key], boost_psi=self.boost_psi)
            w.changed.connect(self._refresh_title)
            if self.conn.is_connected():
                ch = self.conn.channels()
                w.set_cursor(ch["rpm"], self._y_for(key, ch))
        elif kind == "settings":
            w = SettingsPage(key, self.tune.engine)
            w.changed.connect(self._engine_changed)
        elif kind == "page" and key == "datalog":
            self.dock_log.show(); self.dock_log.raise_(); return
        else:
            phase = {"torque_page": "Phase 4", "shift_cut": "Phase 4",
                     "shift_sched": "Phase 4"}.get(key, "Phase 2")
            w = PlaceholderPage(label, phase)
        self.editors[key] = w
        self.tabs.addTab(w, label); self.tabs.setCurrentWidget(w)

    def _close_tab(self, i):
        w = self.tabs.widget(i)
        for k, v in list(self.editors.items()):
            if v is w: del self.editors[k]
        self.tabs.removeTab(i); w.deleteLater()

    def _y_for(self, key, ch):
        return ch.get("map", 0.0) if key != "base_torque" else 0.9

    # ----------------------------------------------------------------- tune
    def new_tune(self):
        if not self._confirm_discard(): return
        self._replace_tune(default_tune())

    def open_tune(self):
        if not self._confirm_discard(): return
        path, _ = QFileDialog.getOpenFileName(self, "Open Tune", "", "Tune files (*.tune);;All files (*)")
        if path:
            try:
                self._replace_tune(Tune.load(path))
            except Exception as e:
                QMessageBox.critical(self, "Open Tune", f"Could not open tune:\n{e}")

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
        self.tune = tune
        while self.tabs.count(): self._close_tab(0)
        self.editors.clear()
        self.open_item("table", "ve", "VE Table")
        self._refresh_title()

    def _confirm_discard(self) -> bool:
        if not self.tune.dirty: return True
        r = QMessageBox.question(self, APP_NAME, "The tune has unsaved changes. Save first?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save: return bool(self.save_tune())
        return r == QMessageBox.Discard

    def _engine_changed(self):
        self.tune.engine_dirty = True; self._refresh_title()

    def _refresh_title(self, *_):
        name = self.tune.path.name if self.tune.path else self.tune.name
        star = "*" if self.tune.dirty else ""
        self.setWindowTitle(f"{name}{star} — {APP_NAME}")
        self.l_tune.setText(f"Tune: {name}{star}")
        self.l_burn.setText("<span style='color:#A00000'>Burn required</span>" if self.tune.dirty else "")

    # ----------------------------------------------------------------- ecu
    def toggle_connect(self):
        if self.conn.is_connected(): self.conn.disconnect_ecu()
        else: self.conn.connect_ecu()

    def burn(self):
        QMessageBox.information(self, "Burn", "Burning to the ECU arrives with the live connection (Phase 3).")

    def _on_conn_state(self, connected: bool):
        if connected:
            self.l_conn.setText(f"<span style='color:#2E9E44'>●</span> Connected: {self.conn.name}")
            self.a_connect.setText("&Disconnect")
        else:
            self.l_conn.setText("<span style='color:#9A9A9A'>●</span> Not connected")
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

    # ----------------------------------------------------------------- misc
    def _set_units(self, psi: bool):
        self.boost_psi = psi
        self.a_units_psi.setChecked(psi); self.a_units_kpa.setChecked(not psi)
        for key, w in self.editors.items():
            if isinstance(w, TableEditor):
                w.model.boost_psi = psi; w.model.headerDataChanged.emit(Qt.Vertical, 0, w.model.rowCount() - 1)
                w.info.setText(f"{w.table.x_name} × {w.model.y_header_title()}"
                               f"{'  —  ' + w.table.unit if w.table.unit else ''}")

    def _load_demo_log(self):
        log = generate(n=1200, seed=3)
        self.datalog.set_log(log["time_s"], {
            "rpm": log["rpm"], "boost": kpa_abs_to_boost_psi(log["map_kpa"]),
            "lambda": log["lam"], "torque": log["torque_ref"]})

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME}</b> {APP_VERSION}<br>Tuner application for a "
                          f"torque-structured engine controller.<br><br>Build: Phase 1 — "
                          f"layout, tables, demo connection.")

    def _default_dock_sizes(self):
        self.resizeDocks([self.dock_log], [330], Qt.Vertical)
        self.resizeDocks([self.dock_nav, self.dock_gauges], [200, 300], Qt.Horizontal)

    def _restore_layout(self) -> bool:
        if not self.persist_layout:
            return False
        s = QSettings(ORG_NAME, APP_NAME)
        ok = False
        if s.value("geometry"): ok = self.restoreGeometry(s.value("geometry")) or ok
        if s.value("state"): ok = self.restoreState(s.value("state")) or ok
        return ok

    def closeEvent(self, ev):
        if not self._confirm_discard():
            ev.ignore(); return
        if self.persist_layout:
            s = QSettings(ORG_NAME, APP_NAME)
            s.setValue("geometry", self.saveGeometry()); s.setValue("state", self.saveState())
        super().closeEvent(ev)
