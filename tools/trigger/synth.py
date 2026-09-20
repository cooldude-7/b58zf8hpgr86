"""Synthetic captures with known ground truth.

No real B48 capture exists yet, so the tool is tested against engines
that were generated rather than measured. That is weaker evidence than a
real capture and the tests say so -- but it does catch the failures that
actually matter here, which are all about the fit mis-reading a signal
rather than about the signal being exotic: a phaser that moves during the
capture, a dropped edge, cranking speed that wanders, and timing jitter.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class SynthTruth:
    teeth_total: int
    teeth_missing: int
    gap_to_tdc_deg: float
    cam_angles: dict[str, list[float]]   # crank degrees in the 720 frame
    cam_advance: dict[str, float] = field(default_factory=dict)


def synth_capture(
    *,
    teeth_total: int = 60,
    teeth_missing: int = 2,
    gap_to_tdc_deg: float = 114.0,
    cam_angles: dict[str, list[float]] | None = None,
    cam_advance: dict[str, float] | None = None,
    cam_slew_dps: dict[str, float] | None = None,
    cam_travel: dict[str, tuple[float, float]] | None = None,
    rpm_start: float = 900.0,
    rpm_end: float | None = None,
    cycles: int = 8,
    jitter_s: float = 0.0,
    drop_crank: tuple[int, ...] = (),
    seed: int = 1,
) -> tuple[dict[str, list[tuple[float, bool]]], SynthTruth]:
    """Generate crank and cam edge lists for a known engine.

    Returns ``{channel: [(time_s, rising), ...]}`` plus the truth it was
    built from, so a test can assert the fit recovers it.
    """
    rng = random.Random(seed)
    if cam_angles is None:
        cam_angles = {"cam_in": [181.0, 361.0, 581.0]}
    advance = dict(cam_advance or {})
    slew = dict(cam_slew_dps or {})
    # A phaser has a mechanical stop and reaches it. Letting a simulated
    # one slew indefinitely produces a capture no engine can make, and
    # then "the tool cannot read it" says nothing about the tool.
    travel = dict(cam_travel or {})
    rpm_end = rpm_start if rpm_end is None else rpm_end

    deg_per_tooth = 360.0 / teeth_total
    present = teeth_total - teeth_missing
    total_deg = cycles * 720.0

    # Walk crank angle in small steps so cam crossings can be placed
    # accurately in time even while the speed is changing.
    step = deg_per_tooth / 8.0
    t = 0.0
    ang = 0.0
    crank: list[tuple[float, bool]] = []
    cams: dict[str, list[tuple[float, bool]]] = {k: [] for k in cam_angles}
    emitted = 0

    while ang < total_deg:
        frac = ang / total_deg
        rpm = rpm_start + (rpm_end - rpm_start) * frac
        dt = step / (rpm * 6.0)

        nxt = ang + step
        # crank teeth
        rel0 = (ang - gap_to_tdc_deg) % 360.0
        rel1 = (nxt - gap_to_tdc_deg) % 360.0
        for k in range(teeth_total):
            at = k * deg_per_tooth
            if k >= present:
                continue
            crossed = (rel0 < at <= rel1) if rel1 >= rel0 else (at > rel0 or at <= rel1)
            if crossed:
                emitted += 1
                if emitted in drop_crank:
                    continue
                jt = rng.gauss(0.0, jitter_s) if jitter_s else 0.0
                crank.append((t + jt, True))

        # cam features, displaced by whatever the phaser is doing
        for name, angles in cam_angles.items():
            adv = advance.get(name, 0.0) + slew.get(name, 0.0) * t
            lo, hi = travel.get(name, (-8.0, 70.0))
            adv = min(max(adv, lo), hi)
            c0, c1 = ang % 720.0, nxt % 720.0
            for a in angles:
                at = (a - adv) % 720.0
                crossed = (c0 < at <= c1) if c1 >= c0 else (at > c0 or at <= c1)
                if crossed:
                    jt = rng.gauss(0.0, jitter_s) if jitter_s else 0.0
                    cams[name].append((t + jt, True))
        ang = nxt
        t += dt

    out: dict[str, list[tuple[float, bool]]] = {"crank": sorted(crank)}
    for k, v in cams.items():
        out[k] = sorted(v)
    truth = SynthTruth(
        teeth_total=teeth_total,
        teeth_missing=teeth_missing,
        gap_to_tdc_deg=gap_to_tdc_deg,
        cam_angles=dict(cam_angles),
        cam_advance=advance,
    )
    return out, truth


def as_csv(edges: dict[str, list[tuple[float, bool]]], path: str,
           *, rate_hz: float = 2.0e6) -> None:
    """Write a logic-style CSV, the way an analyser would export it."""
    names = list(edges)
    times = sorted({t for ch in edges.values() for t, _ in ch})
    if not times:
        raise ValueError("nothing to write")
    state = {n: 0 for n in names}
    pending = {n: dict(edges[n]) for n in names}
    dt = 1.0 / rate_hz
    with open(path, "w") as fh:
        fh.write("Time [s]," + ",".join(names) + "\n")
        for t in times:
            fh.write(f"{max(t - dt, 0.0):.9f}," +
                     ",".join(str(state[n]) for n in names) + "\n")
            for n in names:
                if t in pending[n]:
                    state[n] = 1 if pending[n][t] else 0
            fh.write(f"{t:.9f}," + ",".join(str(state[n]) for n in names) + "\n")
            for n in names:
                if t in pending[n]:
                    state[n] = 0 if pending[n][t] else 1
