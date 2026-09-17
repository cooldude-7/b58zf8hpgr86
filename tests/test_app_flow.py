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
    del d["tables"]["knock"]
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
