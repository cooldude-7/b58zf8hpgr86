"""The tuner-to-ECU contract: identify, describe, write, burn, verify.

These run against the simulator, which is the reference implementation of
the protocol. A serial or CAN transport passes the same tests.
"""
import json

import numpy as np
import pytest

from tuner.core.connection import DemoConnection, ProtocolError
from tuner.core.tune import Tune, TuneError, default_tune


# ---- identity and layout --------------------------------------------------
def test_identify_reports_a_layout_hash(sim):
    ident = sim.identify()
    assert set(ident) >= {"ecu_id", "firmware", "protocol_version", "layout_hash"}
    assert int(ident["layout_hash"], 16) > 0


def test_describe_tables_covers_every_table(sim, tune):
    d = sim.describe_tables()
    assert set(d) == set(tune.tables)
    for key, desc in d.items():
        assert desc["n_x"] == tune.tables[key].n_x
        assert desc["n_y"] == tune.tables[key].n_y


def test_a_read_only_connection_refuses_the_write_side():
    c = DemoConnection()
    c.connect_ecu()
    assert not c.writable
    for call in (lambda: c.read_table("ve"),
                 lambda: c.write_cell("ve", 0, 0, 1.0),
                 lambda: c.burn()):
        with pytest.raises(ProtocolError):
            call()


def test_writes_are_refused_when_disconnected(sim):
    sim.disconnect_ecu()
    with pytest.raises(ProtocolError):
        sim.write_cell("ve", 0, 0, 1.0)


# ---- the ECU holds its own image ------------------------------------------
def test_editing_the_tuners_copy_does_not_reach_the_ecu(sim, tune):
    """The failure this prevents: every keystroke being instantly live in a
    running engine."""
    before = sim.read_table("ve")[0, 0]
    tune.tables["ve"].set(0, 0, 0.42)
    assert sim.read_table("ve")[0, 0] == before


def test_write_cell_reaches_the_ecu_and_is_echoed(sim, qapp):
    seen = []
    sim.write_acked.connect(lambda *a: seen.append(a))
    sim.write_cell("ve", 1, 2, 0.77)
    assert sim.read_table("ve")[1, 2] == pytest.approx(0.77)
    assert seen == [("ve", 1, 2, 0.77)]


# ---- the ECU refuses nonsense ---------------------------------------------
@pytest.mark.parametrize("value", [np.nan, np.inf, 99.0, -1.0])
def test_ecu_refuses_impossible_values(sim, value):
    with pytest.raises(ProtocolError):
        sim.write_cell("ve", 0, 0, float(value))


def test_ecu_refuses_writes_outside_its_layout(sim):
    with pytest.raises(ProtocolError):
        sim.write_cell("ve", 999, 0, 1.0)


def test_ecu_refuses_an_unknown_table(sim):
    with pytest.raises(ProtocolError):
        sim.write_cell("not_a_table", 0, 0, 1.0)


def test_ecu_refuses_a_table_of_the_wrong_shape(sim):
    with pytest.raises(ProtocolError):
        sim.write_table("ve", np.zeros((2, 2)))


# ---- burn -----------------------------------------------------------------
def test_burn_returns_crcs_matching_what_was_committed(sim):
    crcs = sim.burn()
    assert crcs == sim.tune.crcs()
    assert crcs == sim.flash.crcs()


def test_burn_crc_detects_a_difference(sim, tune):
    """The check that makes a burn trustworthy: if the ECU committed
    something other than what the tuner sent, the CRCs disagree."""
    for key, t in tune.tables.items():
        sim.write_table(key, t.values, t.x, t.y)
    committed = sim.burn()
    assert committed == tune.crcs()
    tune.tables["ve"].set(0, 0, 0.5)
    assert committed != tune.crcs()


def test_burn_survives_a_disconnect_reconnect(sim):
    crcs = sim.burn()
    sim.disconnect_ecu()
    sim.connect_ecu()
    assert sim.flash.crcs() == crcs


# ---- tune file integrity --------------------------------------------------
def test_a_tune_with_nan_cannot_be_written(tmp_path, tune):
    tune.tables["ve"].values[0, 0] = np.nan
    with pytest.raises((TuneError, ValueError)):
        tune.save(tmp_path / "t.tune")


def test_a_tune_file_containing_nan_is_refused(tmp_path, tune):
    p = tmp_path / "t.tune"
    tune.save(p)
    p.write_text(p.read_text().replace('"schema": 1', '"schema": 1').replace(
        str(tune.tables["ve"].values[0][0]), "NaN", 1))
    with pytest.raises(TuneError):
        Tune.load(p)


def test_a_tune_missing_a_required_table_is_refused(tmp_path, tune):
    p = tmp_path / "t.tune"
    tune.save(p)
    d = json.loads(p.read_text())
    del d["tables"]["knock"]
    p.write_text(json.dumps(d))
    with pytest.raises(TuneError):
        Tune.load(p)


def test_a_tune_with_a_short_chen_flynn_list_is_refused(tmp_path, tune):
    p = tmp_path / "t.tune"
    tune.save(p)
    d = json.loads(p.read_text())
    d["engine"]["chen_flynn"] = [0.4, 0.005]
    p.write_text(json.dumps(d))
    with pytest.raises(TuneError):
        Tune.load(p)


def test_a_tune_with_a_wild_engine_scalar_is_refused(tmp_path, tune):
    p = tmp_path / "t.tune"
    tune.save(p)
    d = json.loads(p.read_text())
    d["engine"]["rev_limit"] = 99000
    p.write_text(json.dumps(d))
    with pytest.raises(TuneError):
        Tune.load(p)


def test_a_tune_with_a_descending_axis_is_refused(tmp_path, tune):
    p = tmp_path / "t.tune"
    tune.save(p)
    d = json.loads(p.read_text())
    d["tables"]["ve"]["x"] = list(reversed(d["tables"]["ve"]["x"]))
    p.write_text(json.dumps(d))
    with pytest.raises(TuneError):
        Tune.load(p)


def test_save_load_round_trip_is_exact(tmp_path, tune):
    p = tmp_path / "t.tune"
    tune.save(p)
    back = Tune.load(p)
    for key, t in tune.tables.items():
        assert np.array_equal(t.values, back.tables[key].values)
        assert np.array_equal(t.x, back.tables[key].x)
    assert back.crcs() == tune.crcs()


def test_a_loaded_tune_starts_clean(tmp_path, tune):
    p = tmp_path / "t.tune"
    tune.save(p)
    back = Tune.load(p)
    assert not back.file_dirty


def test_the_default_tune_validates():
    default_tune().validate()
