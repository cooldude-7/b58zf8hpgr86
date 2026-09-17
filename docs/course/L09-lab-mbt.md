# L09 — Lab 2: Peak torque timing

**Pass mark:** within two degrees of true MBT everywhere the engine can
reach it.

**Prerequisite:** Lab 1 must pass first. A spark sweep on a wrong VE
table is measuring your fuelling error.

## The difficulty, stated honestly

MBT is a maximum, so the curve is flat there. You are looking for the
top of a hill with a very gentle summit, using a torque reading that
moves around. That is the whole challenge of this lab and it is the
whole challenge on a real dyno.

Two degrees either side of MBT costs well under half a percent of
torque. You will not see that. What you can see is the shape: a clear
rise on one side, a clear fall on the other, and a region in between
where nothing much happens. MBT is the middle of that region.

## Procedure

1. Dyno mode. Pick a speed, start at 2000 rpm.
2. Pedal at 40 percent, which keeps you below the knock limit.
3. Let it settle. Note the torque.
4. In the **MBT Spark** table, select the cells at the cursor and press
   `+` to add a degree. Wait. Note the torque.
5. Keep stepping. Record the numbers as you go, on paper or by reading
   the datalog afterwards.
6. Continue past the point where torque stops rising, until it is
   clearly falling.
7. Put the table at the middle of the flat region.

Then repeat at other speeds. MBT advances with speed, so the shape of
the correction across the rev range is itself information.

## Reading the result

You should get something like this, and the numbers below are from an
actual sweep in this simulator:

| Table offset | Spark | Torque |
|---|---|---|
| −8 | 10.5 | 188.3 |
| −6 | 12.4 | 193.5 |
| −4 | 14.4 | 196.5 |
| −2 | 16.4 | 199.0 |
| 0 | 18.4 | **200.1** |
| +2 | 20.4 | 199.8 |
| +4 | 22.4 | 196.2 |
| +6 | 24.4 | 189.4 |

Note the asymmetry. Going four degrees retarded costs 1.8 percent.
Going four degrees advanced costs 2.0 percent and is also getting close
to knocking. The penalty for over-advance is steeper, which is one
reason calibrations sit slightly retarded of MBT rather than trying to
hit it exactly.

## Where you cannot do this

At high load the knock limit is below MBT. Advance the MBT table all
you like and the ECU will still command the knock-limited value,
because it takes the lower of the two. Torque will not move and you
will learn nothing.

The marker knows this and does not grade points where the engine is
knock limited. Do not waste time there. If a sweep produces no change
in torque at all, check whether knock is what is holding you.

## Common ways to fail this lab

- Doing it before Lab 1 passes.
- Sweeping at full load, where knock governs.
- Chasing noise in the flat region. If two degrees does nothing, you
  are there. Stop.
- Forgetting that the table is a surface. Fixing 2000 rpm perfectly and
  leaving 5000 rpm alone fails.

## Mark it

Course page, **Mark this lab**. Findings say how many degrees out each
point is and in which direction.
