# L08 — Lab 1: Volumetric efficiency

**Pass mark:** every sampled point within three percent of its lambda
target.

> **[Finding the Air](https://claude.ai/artifact/Pg9ux8q7NxRRUpo8kmoWiQ)** has this lab playable, against
> an engine of its own: hold a point, read lambda, scale the cells,
> watch the error map turn green. Same physics, same 48-point marker,
> same three percent. Worth ten minutes there before doing it in the
> app, where one reading takes two seconds to settle.

## What you are doing

Correcting the VE table until the fuel the ECU calculates matches the
air the engine actually took. You judge it by lambda, because lambda is
the only thing in the chain you can both choose and measure.

## The method

From L05:

```
VE_new = VE_old × (lambda_measured / lambda_target)
```

That is it. There is no iteration to it in principle, and in practice
one pass gets you within a fraction of a percent.

## Procedure

1. Press **Load the course tune** on the Course page if you have not.
2. Arm live write: **ECU menu, Arm live write**. Your edits go straight
   into the running engine, which makes the loop tight. You would not
   do this on a real engine at full load.
3. In the Simulator dock set **Load** to **Dyno** and the setpoint to
   1500 rpm.
4. Set the pedal to about 25 percent. Wait two seconds for lambda to
   settle.
5. Read the lambda gauge. Open the **Lambda Target** table and read
   what you asked for at the cursor position.
6. Open the **VE Table**. The cursor marks the cell block you are
   operating in.
7. Select those cells, press `*`, and enter the ratio as a percentage.
   Measured 1.06 against a target of 1.00 is 106 percent.
8. Watch lambda move onto target.
9. Move to a new operating point and repeat.

Cover the grid: roughly 1200 to 6500 rpm, and at each speed a few
pedal positions from light to full. The marker samples a grid that is
deliberately not aligned with the table breakpoints, so you cannot pass
by fixing only the cells you happened to land on. Interpolated values
are what the engine runs on.

## Tools that make this quicker

- `*` scales a selection by a percentage. This is the main one.
- `I` interpolates a rectangle from its four corners. Fix the corners
  of a region, then fill between them.
- `S` smooths a selection. Useful at the end: a VE surface should be
  smooth, and a cell that is sharply different from its neighbours is
  almost always a bad reading rather than real physics.
- Ctrl+Z undoes.

## What you should notice

**The error is not constant.** It varies with speed in a wave and falls
away at high load. That is a real shape, and on a real engine it would
be telling you something about how your intake and cams differ from
whatever the base map was built on.

**One pass is enough.** If you are iterating three or four times on the
same cell, you are probably reading lambda before it has settled.

**Smoothness is information.** When you have finished, look at the
surface in 3D with the `3D` button. It should be a smooth hill. Spikes
are mistakes.

## Common ways to fail this lab

- Reading lambda before it settles. Change, wait, then read.
- Correcting in the wrong direction. Measured richer than target means
  too much fuel means the table is too high. The formula handles the
  sign for you if you trust it.
- Fixing only the breakpoints you visited and leaving the regions
  between them wrong.
- Touching the spark tables. This lab is about air. If you change spark
  you change torque and learn nothing about fuelling.

## Mark it

Course page, **Mark this lab**. Findings are listed by operating point
with the direction of the error. Work through them and mark again.
