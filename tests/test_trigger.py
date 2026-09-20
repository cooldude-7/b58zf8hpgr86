"""tools/trigger, against engines whose geometry we know exactly.

No real B48 capture exists yet, so these are synthetic. That is weaker
evidence than a scope on the actual engine and it should not be mistaken
for the real thing -- but the failures it catches are the ones that
matter here, which are all about misreading a signal rather than about
the signal being exotic.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tools.trigger import fit_cam, fit_wheel, read_csv, synth_capture
from tools.trigger.emit import emit_c
from tools.trigger.synth import as_csv

REPO = Path(__file__).resolve().parents[1]


def _fit(edges):
    crank = [t for t, _ in edges["crank"]]
    return crank, fit_wheel(crank)


def test_recovers_a_60_2_wheel():
    edges, truth = synth_capture(cycles=10)
    _, wheel = _fit(edges)
    assert wheel.teeth_total == truth.teeth_total
    assert wheel.teeth_missing == truth.teeth_missing


def test_recovers_a_different_wheel_so_it_is_not_hard_coded():
    edges, truth = synth_capture(teeth_total=36, teeth_missing=1, cycles=12)
    _, wheel = _fit(edges)
    assert (wheel.teeth_total, wheel.teeth_missing) == (36, 1)


def test_recovers_the_cam_pattern_spacings():
    edges, _ = synth_capture(cycles=12,
                             cam_angles={"cam_in": [181.0, 361.0, 581.0]})
    crank, wheel = _fit(edges)
    cam = fit_cam("cam_in", edges["cam_in"], crank, wheel)
    assert cam.n_edges == 3
    assert cam.intervals_deg == pytest.approx([180.0, 220.0, 320.0], abs=2.0)


def test_survives_the_engine_accelerating():
    """A capture taken on a free rev, not at a convenient steady speed."""
    edges, _ = synth_capture(rpm_start=800.0, rpm_end=4500.0, cycles=20)
    crank, wheel = _fit(edges)
    assert (wheel.teeth_total, wheel.teeth_missing) == (60, 2)
    assert wheel.rpm_min < 1200.0 < wheel.rpm_max
    cam = fit_cam("cam_in", edges["cam_in"], crank, wheel)
    assert cam.intervals_deg == pytest.approx([180.0, 220.0, 320.0], abs=4.0)


def test_cam_pattern_is_unchanged_by_where_the_phaser_sits():
    """The whole premise of the decoder: a phaser moves every feature by
    the same amount, so the spacings between them do not move at all."""
    parked, _ = synth_capture(cycles=12)
    moved, _ = synth_capture(cycles=12, cam_advance={"cam_in": 55.0})

    ck_a, w_a = _fit(parked)
    ck_b, w_b = _fit(moved)
    a = fit_cam("cam_in", parked["cam_in"], ck_a, w_a)
    b = fit_cam("cam_in", moved["cam_in"], ck_b, w_b)
    assert b.intervals_deg == pytest.approx(a.intervals_deg, abs=2.0)


def test_survives_a_phaser_moving_during_the_capture():
    edges, _ = synth_capture(cycles=16, cam_slew_dps={"cam_in": 120.0})
    crank, wheel = _fit(edges)
    cam = fit_cam("cam_in", edges["cam_in"], crank, wheel)
    assert cam.n_edges == 3


def test_survives_timing_jitter():
    edges, _ = synth_capture(cycles=14, jitter_s=8e-6)
    crank, wheel = _fit(edges)
    assert (wheel.teeth_total, wheel.teeth_missing) == (60, 2)
    assert wheel.jitter_deg > 0.0


def test_dropped_crank_edges_are_reported_not_silently_absorbed():
    edges, _ = synth_capture(cycles=14, drop_crank=(120, 121, 300))
    _, wheel = _fit(edges)
    assert wheel.notes, "a capture missing teeth produced no warning"
    assert "tooth count" in wheel.notes[0]


def test_a_capture_too_short_to_trust_is_refused():
    edges, _ = synth_capture(cycles=1)
    crank = [t for t, _ in edges["crank"]][:20]
    with pytest.raises(ValueError, match="crank edges"):
        fit_wheel(crank)


def test_a_channel_that_is_not_a_cam_is_rejected():
    edges, _ = synth_capture(cycles=10)
    crank, wheel = _fit(edges)
    # Feed it the crank as if it were a cam: no 720-degree pattern.
    with pytest.raises(ValueError, match="repeating pattern"):
        fit_cam("not_a_cam", [(t, True) for t in crank], crank, wheel)


def test_csv_round_trip():
    edges, _ = synth_capture(cycles=8)
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "cap.csv")
        as_csv(edges, path)
        cap = read_csv(path)
        crank = sorted(cap.get("crank").rising)
        wheel = fit_wheel(crank)
        assert (wheel.teeth_total, wheel.teeth_missing) == (60, 2)


def test_the_emitted_c_actually_compiles_against_the_firmware():
    """The output is C that has to build, not a plausible-looking blob."""
    cc = shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler")

    edges, _ = synth_capture(cycles=12)
    crank, wheel = _fit(edges)
    cam = fit_cam("cam_in", edges["cam_in"], crank, wheel)
    src = emit_c(wheel, [(cam, 181.0, -8.0, 70.0)],
                 gap_to_tdc_deg=114.0, provenance="pytest synthetic")

    with tempfile.TemporaryDirectory() as d:
        c = Path(d) / "decoder_cal.c"
        c.write_text(src)
        r = subprocess.run(
            [cc, "-c", "-std=c11", "-Wall", "-Wextra", "-Werror",
             f"-I{REPO / 'fw' / 'include'}", f"-I{REPO / 'fw' / 'hal'}",
             str(c), "-o", str(Path(d) / "out.o")],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"generated C did not compile:\n{r.stderr}"


def test_emitted_config_is_marked_as_measured():
    edges, _ = synth_capture(cycles=10)
    crank, wheel = _fit(edges)
    cam = fit_cam("cam_in", edges["cam_in"], crank, wheel)
    src = emit_c(wheel, [(cam, 181.0, -8.0, 70.0)], gap_to_tdc_deg=114.0)
    assert "c.measured = true;" in src, (
        "a generated config must be distinguishable from the provisional "
        "one inside the binary"
    )
