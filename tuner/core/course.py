"""TQ-101: the graded labs.

Each lab states an objective and marks the student's tune against the
simulator's hidden plant. The student cannot see the plant, which is the
point: the grade measures whether the calibration matches the engine,
not whether it matches a worked answer.

Grading is analytic rather than run-based. The relationships are exact,
so there is no need to drive the car to find out:

    measured lambda / target lambda  ==  plant VE / tune VE

so a volumetric efficiency cell is right exactly when the two surfaces
agree there. Spark and knock are direct comparisons. Doing it this way
means a check is instant and deterministic, and a student is never told
they failed because of simulation noise.
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Finding:
    """One thing that is still wrong, in terms the student can act on.

    `error` carries the same meaning in every lab: **how wrong the number
    in the table is, in the table's own units, signed so that positive
    means the cell is too high and wants lowering.** That is what lets the
    editor mark a cell with a direction rather than a paragraph.

    `tol` is the threshold this point exceeded, so severity is
    `abs(error) / tol`. `unsafe` marks a finding that is not merely
    inaccurate -- commanding more advance than the engine will take is a
    different class of wrong from leaving torque on the table.
    """
    rpm: float
    load: float          # kPa, or whatever the table's y axis is
    detail: str
    error: float = 0.0
    tol: float = 0.0
    unsafe: bool = False

    def __str__(self):
        return f"{self.rpm:>5.0f} rpm, {self.load:>4.0f} kPa: {self.detail}"


@dataclass
class Result:
    passed: bool
    summary: str
    findings: list = field(default_factory=list)
    score: float = 0.0          # 0..1, how much of the grid is within spec


@dataclass
class Lab:
    key: str
    title: str
    lecture: str                # which lecture it belongs to
    brief: str
    criterion: str
    grade: object               # callable(tune, plant) -> Result

    def run(self, tune, plant) -> Result:
        return self.grade(tune, plant)


# ---------------------------------------------------------------------------
# The sample grid. Deliberately not the table breakpoints: a student who
# fixed only the cells they happened to visit should not pass, and
# interpolated values are what the engine actually runs on.
# ---------------------------------------------------------------------------
def sample_points(rpm_lo=1200, rpm_hi=6500, n_rpm=8,
                  map_lo=40, map_hi=200, n_map=6):
    rpms = np.linspace(rpm_lo, rpm_hi, n_rpm)
    maps = np.linspace(map_lo, map_hi, n_map)
    return [(float(r), float(m)) for r in rpms for m in maps]


def _score(bad, total):
    return 0.0 if total == 0 else 1.0 - len(bad) / total


# ---------------------------------------------------------------------------
# Lab graders
# ---------------------------------------------------------------------------
def grade_ve(tune, plant, tol=0.03, points=None):
    """Volumetric efficiency, judged as the lambda error it would cause.

    A cell that overestimates airflow by five percent puts five percent
    too much fuel in, and lambda comes back five percent rich. So the
    error the student would measure IS the error in the table.
    """
    points = points or sample_points()
    ve = tune.tables["ve"]
    bad = []
    for rpm, mp in points:
        est = ve.lookup(rpm, mp)
        true = plant.plant_ve(rpm, mp)
        if est <= 0:
            bad.append(Finding(rpm, mp, "volumetric efficiency is zero or negative"))
            continue
        err = true / est - 1.0
        if abs(err) > tol:
            way = "lean" if err > 0 else "rich"
            # err > 0 means the table reads LOW against the truth, so the
            # cell wants raising: the signed error is the other way round
            bad.append(Finding(rpm, mp,
                               f"lambda would read {abs(err) * 100:.1f}% {way}",
                               error=est - true, tol=tol * est))
    ok = not bad
    return Result(ok,
                  "Fuelling is within specification across the map." if ok else
                  f"{len(bad)} of {len(points)} points are outside "
                  f"{tol * 100:.0f}%.",
                  bad, _score(bad, len(points)))


def grade_mbt(tune, plant, tol=2.0, points=None):
    """Peak torque timing, where the engine is allowed to reach it.

    Only graded where the knock limit is not in the way. Above it the
    engine never sees MBT, so requiring the table to be right there
    would be marking work that cannot be done.
    """
    points = points or sample_points()
    mbt = tune.tables["mbt"]
    bad, judged = [], 0
    for rpm, mp in points:
        true_knock = plant.plant_knock_limit(rpm, mp)
        true_mbt = plant.plant_mbt(rpm, mp)
        if true_knock < true_mbt + 1.0:
            continue                      # knock limited: not gradeable here
        judged += 1
        err = mbt.lookup(rpm, mp) - true_mbt
        if abs(err) > tol:
            way = "advanced of" if err > 0 else "retarded from"
            bad.append(Finding(rpm, mp,
                               f"{abs(err):.1f} deg {way} peak torque",
                               error=err, tol=tol))
    ok = not bad and judged > 0
    return Result(ok,
                  f"Peak torque timing is within {tol:.0f} degrees at all "
                  f"{judged} gradeable points." if ok else
                  f"{len(bad)} of {judged} gradeable points are outside "
                  f"{tol:.0f} degrees.",
                  bad, _score(bad, judged))


def grade_knock(tune, plant, margin=3.0, waste=5.0, points=None):
    """The knock limit, marked from both sides.

    Too much advance damages the engine, so that fails hard. Too little
    is safe but leaves torque on the table, and a calibration that
    retards everything to be sure is not a calibration.
    """
    points = points or sample_points()
    knock = tune.tables["knock"]
    bad, unsafe = [], 0
    for rpm, mp in points:
        true = plant.plant_knock_limit(rpm, mp)
        cmd = knock.lookup(rpm, mp)
        over = cmd - true
        if over > 0.0:
            unsafe += 1
            bad.append(Finding(rpm, mp,
                               f"{over:.1f} deg PAST the knock limit",
                               error=over, tol=margin, unsafe=True))
        elif over < -(margin + waste):
            bad.append(Finding(rpm, mp,
                               f"{-over:.1f} deg below the limit: "
                               f"torque left on the table",
                               error=over, tol=margin + waste))
    ok = not bad
    if unsafe:
        summary = (f"UNSAFE: {unsafe} points command more advance than the "
                   f"engine will take.")
    elif ok:
        summary = "Knock limit is safe and not needlessly conservative."
    else:
        summary = f"{len(bad)} of {len(points)} points are too conservative."
    return Result(ok, summary, bad, _score(bad, len(points)))


def grade_lambda(tune, plant, points=None):
    """Mixture strategy, marked against what the targets are FOR.

    Stoichiometric at light load, because that is the only place a
    catalytic converter works. Richer as load rises, for charge cooling
    and exhaust temperature. This is the one lab with no hidden truth:
    the plant does not care, the reasons do.
    """
    points = points or sample_points()
    lam = tune.tables["lambda"]
    bad = []
    for rpm, mp in points:
        target = lam.lookup(rpm, mp)
        if mp <= 95.0:
            if not 0.98 <= target <= 1.02:
                bad.append(Finding(rpm, mp,
                                   f"target {target:.3f}: light load should be "
                                   f"stoichiometric for the catalyst"))
        elif mp >= 170.0:
            if target > 0.90:
                bad.append(Finding(rpm, mp,
                                   f"target {target:.3f}: too lean for full "
                                   f"load, no charge cooling margin"))
            elif target < 0.78:
                bad.append(Finding(rpm, mp,
                                   f"target {target:.3f}: richer than best "
                                   f"torque, wasting fuel and washing bores"))
    ok = not bad
    return Result(ok,
                  "Mixture strategy is sound across the load range." if ok else
                  f"{len(bad)} of {len(points)} points are inappropriate.",
                  bad, _score(bad, len(points)))


def grade_shift(tune, plant, coord=None):
    """The shift coordinator, marked by running it rather than reading it."""
    if coord is None:
        coord = getattr(plant, "coord", None)
    if coord is None or not hasattr(coord, "update"):
        return Result(False, "No coordinator is loaded.", [], 0.0)
    try:
        state = coord.new_controller()
    except Exception as e:                       # noqa: BLE001
        return Result(False, f"new_controller() raised: {e}", [], 0.0)

    findings = []
    driver, entry, target = 400.0, 400.0, 140.0
    try:
        coord.start_shift(state, target, entry)
    except Exception as e:                       # noqa: BLE001
        return Result(False, f"start_shift() raised: {e}", [], 0.0)

    mbt = 25.0
    saw_cut, saw_hold, returned = 0.0, False, False
    air_held = True
    t = 0.0
    for _ in range(600):                          # 0.6 s at 1 ms
        t += 0.001
        try:
            spark, air, tq = coord.update(state, 0.001, driver, mbt)
        except Exception as e:                    # noqa: BLE001
            return Result(False, f"update() raised at t={t:.3f}s: {e}", [], 0.0)
        cut = mbt - spark
        saw_cut = max(saw_cut, cut)
        if abs(tq - target) < 0.05 * target:
            saw_hold = True
        if air > driver * 1.02:
            air_held = False
        if t > 0.45 and cut < 1.0 and abs(tq - driver) < 0.05 * driver:
            returned = True

    if saw_cut < 5.0:
        findings.append(Finding(0, 0, f"spark was only cut {saw_cut:.1f} deg: "
                                      "the fast path is not being used"))
    if not saw_hold:
        findings.append(Finding(0, 0, "torque never settled at the requested "
                                      "target during the hold phase"))
    if not air_held:
        findings.append(Finding(0, 0, "the air request rose during the cut: "
                                      "this is the air-chase failure"))
    if not returned:
        findings.append(Finding(0, 0, "spark and torque did not return to the "
                                      "driver's request after the shift"))
    ok = not findings
    return Result(ok,
                  "Coordinator cuts on the fast path, holds air, and returns."
                  if ok else f"{len(findings)} problems with the coordinator.",
                  findings, _score(findings, 4))


def grade_di(tune, plant, points=None):
    """Direct injection: rail pressure sane, timing sane, pilot where it helps."""
    points = points or sample_points()
    rail = tune.tables["rail_target"]
    soi = tune.tables["soi"]
    split = tune.tables["inj_split"]
    bad = []
    for rpm, mp in points:
        r = rail.lookup(rpm, mp)
        if mp > 150.0 and r < 12000.0:
            bad.append(Finding(rpm, mp,
                               f"rail {r:.0f} kPa is too low for this load: "
                               f"the injector has little time and a lot of "
                               f"cylinder pressure to fight"))
        if mp < 60.0 and r > 15000.0:
            bad.append(Finding(rpm, mp,
                               f"rail {r:.0f} kPa at light load wastes pump "
                               f"work and hurts atomisation of a tiny pulse"))
        s = soi.lookup(rpm, mp)
        if not 240.0 <= s <= 400.0:
            bad.append(Finding(rpm, mp,
                               f"injection at {s:.0f} deg BTDC falls outside "
                               f"the intake event"))
        if mp > 170.0 and rpm > 4000.0 and split.lookup(rpm, mp) < 0.1:
            bad.append(Finding(rpm, mp,
                               "no pilot pulse where mixing time is shortest"))
    ok = not bad
    return Result(ok,
                  "Direct injection strategy is sound." if ok else
                  f"{len(bad)} of {len(points)} points need attention.",
                  bad, _score(bad, len(points)))


# ---------------------------------------------------------------------------
def student_tune():
    """The tune the course starts from.

    The shipped base map is a sensible starting point, which makes it a
    poor exercise: two of the labs pass before the student has done
    anything. This one is wrong in specific, instructive ways, and every
    error in it is one a real calibration has had at some point.
    """
    from .tune import default_tune

    t = default_tune()
    t.name = "TQ-101 student tune"

    # Rich at cruise. Feels safe, ruins the catalyst, costs fuel, and is
    # what you get when somebody is frightened of lean.
    lam = t.tables["lambda"]
    ymap = lam.y[:, None] if lam.y.ndim > 1 else lam.y[:, None]
    light = (ymap <= 95.0)
    lam.values[:] = np.where(light, 0.93, lam.values)

    # Lean at full load. The dangerous one, and it looks like free power
    # on a dyno right up until it is not.
    heavy = (ymap >= 170.0)
    lam.values[:] = np.where(heavy, 0.95, lam.values)

    # A flat rail pressure, as though the pump had one setting.
    t.tables["rail_target"].values[:] = 8000.0

    # Injection late enough to be spraying at a closing intake valve.
    t.tables["soi"].values[:] = 250.0

    # No pilot pulse anywhere.
    t.tables["inj_split"].values[:] = 0.0

    for tbl in t.tables.values():
        tbl.mark_saved()
        tbl.mark_burned()
    return t.validate()


LABS = [
    Lab("ve", "Lab 1: Volumetric efficiency", "L8",
        "Correct the VE table until the mixture lands on target everywhere. "
        "Work in dyno mode, read lambda, and multiply the cells by measured "
        "over target. Nothing else on this lab: leave spark alone.",
        "Every sampled point within 3% of its lambda target.",
        grade_ve),
    Lab("mbt", "Lab 2: Peak torque timing", "L9",
        "Find MBT by sweeping spark and watching torque. Only meaningful "
        "once Lab 1 passes, because a sweep on a wrong VE table measures "
        "your fuelling error. Where knock gets there first, leave it.",
        "Within 2 degrees of true MBT everywhere the engine can reach it.",
        grade_mbt),
    Lab("knock", "Lab 3: The knock limit", "L10",
        "Raise the knock table until the counter moves, then back off. "
        "Marked from both sides: past the limit fails outright, and burying "
        "everything in retard to be safe also fails.",
        "Never past the limit, and never more than 8 degrees under it.",
        grade_knock),
    Lab("lambda", "Lab 4: Mixture strategy", "L11",
        "Set lambda targets that suit what each region is for. Light load "
        "has a catalyst to keep working; full load has heat and knock to "
        "manage.",
        "Stoichiometric below 95 kPa, between 0.78 and 0.90 above 170 kPa.",
        grade_lambda),
    Lab("shift", "Lab 5: The shift coordinator", "L13",
        "Finish the four TODOs in tools/shift/coordinator.py so a shift cuts "
        "torque on the fast path, holds the air request where it was, and "
        "ramps back afterwards.",
        "Cuts at least 5 degrees, holds the target, does not chase air, "
        "and returns.",
        grade_shift),
    Lab("di", "Lab 6: Direct injection", "L14",
        "Set rail pressure, injection timing and the pilot fraction so the "
        "fuel system suits the load it is under.",
        "Rail pressure appropriate to load, injection inside the intake "
        "event, pilot pulse where mixing time is short.",
        grade_di),
]

LABS_BY_KEY = {lab.key: lab for lab in LABS}
