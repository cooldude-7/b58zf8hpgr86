"""Regenerate fw/tests/data/golden.txt from the Python torque model.

The Python model is the reference; the C port in fw/src/model.c is checked
against this file. When the model changes deliberately, run

    python3 tools/gen_golden.py

and commit the regenerated file alongside the change that caused it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tqmodel.model import (Engine, air_mass, authority, base_torque,
                           brake_torque, friction_torque, indicated_efficiency,
                           lambda_efficiency, required_air, spark_efficiency,
                           ve_from_air)

OUT = Path(__file__).resolve().parents[1] / "fw" / "tests" / "data" / "golden.txt"


def rows():
    e = Engine()
    yield "indicated_efficiency", (), indicated_efficiency(e)
    for ve in (0.3, 0.6, 0.95, 1.25):
        for mp in (30.0, 100.0, 180.0, 250.0):
            for t in (280.0, 320.0, 360.0):
                a = float(air_mass(ve, mp, t, e))
                yield "air_mass", (ve, mp, t), a
                yield "ve_from_air", (a, mp, t), float(ve_from_air(a, mp, t, e))
    for d in (0.0, 1.0, 5.0, 10.0, 17.5, 20.0, 30.0, 45.0, 60.0, 80.0, -5.0):
        yield "spark_efficiency", (d,), float(spark_efficiency(d))
    for lam in (0.70, 0.80, 0.88, 1.00, 1.15, 1.40):
        yield "lambda_efficiency", (lam,), float(lambda_efficiency(lam))
    for air in (0.1, 0.35, 0.7, 1.1):
        for rpm in (800.0, 3000.0, 7000.0):
            yield "base_torque", (air, rpm), float(base_torque(air, rpm, e))
    for rpm in (800.0, 2000.0, 4500.0, 7200.0):
        for mp in (30.0, 100.0, 220.0):
            yield "friction_torque", (rpm, mp), float(friction_torque(rpm, mp, e))
    for ve in (0.5, 0.95):
        for mp in (60.0, 150.0, 240.0):
            for rpm in (1200.0, 4000.0, 6800.0):
                for spark, mbt in ((18.0, 18.0), (5.0, 22.0), (-10.0, 25.0)):
                    for lam in (0.85, 1.0):
                        args = (ve, mp, 320.0, rpm, spark, mbt, lam)
                        yield "brake_torque", args, float(brake_torque(*args, e))
                        yield "authority", args, float(authority(*args, e))
    for tgt in (20.0, 150.0, 400.0):
        for rpm in (1000.0, 3500.0, 6500.0):
            for spark, mbt in ((20.0, 20.0), (8.0, 24.0)):
                for lam in (0.88, 1.0):
                    args = (tgt, rpm, spark, mbt, lam, 150.0)
                    yield "required_air", args, float(required_air(*args, e))


def main():
    lines = ["# Generated from tqmodel by tools/gen_golden.py -- do not edit.",
             "# name n_args arg... expected"]
    n = 0
    for name, args, val in rows():
        lines.append(f"{name} {len(args)} "
                     + " ".join(f"{a:.17g}" for a in args)
                     + f" {val:.17g}")
        n += 1
    OUT.write_text("\n".join(lines) + "\n")
    print(f"{n} rows -> {OUT}")


if __name__ == "__main__":
    main()
