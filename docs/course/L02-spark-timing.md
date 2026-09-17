# L02 — Spark timing and maximum brake torque

## Burning takes time

A spark does not cause an explosion. It lights a flame kernel, and that
flame travels across the chamber. On a typical engine the whole process
takes somewhere between one and two milliseconds.

At 6000 rpm, one crankshaft revolution takes ten milliseconds. So the
burn occupies something like forty to sixty degrees of crank rotation.
That is the entire reason spark timing exists as a control variable: you
have to start the fire early enough that it is burning hard when you
want the pressure, and the amount of "early" depends on how fast the
engine is turning.

## What you are actually timing

You want peak cylinder pressure to occur shortly after top dead centre,
around fourteen to sixteen degrees after, near enough regardless of
engine, speed or load. That number is one of the most stable facts in
this subject.

Why there and not at top dead centre? Because at top dead centre the
crank has no leverage. The connecting rod is pushing straight down
through the crank centre and the moment arm is nearly zero. You can
make all the pressure you like and get no torque from it. A few degrees
later the crank has rotated enough to convert that pressure into a
turning moment.

Why not later still? Because the cylinder is expanding. Wait too long
and the gas is pushing on a volume that is already growing away from
it, and you finish the stroke with hot gas still under pressure, which
then leaves through the exhaust valve carrying energy you paid for and
never collected.

So: too early and you fight the piston on its way up. Too late and you
throw heat out of the exhaust. Somewhere between is a maximum.

## MBT

The spark timing that produces that maximum is called MBT, for maximum
brake torque. It is defined by measurement, not by theory: it is
whatever timing gives the most torque at a given operating point.

Two consequences worth internalising.

**MBT is a maximum, so the curve is flat there.** By definition, the
slope of torque against spark is zero at MBT. Move a degree either way
and torque changes by almost nothing. Move ten degrees and you notice.
In this repository the curve is `spark_efficiency` in
`tqmodel/model.py`, and it is deliberately written with zero slope at
the origin for exactly this reason.

| Degrees retarded from MBT | Torque remaining |
|---|---|
| 5 | 98% |
| 10 | 93% |
| 20 | 76% |
| 30 | 50% |

**It moves with everything.** Faster engine speed means less time per
degree, so the spark must come earlier. More load means a denser
charge, which burns faster, so the spark comes later. Different fuel,
different mixture, different cam timing all move it. Hence a table.

## Retard as a control input

Because the relationship is smooth and repeatable, spark retard is a
torque control. Pull ten degrees and you have about ninety-three
percent of the torque, within a single engine cycle, without touching
the throttle. That is a remarkably useful thing to have, and Part IV of
this course is largely about what it is used for.

The cost is heat. The energy you did not turn into torque leaves as hot
exhaust gas. Sustained heavy retard cooks turbochargers and catalytic
converters, which is why it is a tool for milliseconds, not minutes.

## Look at this in the app

Open the **MBT Spark** table. Notice that it advances with engine speed
and retards with load, for the two reasons above.

Then open the **Knock Limit** table next to it and compare. At low load
they are far apart and MBT wins. At high load the knock limit is well
below MBT and it is the knock table that decides. The ECU commands the
lower of the two, which you can see in `sim_ecu.py`:

```python
spark_cmd = min(mbt_tbl, knock_tbl) - 1.0
```

That single line is most of a spark strategy.

## Questions to be able to answer

1. Why does MBT advance as engine speed rises but retard as load rises?
2. You retard ten degrees and torque falls seven percent. Where did the
   energy go?
3. If the torque curve is flat at MBT, how would you ever find it by
   measurement? (This is Lab 2. Think about it before you get there.)
