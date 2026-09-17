"""Table construction, validation, lookup and the three-state cell model."""
import numpy as np
import pytest

from tuner.core.table import Table, TableError
from tuner.core import tableops as ops


def make(lo=-100.0, hi=100.0, values=None):
    v = np.zeros((3, 4)) if values is None else np.asarray(values, dtype=float)
    return Table("t", "T", "RPM", "rpm", "MAP", "kPa",
                 [1000, 2000, 3000, 4000], [50, 100, 150], v, lo=lo, hi=hi)


# ---- construction refuses what an ECU cannot run --------------------------
def test_descending_axis_is_refused():
    with pytest.raises(TableError):
        Table("t", "T", "a", "", "b", "", [3, 2, 1], [1, 2], np.zeros((2, 3)))


def test_duplicate_breakpoints_are_refused():
    with pytest.raises(TableError):
        Table("t", "T", "a", "", "b", "", [1, 2, 2], [1, 2], np.zeros((2, 3)))


def test_single_point_axis_is_refused():
    with pytest.raises(TableError):
        Table("t", "T", "a", "", "b", "", [1], [1, 2], np.zeros((2, 1)))


def test_shape_mismatch_is_refused():
    with pytest.raises(TableError):
        Table("t", "T", "a", "", "b", "", [1, 2, 3], [1, 2], np.zeros((3, 2)))


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_values_are_refused(bad):
    v = np.zeros((3, 4)); v[1, 1] = bad
    with pytest.raises(TableError):
        make(values=v)


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite_axis_is_refused(bad):
    with pytest.raises(TableError):
        Table("t", "T", "a", "", "b", "", [1, 2, bad], [1, 2], np.zeros((2, 3)))


def test_values_outside_bounds_are_refused():
    with pytest.raises(TableError):
        make(lo=0.0, hi=1.0, values=np.full((3, 4), 5.0))


# ---- set ------------------------------------------------------------------
def test_set_refuses_out_of_bounds():
    t = make(lo=0.0, hi=10.0)
    with pytest.raises(TableError):
        t.set(0, 0, 11.0)
    assert t.values[0, 0] == 0.0


def test_set_refuses_nan():
    t = make()
    with pytest.raises(TableError):
        t.set(0, 0, np.nan)


def test_accepts_matches_set():
    t = make(lo=0.0, hi=10.0)
    assert t.accepts(5.0) and not t.accepts(11.0) and not t.accepts(np.nan)


# ---- lookup ---------------------------------------------------------------
def test_lookup_returns_breakpoint_values_exactly():
    v = np.arange(12, dtype=float).reshape(3, 4)
    t = make(values=v)
    for j, y in enumerate(t.y):
        for i, x in enumerate(t.x):
            assert t.lookup(x, y) == pytest.approx(v[j, i])


def test_lookup_clamps_below_and_above_both_axes():
    v = np.arange(12, dtype=float).reshape(3, 4)
    t = make(values=v)
    assert t.lookup(-1e6, -1e6) == pytest.approx(v[0, 0])
    assert t.lookup(1e6, 1e6) == pytest.approx(v[-1, -1])
    assert t.lookup(-1e6, 1e6) == pytest.approx(v[-1, 0])


def test_lookup_is_continuous_across_a_breakpoint():
    v = np.arange(12, dtype=float).reshape(3, 4)
    t = make(values=v)
    eps = 1e-7
    assert t.lookup(2000 - eps, 100) == pytest.approx(t.lookup(2000 + eps, 100), abs=1e-5)


def test_lookup_midpoint_is_the_average():
    t = make(values=np.array([[0, 10, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], dtype=float))
    assert t.lookup(1500, 50) == pytest.approx(5.0)


def test_lookup_of_nan_does_not_propagate():
    """A dead sensor must not turn every table lookup into NaN."""
    t = make(values=np.ones((3, 4)))
    assert np.isfinite(t.lookup(np.nan, np.nan))


# ---- the three cell states ------------------------------------------------
def test_cell_state_progresses_local_ram_flash():
    t = make()
    assert (t.state() == Table.FLASH).all()
    t.set(0, 0, 1.0)
    assert t.state()[0, 0] == Table.LOCAL
    t.mark_sent()
    assert t.state()[0, 0] == Table.RAM
    t.mark_burned()
    assert t.state()[0, 0] == Table.FLASH


def test_burning_does_not_clear_unsaved():
    """The bug this whole split exists to prevent: burn used to clear the
    file-dirty flag, so edits could be burned and then discarded on close
    with no prompt."""
    t = make()
    t.set(0, 0, 1.0)
    t.mark_burned()
    assert not t.dirty.any()
    assert t.unsaved.any()


def test_saving_does_not_clear_unburned():
    t = make()
    t.set(0, 0, 1.0)
    t.mark_saved()
    assert not t.unsaved.any()
    assert t.dirty.any()


def test_axis_change_invalidates_every_cell():
    t = make()
    t.mark_burned(); t.mark_saved()
    t.invalidate_baselines()
    assert t.dirty.all() and t.unsaved.all()


# ---- crc ------------------------------------------------------------------
def test_crc_changes_with_any_value():
    t = make()
    before = t.crc()
    t.set(1, 1, 1.0)
    assert t.crc() != before


def test_crc_changes_with_the_axes():
    t = make()
    before = t.crc()
    t.x = np.array([1000.0, 2000.0, 3000.0, 5000.0])
    assert t.crc() != before


def test_crc_is_stable_for_equal_tables():
    assert make().crc() == make().crc()


# ---- persistence ----------------------------------------------------------
def test_dict_round_trip_keeps_values_and_bounds():
    t = make(lo=-5.0, hi=5.0, values=np.ones((3, 4)))
    t2 = Table.from_dict(t.to_dict())
    assert np.array_equal(t.values, t2.values)
    assert (t2.lo, t2.hi) == (-5.0, 5.0)


def test_from_dict_reports_missing_keys():
    d = make().to_dict()
    del d["values"]
    with pytest.raises(TableError):
        Table.from_dict(d)


# ---- clipboard ------------------------------------------------------------
@pytest.mark.parametrize("text", ["1 nan", "1 inf", "1 -inf", "1 1e400"])
def test_clipboard_rejects_non_finite(text):
    assert ops.from_tsv(text) is None


def test_clipboard_rejects_ragged_blocks():
    assert ops.from_tsv("1 2 3\n4 5") is None


def test_clipboard_round_trip():
    v = np.arange(12, dtype=float).reshape(3, 4)
    text = ops.to_tsv(v, 0, 2, 0, 3, "{:.3f}")
    back = ops.from_tsv(text)
    assert np.allclose(back[::-1], v)
