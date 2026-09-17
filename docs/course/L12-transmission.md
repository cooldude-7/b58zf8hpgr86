# L12 — Coordinating with a transmission

## What a clutch has to do

An automatic gearbox changes ratio by releasing one clutch and applying
another. During the changeover both are partly engaged and slipping,
and the friction material is absorbing the difference between input
and output speed.

The energy going into that friction material is torque times slip
speed. Torque is set by the engine. So the engine's behaviour during
those few hundred milliseconds decides whether the shift is smooth,
harsh, or destructive.

A shift has three phases:

**Fill.** Hydraulic pressure takes up clearance in the oncoming clutch.
Nothing has happened mechanically yet. Around 100 ms.

**Torque phase.** The oncoming clutch starts taking torque while the
offgoing one gives it up. If both hold too much at once the
transmission binds; if neither holds enough, it flares. Around 100 ms.

**Inertia phase.** The engine has to change speed to match the new
ratio. On an upshift it must slow down, and the energy of slowing it
goes into the oncoming clutch as heat. Around 250 ms.

## Why the engine has to help

Consider an upshift at full throttle. The engine is making 400 Nm at
7000 rpm and the new ratio requires 5000 rpm. Something has to absorb
400 Nm while dragging the engine's rotating mass down by 2000 rpm.

If the clutch does all of it, the shift is violent and the friction
material has a hard life. If the engine reduces its torque for the
duration, the clutch's job becomes small and the shift becomes
imperceptible.

That is what a torque cut is: the engine briefly making less, on
request, so the transmission can do its job gently. Every modern
automatic relies on it, and it is why they need a torque-based engine
management system to talk to.

## Why it must be the fast path

The whole event is a few hundred milliseconds and the torque phase is
a fraction of that. The air path cannot move in that time. Only spark
can, which is L07.

So a shift cut is spark retard, ramped in over tens of milliseconds,
held for the duration, and ramped back out.

## The failure this course cares about

Here is where it goes wrong, and it is worth following slowly because
it is the most instructive bug in the whole system.

The driver is flat. The pedal is asking for 400 Nm. The transmission
asks for a cut to 150 Nm for the shift. The coordinator retards spark
to produce 150 Nm.

Now the air path looks at the situation. It sees a torque request of
400 Nm from the pedal, which has not changed, because the driver's
foot has not moved. It looks at the inverse model in L06, which asks:
how much air do I need to make 400 Nm at the spark I am currently
running? And the spark it is currently running is heavily retarded.

The answer is: a great deal more air.

So the throttle opens. Boost builds. The cut gets diluted, because
more air at the same retard is more torque. And then the shift ends,
spark ramps back to the knock limit, and all of that extra air is
suddenly being harvested at full efficiency. The torque that lands on
a clutch that has just finished engaging is far more than anybody
planned for.

## The fix

The coordinator that asks for the cut must also tell the air path to
hold where it was.

During the shift, the air request stays frozen at the pre-shift value.
The throttle does not move. The manifold stays full. Spark does all of
the torque reduction, and when it ramps back out the torque returns to
exactly what the driver asked for, immediately, because the air was
there all along.

That last part is a bonus rather than an accident. Holding the air is
what makes the torque come back instantly after the shift, which is
what makes an upshift at full throttle feel like one continuous pull
rather than two separate ones.

## In this codebase

`tools/shift/coordinator.py` returns three things from `update()`:

```python
return spark, air_request, torque_target
```

The `air_request` is the one that matters. Return the driver's request
and the air holds. Return something derived from the cut and you have
built the failure above, which is what the `chase_air_bug` flag does
on purpose so you can watch it.

## Questions to be able to answer

1. Why can the air path not be used for a shift cut?
2. During the cut, the engine is making 150 Nm but the air in the
   manifold is enough for 400. Where is the other 250 Nm going?
3. Why does holding the air make the post-shift torque recovery faster
   rather than slower?
4. The engine speed drops from 7000 to 5000 during the shift. If the
   air request is held constant, why does the torque not change as the
   speed falls?
