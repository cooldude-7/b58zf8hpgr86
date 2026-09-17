# L13 — Lab 5: The shift coordinator

**Pass mark:** cuts at least five degrees, holds the requested target,
does not chase air, and returns to the driver's request afterwards.

This is a programming lab rather than a calibration one. You are
finishing `tools/shift/coordinator.py`.

## What is there

A state machine with four phases: idle, cutting, holding, restoring.
Helper functions that convert between a torque fraction and degrees of
retard, which are given to you because they are algebra rather than
architecture.

Four sections marked TODO, which are not.

## The four

**TODO 1: advance the phase.** Each phase has a duration in
milliseconds. When `time_in_phase` exceeds it, move to the next and
reset the timer. Watch the units: the constants are in milliseconds and
the accumulator is in seconds.

**TODO 2: the torque target.** Idle passes the driver's request
through. Cutting ramps down from the torque at the start of the shift
to the requested target. Holding sits at the target. Restoring ramps
back up to the driver's request. The `ramp()` helper does the
interpolation.

**TODO 3: the spark angle.** You want a fraction of the torque you
started with. `retard_for_fraction()` turns that fraction into degrees.
Subtract from the current reference.

**TODO 4: the air request.** The important one, and the subject of
L12. While any phase other than idle is running, the air request stays
at `frozen_air`. When idle, it is the driver's request. If
`chase_air_bug` is set, do the wrong thing deliberately.

## Testing it

Save the file and press **Reload** in the Simulator dock. The label
tells you whether it imported.

Then drive: road mode, full throttle, and either let it shift
automatically or press the shift buttons. Watch **Cut retard** in the
datalog. It should rise, hold, and fall back to zero, and the whole
event should last about half a second.

## Then break it on purpose

Tick **Chase air with the cut** and do the same shift. Watch the torque
trace after the shift completes.

That overshoot is the failure from L12, and seeing it once is worth
more than reading about it three times. Note how the peak is worse at
higher boost, because there is more air available to inflate.

## Notes

Your coordinator is untrusted code as far as the ECU is concerned. If
it raises an exception, the simulator catches it once, falls back to
the base spark, sets a fault channel and keeps the engine running. If
it returns an absurd retard, the value is clamped to the engine's
`max_cut_retard` scalar. You will not be able to break the engine from
inside it, which is deliberate: that is how a real ECU should treat a
subsystem that asks it to do something drastic.

## Mark it

Course page, **Mark this lab**. The marker runs your coordinator
directly with a synthetic shift and checks the four behaviours in the
pass mark. It does not read your code, only what it does.
