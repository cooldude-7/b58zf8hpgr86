# Learning to tune, on the simulator

The simulator runs on its own volumetric efficiency, spark and knock
surfaces, and they are not the tables you are editing. That is the whole
point: the tables start wrong, the engine does not read them to decide
how to behave, and the only way to correct them is the same way you
would correct them on a real engine. If you tune the simulator to the
truth, you have done the real procedure, not a demonstration of it.

Nothing here can break anything. Do it badly on purpose a few times.

## The order, and why it is that order

Each stage is judged by a measurement the other stages do not touch.
That is what lets you change one thing at a time even though everything
in an engine is connected.

| Stage | What you change | What tells you it is right |
|---|---|---|
| 1 | VE table | measured lambda |
| 2 | MBT table | torque |
| 3 | Knock table | knock counter |
| 4 | Lambda target | torque, then re-check spark |

Do not skip ahead. A spark sweep done on a wrong VE table is measuring
your fuelling error.

## Before you start

Open the app connected to the simulator:

```
python -m tuner.app --sim 0
```

Find these, because you will use them constantly:

- **Simulator dock**, left hand side. The virtual pedal, and under Load
  the choice between Road and Dyno. Dyno holds a fixed engine speed,
  which is what makes a controlled sweep possible.
- **Gauges dock**, right hand side. Lambda, torque, spark and the
  numeric readouts under the dials.
- **Datalog**, along the bottom. Record captures every channel; Save
  writes a CSV.
- **The status bar** tells you whether live write is armed. Unarmed,
  your edits stay in the tuner until you press F4. Cells show red when
  the ECU has not seen them, amber when they are in RAM, nothing when
  burned.

For learning, arm live write: **ECU menu, Arm live write**. Then a cell
you type goes straight into the running engine and you see the effect
immediately. You would not do this on a real engine at full load.

## Stage 1: the VE table, against lambda

This is most of the work, and it is the one that has a formula.

You choose the lambda target, so it is known. You measure lambda at the
exhaust. The difference between them is the error in your airflow
estimate, because the VE table is what decided how much fuel went in:

```
VE_new = VE_old × (lambda_measured / lambda_target)
```

If you targeted 0.98 and measured 1.06, the mixture came out leaner than
asked, the table underestimated the air, and that ratio of about 1.08 is
how much the cell needs to come up.

Do this:

1. Set Load to **Dyno** and the setpoint to 3000 rpm.
2. Set the pedal to about 55 percent. Wait for lambda to settle.
3. Read lambda from the gauge, and the lambda target from the Lambda
   Target table at that speed and manifold pressure. The live cursor in
   the table shows where you are.
4. Open the VE table. The cursor marks the four cells you are between.
5. Multiply those cells by the ratio. Select them and press `*`, then
   enter the percentage.
6. Watch lambda move onto target within a second or two.

Then move: change the setpoint, change the pedal, repeat. Work a grid of
speeds and loads. You will find the error is not a constant, which is why
it is a table.

**Done when** lambda sits on target everywhere you can reach, without
you having touched anything else.

**What you should notice:** the correction is large in some regions and
almost nothing in others. That shape is the difference between the base
map and the engine, and on a real engine it is the difference between
the map's engine and yours.

## Stage 2: MBT, by sweeping spark

Only once the VE table is right.

1. Dyno mode, 3000 rpm, pedal around 55 percent, settled.
2. Note the torque readout.
3. In the MBT table, advance the cells around the cursor by one degree
   with `+`. Wait for it to settle. Note the torque.
4. Keep going. Torque will rise, flatten, and then fall.
5. The top of that curve is MBT. Put the table there.

**What you should notice:** the peak is flat. Two degrees either side of
MBT costs almost nothing, which is why nobody chases the last degree and
why a curve with a sharp peak means something else is going on. If two
degrees changes nothing measurable, you are already there.

Go too far and torque falls off faster than it did on the retarded side.
Peak pressure is arriving too early and the engine is fighting it on the
way up.

Repeat at several speeds. At high load you will run into stage 3 before
you find MBT, which is the correct outcome and the subject of the next
section.

## Stage 3: the knock limit

Watch the knock counter and knock retard in the datalog or the readouts.

1. Dyno mode, pick a speed, pedal to full so you are at high load.
2. Raise the Knock Limit cells around the cursor one degree at a time.
3. At some point the knock counter starts incrementing and knock retard
   climbs. That is the limit.
4. Back off two or three degrees from where it started and leave it
   there.

**What you should notice:** at high load the knock limit is below MBT,
often well below. The engine never sees MBT there, so the MBT table
above that load is theoretical and the knock table is what actually
governs the spark. That is why boosted engines are tuned around knock
and not around MBT.

**Also notice** that knock retard is a feedback loop, not a fault. It
pulls timing and gives it back. If it is permanently active, your table
is too aggressive rather than the engine being broken.

## Stage 4: the lambda target, and a re-check

Now you can change what you are aiming for. Richer at high load buys
knock margin through charge cooling and keeps exhaust temperature down;
leaner at cruise is efficient and keeps a catalytic converter working.

Change it and two things happen: torque moves, and your VE corrections
still hold, because VE is about air and this is about fuel. But your
knock limit may have moved, because a richer mixture resists knock. So
re-check stage 3 in the regions you changed.

## Stage 5: the shift coordinator

This one is a programming exercise rather than a calibration.
`tools/shift/coordinator.py` has four sections marked TODO and
currently does nothing, so shifts happen at full torque.

Fill them in, save the file, and press Reload in the Simulator dock. You
should see the cut appear in the Cut retard channel during a shift.

Then tick **Chase air with the cut** and watch what happens after the
shift finishes. The torque overshoot you get is the failure the exercise
exists to teach: if the air path compensates for a deliberate spark cut,
the cut gets diluted, and all the air that was let in arrives as torque
the moment spark comes back.

## The workflow you should build habits around

- **One thing at a time.** If you change two and something improves, you
  have learned nothing.
- **Change, settle, read.** The manifold takes a few hundred
  milliseconds. Reading before it settles is how people tune noise.
- **Record a log for anything you care about.** The datalog writes CSV
  and the numbers do not lie about what you actually did.
- **F4 sends, F5 burns, Ctrl+S saves.** These are three different
  things. Sent means the running engine has it. Burned means it survives
  key-off. Saved means it survives your laptop. The title bar shows an
  asterisk while the file is behind, and the status bar says Burn
  required while the ECU is behind.
- **Undo is Ctrl+Z** and it works on tables. Use it rather than typing a
  value back.

## What transfers to a real engine, and what does not

Transfers: the order of the stages, the VE formula, the shape of an MBT
sweep, the meaning of knock retard, and the discipline of one variable
at a time. Those are the same on a dyno.

Does not transfer: the numbers. Every table here is fitted to a plant I
invented. On the real engine you start from the same base map and find
different corrections.

Also does not transfer: the safety. Here you can command forty degrees
of advance at full boost and watch what happens. The real engine gets
one chance.
