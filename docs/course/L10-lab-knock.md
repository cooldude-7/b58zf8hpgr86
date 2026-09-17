# L10 — Lab 3: The knock limit

**Pass mark:** never past the limit, and never more than eight degrees
under it.

**Prerequisite:** Labs 1 and 2. A knock limit found at the wrong
mixture is not the knock limit.

## Marked from both sides, and why

Every other lab has one failure mode. This one has two, and they pull
in opposite directions.

**Too much advance** and the engine detonates. On the simulator you
watch a counter increment. On a real engine you are eroding a piston
crown. This fails outright, and the marker says UNSAFE rather than
giving you a score.

**Too little advance** and nothing breaks, but you have thrown away
torque and you have also thrown away the point of the exercise. A
calibration that retards everything to be certain is not a
calibration. The marker fails anything more than eight degrees under
the limit.

Real calibration lives in that gap, and the skill is knowing how much
margin to keep. Production maps typically sit a few degrees below
where knock starts, because fuel quality varies, intake temperature
varies, and the engine gets dirtier as it ages.

## Procedure

1. Dyno mode, 3000 rpm, pedal at full. You want to be genuinely on
   boost.
2. Watch **Knock count** and **Knock retard**. They are in the datalog
   legend; add them if they are not showing.
3. Raise the **Knock Limit** cells at the cursor by one degree.
4. Wait. Watch the counter.
5. Repeat until the counter starts incrementing and retard appears.
6. Back off three degrees from there.
7. Move to another speed and load and repeat.

Work across the map. The limit falls steeply with load and rises with
speed, for the reasons in L03, so the surface has a definite shape and
a flat knock table is always wrong.

## What you should notice

**Knock retard is a loop, not a warning.** It pulls timing and gives it
back continuously. Seeing it act once while you are probing is the
experiment working. Seeing it permanently active means your table is
past the limit and the ECU is holding the engine together for you.

**The limit crosses MBT.** At light load MBT is lower and the knock
table is irrelevant. Somewhere in the mid range they cross, and above
that the knock table is the one deciding your spark. Find where that
crossover is on this engine.

**There is timing available in some places.** The course tune is not
uniformly conservative. In some regions it is already past the limit
and needs pulling back. Finding out which is which is the lab.

## A note about the real thing

On the simulator you creep up until the counter moves and then step
back, and nothing is harmed. On an engine the counter moving means it
already knocked, and a few cycles of heavy detonation at full boost is
enough to do damage.

Real practice differs in three ways. You approach from much further
below. You do it at the worst conditions you expect, hot with the
poorest fuel you would use, because otherwise you have calibrated for
a day that will not always happen. And you leave more margin than the
measurement strictly requires.

## Mark it

Course page, **Mark this lab**. An UNSAFE result lists every point
commanding more advance than the engine will take. Fix those first;
the conservative ones can wait.
