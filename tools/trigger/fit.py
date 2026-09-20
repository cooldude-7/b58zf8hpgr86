"""Recover wheel and cam geometry from a capture.

Everything here is a shape, never an absolute position. The crank gap is
found relative to the teeth around it; the cam pattern is found relative
to the crank. Where any of it sits with respect to cylinder 1 compression
TDC is not in this data and is not guessed -- see PROCEDURE.md.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class WheelFit:
    teeth_total: int
    teeth_missing: int
    gap_edge_indices: list[int]          # index into the crank edge list
    deg_per_tooth: float
    rpm_min: float
    rpm_max: float
    jitter_deg: float                    # 1 sigma of the per-tooth residual
    notes: list[str] = field(default_factory=list)


@dataclass
class CamFit:
    name: str
    n_edges: int
    intervals_deg: list[float]           # crank degrees, edge i -> i+1
    rising: list[bool]
    jitter_deg: float
    cycles_seen: int
    notes: list[str] = field(default_factory=list)


def _baseline(periods: list[float], i: int, span: int = 8) -> float:
    """Median of the periods just before `i`, as a local speed reference.

    A median rather than a mean: a mean that has swallowed one gap is
    already 5 % long, which is enough to miss the next gap.
    """
    lo = max(0, i - span)
    window = periods[lo:i]
    return statistics.median(window) if window else periods[i]


def fit_wheel(edges: list[float], *, gap_ratio: float = 1.5) -> WheelFit:
    """Derive tooth count, missing teeth and gap positions from crank edges."""
    if len(edges) < 40:
        raise ValueError(
            f"only {len(edges)} crank edges; capture at least a few revolutions"
        )
    periods = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]

    gaps: list[int] = []
    ratios: list[float] = []
    for i in range(8, len(periods)):
        base = _baseline(periods, i)
        if base <= 0:
            continue
        r = periods[i] / base
        if r > gap_ratio:
            gaps.append(i)
            ratios.append(r)
    if len(gaps) < 3:
        raise ValueError(
            "found fewer than 3 gaps. Either this is not a missing-tooth "
            "wheel, or the capture is too short, or the trigger level is "
            "wrong and teeth are being missed."
        )

    spacings = [gaps[i + 1] - gaps[i] for i in range(len(gaps) - 1)]
    teeth_per_rev = statistics.mode(spacings)
    odd = [s for s in spacings if s != teeth_per_rev]

    missing = round(statistics.median(ratios) - 1.0)
    if missing < 1:
        missing = 1
    teeth_total = teeth_per_rev + missing
    deg_per_tooth = 360.0 / teeth_total

    notes: list[str] = []
    if odd:
        notes.append(
            f"{len(odd)} of {len(spacings)} revolutions had an unexpected "
            f"tooth count {sorted(set(odd))} against a modal "
            f"{teeth_per_rev}. Dropped edges, or a trigger level that is "
            f"marginal on the small teeth either side of the gap."
        )

    # Speed range, and how well a constant-acceleration model fits each
    # tooth. A large residual means the capture is too noisy to trust for
    # anything finer than the tooth count.
    rpms: list[float] = []
    resid: list[float] = []
    for i, p in enumerate(periods):
        if p <= 0:
            continue
        is_gap = i in set(gaps)
        step = deg_per_tooth * ((missing + 1) if is_gap else 1)
        rpms.append(step / p / 6.0)
        if 1 <= i < len(periods) - 1 and not is_gap:
            pred = 0.5 * (periods[i - 1] + periods[i + 1])
            if pred > 0:
                resid.append((p - pred) / pred * step)

    return WheelFit(
        teeth_total=teeth_total,
        teeth_missing=missing,
        gap_edge_indices=gaps,
        deg_per_tooth=deg_per_tooth,
        rpm_min=min(rpms) if rpms else 0.0,
        rpm_max=max(rpms) if rpms else 0.0,
        jitter_deg=statistics.pstdev(resid) if len(resid) > 2 else 0.0,
        notes=notes,
    )


def crank_angle_track(edges: list[float], wheel: WheelFit) -> list[float]:
    """Cumulative crank angle at each crank edge, starting from zero.

    Cumulative, not wrapped: the whole point is to measure cam spacings
    that are larger than 360 degrees, and a wrapped angle cannot tell 100
    from 820. This is the same trick the firmware decoder uses, where it
    counts crank degrees since each cam's previous edge rather than
    subtracting two angles.
    """
    gaps = set(wheel.gap_edge_indices)
    ang = [0.0]
    for i in range(len(edges) - 1):
        step = wheel.deg_per_tooth * ((wheel.teeth_missing + 1) if i in gaps else 1)
        ang.append(ang[-1] + step)
    return ang


def _angle_at(t: float, edges: list[float], track: list[float]) -> float | None:
    """Interpolate cumulative crank angle at an arbitrary time."""
    if not edges or t < edges[0] or t > edges[-1]:
        return None
    lo, hi = 0, len(edges) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if edges[mid] <= t:
            lo = mid
        else:
            hi = mid
    span = edges[hi] - edges[lo]
    frac = 0.0 if span <= 0 else (t - edges[lo]) / span
    return track[lo] + frac * (track[hi] - track[lo])


def fit_cam(
    name: str,
    cam_edges: list[tuple[float, bool]],
    crank_edges: list[float],
    wheel: WheelFit,
    *,
    cycle_deg: float = 720.0,
    tol_deg: float = 12.0,
    slew_allow_deg: float = 90.0,
) -> CamFit:
    """Derive a cam pattern: how many features, and the gaps between them.

    Only the SHAPE is recoverable here. A phaser moves the whole pattern
    rigidly, so the spacings are a property of the wheel and the absolute
    angles are a property of wherever the phaser happened to be sitting.
    """
    track = crank_angle_track(crank_edges, wheel)
    stamped: list[tuple[float, bool]] = []
    for t, rising in cam_edges:
        a = _angle_at(t, crank_edges, track)
        if a is not None:
            stamped.append((a, rising))
    if len(stamped) < 6:
        raise ValueError(
            f"{name}: only {len(stamped)} cam edges inside the crank "
            f"capture; record at least a few engine cycles"
        )

    deltas = [stamped[i + 1][0] - stamped[i][0] for i in range(len(stamped) - 1)]

    # How many edges make one cycle? The smallest n whose consecutive
    # deltas sum CONSISTENTLY to about 720 crank degrees.
    #
    # "Consistently" rather than "exactly", because a phaser that is
    # moving while the capture runs shifts the whole pattern a little
    # further every cycle, so each cycle measures slightly short (or
    # long) by however far the cam travelled during it. Demanding exactly
    # 720 rejects every capture taken on a running engine, which is most
    # of them. What a real pattern always gives is a tight SPREAD; a
    # steady offset from 720 is a moving phaser and is recoverable.
    n_edges = 0
    sums: list[float] = []
    for n in range(1, min(9, len(deltas))):
        cand = [sum(deltas[i:i + n]) for i in range(0, len(deltas) - n, n)]
        if len(cand) < 2:
            continue
        mid = statistics.median(cand)
        spread = statistics.pstdev(cand)
        if abs(mid - cycle_deg) < slew_allow_deg and spread < tol_deg:
            n_edges, sums = n, cand
            break
    if n_edges == 0:
        raise ValueError(
            f"{name}: could not find a repeating pattern summing to "
            f"{cycle_deg:.0f} crank degrees. Either edges are being "
            f"dropped, or this channel is not a cam sensor."
        )

    # Average each phase of the pattern, so wheel machining error on one
    # lobe does not masquerade as a different pattern.
    groups: list[list[float]] = [[] for _ in range(n_edges)]
    for i, d in enumerate(deltas):
        groups[i % n_edges].append(d)
    intervals = [statistics.fmean(g) for g in groups]
    spread = [statistics.pstdev(g) for g in groups if len(g) > 1]

    # If the cycles came out short or long, the cam was travelling. Scale
    # the spacings back onto a 720-degree cycle and say so -- the wheel
    # geometry is fixed metal, so whatever the phaser was doing is not
    # part of it.
    measured_cycle = statistics.median(sums)
    drift = measured_cycle - cycle_deg
    if abs(drift) > 1.0 and measured_cycle > 0.0:
        scale = cycle_deg / measured_cycle
        intervals = [x * scale for x in intervals]

    rising = [stamped[i][1] for i in range(n_edges)]
    notes: list[str] = []
    if abs(drift) > 1.0:
        span_s = 0.0
        if len(cam_edges) > 1:
            span_s = cam_edges[-1][0] - cam_edges[0][0]
        cycles = max(len(deltas) // n_edges, 1)
        per_cycle_s = (span_s / cycles) if cycles and span_s > 0 else 0.0
        rate = (-drift / per_cycle_s) if per_cycle_s > 0 else 0.0
        notes.append(
            f"the phaser moved during this capture: each cycle measured "
            f"{measured_cycle:.1f} instead of {cycle_deg:.0f} crank "
            f"degrees, about {rate:.0f} deg/s. Spacings have been scaled "
            f"back onto a {cycle_deg:.0f} degree cycle. For the cleanest "
            f"geometry, capture with the phasers parked -- crank the "
            f"engine with no oil pressure."
        )
    if len(set(rising)) > 1:
        notes.append(
            "this pattern mixes rising and falling edges; the decoder "
            "matches one polarity, so confirm which edge carries the "
            "pattern before using it"
        )
    return CamFit(
        name=name,
        n_edges=n_edges,
        intervals_deg=intervals,
        rising=rising,
        jitter_deg=max(spread) if spread else 0.0,
        cycles_seen=len(deltas) // n_edges,
        notes=notes,
    )
