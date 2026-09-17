"""The tuner talking to the real firmware over the real protocol.

Everything else in the test suite exercises the tuner against a Python
simulator. This one runs the C firmware as a subprocess and speaks to it
down a pipe, so the bytes crossing the boundary are the bytes that will
cross a USB cable. It is the only test that can catch the two framing
implementations drifting apart.
"""
import shutil
import struct
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from tuner.core.connection import ProtocolError
from tuner.core.link import (CMD_IDENTIFY, FrameReader, SerialConnection,
                             crc16, expected_crc, frame)
from tuner.core.tune import default_tune

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "fw"
BUILD = ROOT / "build" / "fw"

pytestmark = pytest.mark.skipif(
    shutil.which("cmake") is None or shutil.which("cc") is None,
    reason="no C toolchain available")


def write_layout(path: Path, tune):
    """The calibration the ECU boots with, as a flat text file. Stands in
    for the image a real ECU would have been flashed with."""
    lines = [f"tables {len(tune.tables)}"]
    for key, t in tune.tables.items():
        lines.append(f"table {key} {t.n_x} {t.n_y} {t.lo:.9g} {t.hi:.9g}")
        lines.append("x " + " ".join(f"{v:.9g}" for v in t.x))
        lines.append("y " + " ".join(f"{v:.9g}" for v in t.y))
        for j in range(t.n_y):
            lines.append("v " + " ".join(f"{v:.9g}" for v in t.values[j]))
    path.write_text("\n".join(lines) + "\n")


class PipeStream:
    """A subprocess's stdin and stdout as one read/write stream."""

    def __init__(self, proc):
        self.proc = proc

    def write(self, data):
        self.proc.stdin.write(data)

    def flush(self):
        self.proc.stdin.flush()

    def read(self, n):
        return self.proc.stdout.read(n)


@pytest.fixture(scope="session")
def ecu_binary():
    subprocess.run(["cmake", "-S", str(FW), "-B", str(BUILD),
                    "-DCMAKE_BUILD_TYPE=Release"], check=True,
                   capture_output=True)
    subprocess.run(["cmake", "--build", str(BUILD), "--target", "ecu_host",
                    "-j", "4"], check=True, capture_output=True)
    exe = BUILD / "ecu_host"
    assert exe.exists(), "ecu_host was not built"
    return exe


@pytest.fixture
def ecu(ecu_binary, tmp_path, tune):
    layout = tmp_path / "cal.txt"
    write_layout(layout, tune)
    proc = subprocess.Popen([str(ecu_binary), str(layout)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            bufsize=0)
    conn = SerialConnection(PipeStream(proc))
    try:
        conn.connect_ecu()
        yield conn
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---- framing agrees on both sides ----------------------------------------
def test_framing_round_trips_in_python():
    f = frame(0x42, b"hello")
    got = list(FrameReader().feed(f))
    assert got == [(0x42, b"hello")]


def test_a_reader_joined_mid_frame_recovers():
    r = FrameReader()
    f = frame(CMD_IDENTIFY)
    assert list(r.feed(b"\x11\x22\x33" + f)) == [(CMD_IDENTIFY, b"")]
    assert r.dropped == 3


def test_a_corrupted_frame_is_not_yielded():
    r = FrameReader()
    f = bytearray(frame(CMD_IDENTIFY, b"abc"))
    f[-1] ^= 0xFF
    assert list(r.feed(bytes(f))) == []
    assert r.bad_crc == 1


# ---- against the real firmware -------------------------------------------
def test_identify(ecu):
    ident = ecu.identify()
    assert ident["protocol_version"] == 1
    assert ident["ecu_id"] == "TORQUETUNE-FW"
    assert int(ident["layout_hash"], 16) > 0


def test_layout_matches_the_tune(ecu, tune):
    desc = ecu.describe_tables()
    assert set(desc) == set(tune.tables)
    for key, t in tune.tables.items():
        assert desc[key]["n_x"] == t.n_x
        assert desc[key]["n_y"] == t.n_y
        assert desc[key]["lo"] == pytest.approx(t.lo, rel=1e-6)


def test_read_table_returns_what_was_flashed(ecu, tune):
    got = ecu.read_table("ve")
    assert got.shape == tune.tables["ve"].values.shape
    assert np.allclose(got, tune.tables["ve"].values, atol=1e-6)


def test_write_cell_is_echoed_and_readable(ecu):
    ecu.write_cell("ve", 2, 3, 1.234)
    assert ecu.read_table("ve")[2, 3] == pytest.approx(1.234, abs=1e-6)


def test_the_ecu_refuses_a_value_outside_its_bounds(ecu):
    with pytest.raises(ProtocolError):
        ecu.write_cell("ve", 0, 0, 99.0)


def test_the_ecu_refuses_nan(ecu):
    with pytest.raises(ProtocolError):
        ecu.write_cell("ve", 0, 0, float("nan"))


def test_the_ecu_refuses_an_index_outside_its_layout(ecu):
    with pytest.raises(ProtocolError):
        ecu.write_cell("ve", 99, 0, 1.0)


def test_the_ecu_refuses_an_unknown_table(ecu):
    with pytest.raises(ProtocolError):
        ecu.write_cell("not_a_table", 0, 0, 1.0)


def test_the_ecu_refuses_a_tune_of_the_wrong_shape(ecu):
    with pytest.raises(ProtocolError):
        ecu.write_table("ve", np.zeros((2, 2)))


def test_a_refused_table_write_changes_nothing(ecu):
    before = ecu.read_table("ve").copy()
    bad = before.copy()
    bad[-1, -1] = 50.0                       # out of bounds for VE
    with pytest.raises(ProtocolError):
        ecu.write_table("ve", bad)
    assert np.array_equal(ecu.read_table("ve"), before)


def test_write_table_round_trips(ecu, tune):
    t = tune.tables["ve"]
    new = np.clip(t.values * 0.93, t.lo, t.hi)
    ecu.write_table("ve", new, t.x, t.y)
    assert np.allclose(ecu.read_table("ve"), new, atol=1e-6)


# ---- the burn verification that makes any of this trustworthy ------------
def test_the_crc_the_ecu_reports_matches_the_one_the_tuner_computes(ecu, tune):
    """The whole point of the burn check. If these two numbers are
    computed differently, a corrupted burn looks identical to a good
    one."""
    for key, t in tune.tables.items():
        ecu.write_table(key, t.values, t.x, t.y)
    committed = ecu.burn()
    for key, t in tune.tables.items():
        assert committed[key] == t.crc(), f"{key} CRC disagrees"


def test_the_crc_notices_a_single_changed_cell(ecu, tune):
    t = tune.tables["ve"]
    ecu.write_table("ve", t.values, t.x, t.y)
    before = ecu.table_crc("ve")
    ecu.write_cell("ve", 0, 0, float(t.values[0, 0]) + 0.01)
    assert ecu.table_crc("ve") != before


def test_burn_survives_and_matches_after_more_edits(ecu, tune):
    t = tune.tables["ve"]
    ecu.write_table("ve", t.values, t.x, t.y)
    first = ecu.burn()["ve"]
    ecu.write_cell("ve", 1, 1, 0.5)
    assert ecu.table_crc("ve") != first
    second = ecu.burn()["ve"]
    assert second == ecu.table_crc("ve")


def test_expected_crc_helper_agrees_with_the_table(tune):
    t = tune.tables["mbt"]
    assert expected_crc("mbt", t.x, t.y, t.values) == t.crc()


# ---- the link misbehaving -------------------------------------------------
def test_garbage_on_the_wire_does_not_kill_the_link(ecu):
    ecu.stream.write(b"\x00\x11\x22\x33\x44\x55\x66\x77")
    ecu.stream.flush()
    assert ecu.identify()["protocol_version"] == 1


def test_a_corrupted_frame_gets_no_reply_and_the_link_recovers(ecu):
    bad = bytearray(frame(CMD_IDENTIFY))
    bad[-1] ^= 0xFF
    ecu.stream.write(bytes(bad))
    ecu.stream.flush()
    time.sleep(0.05)
    assert ecu.identify()["ecu_id"] == "TORQUETUNE-FW"


def test_a_dead_ecu_raises_rather_than_hanging(ecu_binary, tmp_path, tune):
    layout = tmp_path / "cal.txt"
    write_layout(layout, tune)
    proc = subprocess.Popen([str(ecu_binary), str(layout)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            bufsize=0)
    conn = SerialConnection(PipeStream(proc))
    conn.connect_ecu()
    proc.kill()
    proc.wait()
    with pytest.raises(ProtocolError):
        conn.identify()
