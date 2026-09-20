"""The tuner as a tuner uses it: edit, send, burn, save, reopen.

These drive the real MainWindow. The data-layer tests prove the flags
are right; these prove the window actually consults them, which is where
the original data-loss bug lived.
"""
import numpy as np
import pytest

from tuner.core.tune import Tune, default_tune


@pytest.fixture
def win(qapp, tmp_path):
    from tuner.ui.main_window import MainWindow
    w = MainWindow(default_tune(), persist_layout=False)
    w.conn = w.sim
    w.conn.connect_ecu()
    w._on_conn_state(True)
    yield w
    w.conn.disconnect_ecu()
    # Closing with unsaved work raises a modal prompt, which is the
    # behaviour these tests exist to verify. Clear it here so the
    # teardown does not sit on a dialog nobody can answer; the prompt
    # itself is asserted in test_closing_with_unsaved_work_prompts.
    w.tune.mark_saved()
    w.close()


def edit(win, key="ve", j=0, i=0, value=0.77):
    win.tune.tables[key].set(j, i, value)
    win._on_table_changed(key)


# ---- the bug this all exists to prevent ----------------------------------
def test_burning_does_not_clear_the_unsaved_marker(win):
    """Edit, burn, and the window must still know the file is dirty. The
    original bug cleared one flag for both questions, so a burned edit
    could be closed away with no prompt."""
    edit(win)
    assert win.tune.file_dirty and win.tune.ecu_dirty
    win.burn()
    assert not win.tune.ecu_dirty, "burn did not reach the ECU"
    assert win.tune.file_dirty, "burn cleared the unsaved marker: edits can be lost"
    assert "*" in win.windowTitle()


def test_saving_does_not_clear_the_burn_marker(win, tmp_path):
    edit(win)
    win.tune.save(tmp_path / "t.tune")
    win._refresh_title()
    assert not win.tune.file_dirty
    assert win.tune.ecu_dirty, "saving to disk marked the ECU as up to date"


def test_the_status_bar_tracks_the_ecu_not_the_file(win, tmp_path):
    edit(win)
    win.tune.save(tmp_path / "t.tune")
    win._refresh_title()
    assert "Burn required" in win.l_burn.text()
    win.burn()
    assert "Burn required" not in win.l_burn.text()


def test_closing_with_unsaved_work_prompts(win, monkeypatch):
    """The end of the story. Edit, burn, close: the window must still ask,
    because the edits are in the ECU but not on disk. The original bug
    made this close silently and lose them."""
    from PySide6.QtWidgets import QMessageBox

    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.Discard)
    edit(win)
    win.burn()
    win.close()
    assert asked, "closing after a burn did not ask about unsaved changes"


def test_closing_with_everything_saved_does_not_prompt(win, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.Discard)
    edit(win)
    win.burn()
    win.tune.save(tmp_path / "t.tune")
    win.close()
    assert not asked, "prompted even though nothing was unsaved"


# ---- armed live write -----------------------------------------------------
def test_unarmed_edits_do_not_reach_the_running_engine(win):
    before = win.sim.read_table("ve")[0, 0]
    edit(win, value=0.61)
    assert win.sim.read_table("ve")[0, 0] == before
    assert win.tune.tables["ve"].state()[0, 0] == 0      # LOCAL


def test_armed_edits_go_straight_to_the_engine(win):
    win.set_armed(True)
    edit(win, value=0.61)
    assert win.sim.read_table("ve")[0, 0] == pytest.approx(0.61)
    assert win.tune.tables["ve"].state()[0, 0] == 1      # RAM
    assert "ARMED" in win.l_arm.text()


def test_disconnecting_disarms(win):
    win.set_armed(True)
    win.conn.disconnect_ecu()
    win._on_conn_state(False)
    assert not win.armed
    assert win.l_arm.text() == ""


def test_burn_sends_local_edits_first(win):
    """An unarmed edit is LOCAL. Burning must push it before committing,
    or the ECU commits an image the tuner is not showing."""
    edit(win, value=0.71)
    assert win.sim.read_table("ve")[0, 0] != pytest.approx(0.71)
    win.burn()
    assert win.sim.flash.tables["ve"].values[0, 0] == pytest.approx(0.71)
    assert win.tune.tables["ve"].state()[0, 0] == 2      # FLASH


# ---- read back ------------------------------------------------------------
def test_reading_from_the_ecu_replaces_the_editor_image(win, tmp_path):
    win.burn()
    win.sim.write_cell("ve", 0, 0, 0.55)
    win.sim.burn()
    win.tune.path = tmp_path / "t.tune"
    win.tune.save(win.tune.path)
    win.read_from_ecu()
    assert win.tune.tables["ve"].values[0, 0] == pytest.approx(0.55)
    assert not win.tune.ecu_dirty


# ---- loading a broken tune ------------------------------------------------
def test_a_tune_missing_a_table_is_refused_before_it_is_swapped_in(win, tmp_path):
    import json
    p = tmp_path / "bad.tune"
    win.tune.save(p)
    d = json.loads(p.read_text())
    del d["tables"]["knock"]          # a core table: must be refused
    p.write_text(json.dumps(d))
    good = win.tune.tables["ve"].values.copy()
    with pytest.raises(Exception):
        win._replace_tune(Tune.load(p))
    assert np.array_equal(win.tune.tables["ve"].values, good)
    win.sim._step()          # the engine is still running on a valid tune


def test_the_simulator_keeps_its_own_image_of_the_tune(win):
    assert win.sim.tune is not win.tune
    win.tune.tables["mbt"].values[:] += 5.0
    assert not np.allclose(win.sim.tune.tables["mbt"].values,
                           win.tune.tables["mbt"].values)


# ---- the status bar -------------------------------------------------------
@pytest.mark.parametrize("width", [1400, 1100, 900])
def test_status_labels_never_overlap_or_clip(qapp, width):
    """Labels that start empty and gain text later used to be drawn on
    top of each other, because a status bar does not re-lay-out when a
    child's size hint changes."""
    from tuner.ui.main_window import MainWindow

    w = MainWindow(default_tune(), persist_layout=False)
    w.resize(width, 860)
    w.show()
    w.conn = w.sim
    w.conn.connect_ecu()
    w._on_conn_state(True)
    w.set_armed(True)
    w.tune.tables["ve"].set(0, 0, 0.9)
    w._on_table_changed("ve")
    for _ in range(3):
        qapp.processEvents()
    try:
        right = -1
        for label in (w.l_conn, w.l_tune, w.l_burn, w.l_arm, w.l_hint):
            g = label.geometry()
            assert g.x() >= right, f"{label.text()!r} overlaps its neighbour"
            if label is not w.l_hint:
                assert g.width() >= label.sizeHint().width(), \
                    f"{label.text()!r} is clipped"
            right = g.x() + g.width()
    finally:
        w.conn.disconnect_ecu()
        w.tune.mark_saved()
        w.close()


def test_wide_open_throttle_does_not_trip_the_monitor(sim):
    """A progressive pedal makes near-full torque well before full
    travel. A monitor that assumes a straight ramp limps the car on
    every hard pull, which is worse than no monitor at all."""
    sim.pedal = 0.8
    for _ in range(900):
        sim._step()
    ch = sim.channels()
    assert ch["limp_level"] == 0, (
        f"limped at 80% pedal: torque {ch['torque']:.0f} vs permissible "
        f"{ch['torque_permissible']:.0f}, fault {ch['fault_code']:.0f}")
    assert ch["torque"] > 150.0, f"only made {ch['torque']:.0f} Nm at 80% pedal"


def test_disarming_something_never_armed_says_nothing(qapp):
    """A temporary status message covers the permanent labels while it
    shows. Announcing a disarm that never happened put it there at every
    start-up, on top of the connection and tune names."""
    from tuner.ui.main_window import MainWindow

    w = MainWindow(default_tune(), persist_layout=False)
    try:
        w.set_armed(False)
        assert w.statusBar().currentMessage() == ""
        w.conn = w.sim
        w.conn.connect_ecu()
        w._on_conn_state(True)
        assert w.statusBar().currentMessage() == ""
        w.set_armed(True)
        assert "armed" in w.statusBar().currentMessage().lower()
    finally:
        w.conn.disconnect_ecu()
        w.tune.mark_saved()
        w.close()


# ---- regressions: the app must explain itself ----------------------------
def test_an_unarmed_edit_is_marked_differently_from_a_sent_one(win):
    """An edit that has not reached the engine used to look identical to
    one that had, which made a correctly working tuner look like a dead
    simulator."""
    from tuner.core.table import Table

    t = win.tune.tables["ve"]
    assert t.state()[0, 0] == Table.FLASH
    edit(win, value=0.61)
    assert t.state()[0, 0] == Table.LOCAL
    win.set_armed(True)
    edit(win, j=0, i=1, value=0.62)
    assert t.state()[0, 1] == Table.RAM
    win.burn()
    assert (t.state() == Table.FLASH).all()


def test_the_live_write_state_is_always_visible_when_connected(win):
    """Blank is the wrong way to say off. Without this the tuner has no
    way to know why edits are not reaching the engine."""
    win.set_armed(False)
    assert win.l_arm.text(), "no indication that live write is off"
    assert "off" in win.l_arm.text().lower()
    win.set_armed(True)
    assert "armed" in win.l_arm.text().lower()


def test_a_connection_error_is_reported_not_swallowed(win, monkeypatch):
    """The simulator stops its timer when a step raises. If nothing is
    listening, the screen looks exactly like an idling engine."""
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a[2] if len(a) > 2 else a))
    win.conn.error.emit("Simulation stopped: something went wrong")
    assert shown, "a connection error reached nobody"
    assert "stopped" in win.statusBar().currentMessage().lower()


def test_a_tune_from_an_older_version_still_loads(tmp_path, tune):
    """Adding required scalars must not make every saved tune
    disposable. They are filled from the defaults and named."""
    import json

    from tuner.core.tune import Tune

    p = tmp_path / "old.tune"
    tune.save(p)
    d = json.loads(p.read_text())
    for k in ("boost_max_kpa", "overboost_cut_kpa", "max_cut_retard",
              "trigger_teeth", "dwell_ms"):
        d["engine"].pop(k, None)
    p.write_text(json.dumps(d))

    back = Tune.load(p)
    assert "boost_max_kpa" in back.upgraded
    assert back.engine["boost_max_kpa"] > 0
    assert back.file_dirty, "the upgrade was not flagged for saving"


def test_a_genuinely_broken_tune_is_still_refused(tmp_path, tune):
    import json

    from tuner.core.tune import Tune, TuneError

    p = tmp_path / "bad.tune"
    tune.save(p)
    d = json.loads(p.read_text())
    d["engine"]["rev_limit"] = 99000
    p.write_text(json.dumps(d))
    with pytest.raises(TuneError):
        Tune.load(p)


def test_every_navigator_item_opens_something(win):
    """No dead ends. An item that opens a "not available in this build"
    page is worse than no item at all in software somebody has paid for,
    so the tree and the thing that handles it must not drift apart."""
    from tuner.ui.nav_tree import TREE

    for _group, children in TREE:
        for label, kind, key in children:
            assert kind in ("course", "settings", "table", "page"), (label, kind)
            win.open_item(kind, key, label)
            if kind == "page" and key in ("datalog", "simdock"):
                dock = win.dock_log if key == "datalog" else win.dock_sim
                # isHidden, not isVisible: the fixture never shows the
                # window, so nothing inside it is on screen either way
                assert not dock.isHidden(), label   # these raise a dock, not a tab
            else:
                assert key in win.editors, label
                assert win.tabs.currentWidget() is win.editors[key], label


def test_no_placeholder_pages_remain(win):
    """The class is gone; this fails loudly if it comes back rather than
    quietly shipping a stub behind a navigator item."""
    import tuner.ui.settings_page as sp

    assert not hasattr(sp, "PlaceholderPage")


def test_driving_records_which_cells_were_visited(win):
    """Coverage answers "do I have data here", which is what makes a
    correction honest: you change the cells your pull actually touched."""
    ed = win.editors["ve"]
    ed.clear_coverage()
    assert not ed.coverage

    for k in range(400):                      # a pull, wound on from idle
        win.sim.pedal = min(0.15 + k / 250.0, 1.0)
        win.sim._step()
        if k % 2 == 0:
            win._on_channels(win.sim.channels())

    assert len(ed.coverage) > 3, "a pull should cross several cells"
    for (j, i), n in ed.coverage.items():
        assert 0 <= j < ed.table.n_y and 0 <= i < ed.table.n_x
        assert n > 0
    # the whole map is never covered by one pull, which is the point
    assert len(ed.coverage) < ed.table.n_y * ed.table.n_x


def test_coverage_can_be_cleared_on_every_table_at_once(win):
    """What THIS pull touched is the useful question, so it needs a clean
    sheet between pulls."""
    win.open_item("table", "mbt", "MBT Spark")
    for k in range(60):
        win.sim.pedal = 0.5
        win.sim._step()
        win._on_channels(win.sim.channels())
    assert win.editors["ve"].coverage and win.editors["mbt"].coverage

    win.clear_coverage()
    assert not win.editors["ve"].coverage
    assert not win.editors["mbt"].coverage


def test_coverage_and_findings_are_different_facts(win):
    """Coverage says where the engine has been. Findings say what is
    wrong. A cell can have either, both or neither, and they are drawn in
    different corners so they never have to compete."""
    ed = win.editors["ve"]
    assert ed.coverage is not ed.findings
    ed.clear_coverage()
    ed.set_findings([])
    assert not ed.coverage and not ed.findings
