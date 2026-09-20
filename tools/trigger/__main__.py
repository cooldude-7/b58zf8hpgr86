"""Command line: capture in, decoder configuration out.

    python -m tools.trigger fit capture.csv
    python -m tools.trigger emit capture.csv --gap-to-tdc 114.0 \
        --cam cam_in:181.0:-8:70 --out fw/src/decoder_cal.c
"""
from __future__ import annotations

import argparse
import sys

from .capture import read_csv
from .emit import emit_c
from .fit import fit_cam, fit_wheel


def _channels(cap, crank_name):
    crank = cap.get(crank_name)
    crank_edges = sorted(crank.rising)
    if len(crank_edges) < 40:
        # Some analysers export the crank on the falling edge.
        if len(crank.falling) > len(crank.rising):
            crank_edges = sorted(crank.falling)
    return crank_edges


def cmd_fit(args) -> int:
    cap = read_csv(args.csv)
    crank_edges = _channels(cap, args.crank)
    wheel = fit_wheel(crank_edges)

    print(f"crank wheel:  {wheel.teeth_total}-{wheel.teeth_missing}")
    print(f"  {len(wheel.gap_edge_indices)} gaps over the capture")
    print(f"  speed {wheel.rpm_min:.0f}..{wheel.rpm_max:.0f} rpm")
    print(f"  per-tooth jitter {wheel.jitter_deg:.3f} deg (1 sigma)")
    for n in wheel.notes:
        print(f"  NOTE: {n}")

    for name in cap.channels:
        if name == args.crank:
            continue
        try:
            cam = fit_cam(name, cap.get(name).all_edges(), crank_edges, wheel)
        except ValueError as exc:
            print(f"\n{name}: not a cam pattern ({exc})")
            continue
        print(f"\ncam {name}: {cam.n_edges} features, "
              f"{cam.cycles_seen} cycles seen")
        print(f"  spacings, crank deg: "
              f"{', '.join(f'{x:.1f}' for x in cam.intervals_deg)}")
        print(f"  jitter {cam.jitter_deg:.2f} deg")
        for n in cam.notes:
            print(f"  NOTE: {n}")

    print("\nNot derivable from this capture, and not guessed:")
    print("  gap_to_tdc_deg, and where each cam pattern sits in the 720")
    print("  degree cycle. See tools/trigger/PROCEDURE.md.")
    return 0


def cmd_emit(args) -> int:
    cap = read_csv(args.csv)
    crank_edges = _channels(cap, args.crank)
    wheel = fit_wheel(crank_edges)

    cams = []
    for spec in args.cam:
        try:
            name, first, lo, hi = spec.split(":")
            first_f, lo_f, hi_f = float(first), float(lo), float(hi)
        except ValueError:
            print(f"bad --cam {spec!r}; want name:first_angle:adv_min:adv_max",
                  file=sys.stderr)
            return 2
        cam = fit_cam(name, cap.get(name).all_edges(), crank_edges, wheel)
        cams.append((cam, first_f, lo_f, hi_f))

    text = emit_c(wheel, cams, gap_to_tdc_deg=args.gap_to_tdc,
                  provenance=f"from {args.csv}")
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.trigger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fit", help="read a capture and report what is in it")
    f.add_argument("csv")
    f.add_argument("--crank", default="crank")
    f.set_defaults(fn=cmd_fit)

    e = sub.add_parser("emit", help="write a decoder configuration as C")
    e.add_argument("csv")
    e.add_argument("--crank", default="crank")
    e.add_argument("--gap-to-tdc", type=float, required=True,
                   help="from PROCEDURE.md; this tool cannot measure it")
    e.add_argument("--cam", action="append", default=[],
                   metavar="NAME:FIRST_DEG:ADV_MIN:ADV_MAX")
    e.add_argument("--out")
    e.set_defaults(fn=cmd_emit)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
