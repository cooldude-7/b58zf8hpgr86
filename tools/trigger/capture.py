"""Reading captures off the instruments people actually own.

Two shapes turn up. A logic analyser exports edges or logic samples, and
is easy. A scope exports voltage samples, and a VR crank sensor is not
logic at all -- it is a bipolar analogue signal whose amplitude is
proportional to how fast the wheel is turning, which is why a VR capture
taken at cranking speed can be almost unreadable while the same sensor is
perfectly clear at 3000 rpm.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field


@dataclass
class Channel:
    """Rising/falling edge times for one signal, in seconds."""

    name: str
    rising: list[float] = field(default_factory=list)
    falling: list[float] = field(default_factory=list)

    def all_edges(self) -> list[tuple[float, bool]]:
        e = [(t, True) for t in self.rising] + [(t, False) for t in self.falling]
        e.sort()
        return e


@dataclass
class Capture:
    channels: dict[str, Channel]
    duration_s: float = 0.0

    def get(self, name: str) -> Channel:
        if name not in self.channels:
            raise KeyError(
                f"no channel named {name!r}; capture has "
                f"{sorted(self.channels)}"
            )
        return self.channels[name]


def edges_from_samples(
    times: list[float],
    volts: list[float],
    *,
    hysteresis: float | None = None,
) -> tuple[list[float], list[float]]:
    """Threshold a sampled waveform into edges, with hysteresis.

    The threshold is the midpoint of the signal and the hysteresis band
    defaults to a tenth of its range. Without a band, a noisy signal
    produces a burst of edges every time it crosses, which downstream
    looks exactly like a wheel with far too many teeth.

    Edge times are linearly interpolated between the two samples that
    straddle the threshold. That matters more than it sounds: a scope
    sampling at 1 MHz quantises an edge to 1 us, which at 7000 rpm is
    0.04 crank degrees -- fine -- but at a low sample rate the
    quantisation lands straight in the tooth-period jitter the fit uses
    to find the gap.
    """
    if len(times) != len(volts) or len(times) < 2:
        raise ValueError("times and volts must be the same length, and > 1")

    lo, hi = min(volts), max(volts)
    if hi - lo < 1e-9:
        return [], []
    mid = 0.5 * (lo + hi)
    band = (hi - lo) * 0.10 if hysteresis is None else hysteresis
    hi_th, lo_th = mid + band * 0.5, mid - band * 0.5

    rising: list[float] = []
    falling: list[float] = []
    state = volts[0] > mid
    for i in range(1, len(volts)):
        v0, v1 = volts[i - 1], volts[i]
        if not state and v1 > hi_th:
            th = hi_th
            state = True
            out = rising
        elif state and v1 < lo_th:
            th = lo_th
            state = False
            out = falling
        else:
            continue
        span = v1 - v0
        frac = 0.0 if abs(span) < 1e-12 else (th - v0) / span
        frac = min(max(frac, 0.0), 1.0)
        out.append(times[i - 1] + frac * (times[i] - times[i - 1]))
    return rising, falling


def read_csv(path: str, *, time_col: str | None = None) -> Capture:
    """Read a Saleae/DSView-style CSV.

    Accepts either logic columns (0/1 per channel per sample) or analogue
    voltages, deciding per column: a column holding only two distinct
    values is logic, anything else is thresholded.
    """
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh))
    if len(rows) < 3:
        raise ValueError(f"{path}: too few rows to be a capture")

    header = [h.strip() for h in rows[0]]
    if time_col is None:
        for cand in header:
            if cand.lower().startswith(("time", "t[", "t(", "seconds")):
                time_col = cand
                break
        else:
            time_col = header[0]
    ti = header.index(time_col)

    cols: dict[str, list[float]] = {h: [] for h in header}
    times: list[float] = []
    for r in rows[1:]:
        if len(r) != len(header):
            continue
        try:
            t = float(r[ti])
        except ValueError:
            continue
        times.append(t)
        for j, h in enumerate(header):
            try:
                cols[h].append(float(r[j]))
            except ValueError:
                cols[h].append(float("nan"))

    chans: dict[str, Channel] = {}
    for h in header:
        if h == time_col:
            continue
        v = cols[h]
        distinct = {x for x in v if x == x}
        if len(distinct) <= 2:
            rising, falling = [], []
            prev = None
            for t, x in zip(times, v):
                if prev is not None and x != prev:
                    (rising if x > prev else falling).append(t)
                prev = x
        else:
            rising, falling = edges_from_samples(times, v)
        chans[h] = Channel(h, rising, falling)

    return Capture(chans, duration_s=(times[-1] - times[0]) if times else 0.0)
