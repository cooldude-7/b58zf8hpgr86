# L07 — Two paths to torque

## Fast and slow

There are two ways to change how much torque an engine makes, and they
have completely different characters.

**The air path.** Open the throttle, raise boost. Sets how much energy
is available to harvest. Slow, because the manifold has to fill and the
turbocharger has to spin up. Hundreds of milliseconds. Costs nothing:
air is free and retarding nothing means harvesting everything.

**The spark path.** Retard from MBT. Sets how much of the available
energy you actually collect. Fast, because it takes effect on the very
next combustion event, which at 3000 rpm is within twenty milliseconds.
Expensive, because the energy you do not collect leaves as heat.

A torque-based ECU uses both, and knowing which to use for what is most
of the craft.

## Authority

At any moment, the amount of torque you could remove right now using
spark alone is called the fast-path authority. In this codebase:

```python
now   = brake_torque(..., spark, ...)
floor = brake_torque(..., mbt - 30, ...)
authority = now - floor
```

It is the difference between what you are making and what you would
make at the retard limit. It is published as a channel and you can
watch it on the gauge panel.

Why it matters: it is the answer to "if something needs torque removed
in the next ten milliseconds, can I do it?" A transmission about to
start a shift needs exactly that answer before it commits, and a two
box engine and transmission setup structurally cannot provide it. That
is the argument for integrating them, and it is the thesis of this
whole project.

Note what makes authority small. If spark is already heavily retarded
by the knock limit, most of the range has been spent and there is
little left. So at full boost, when the transmission most wants a big
fast cut, you have the least fast authority available. Real shift
strategies account for this.

## Which path for which job

| Job | Path | Why |
|---|---|---|
| Driver asks for more | air | it is free, and nobody is in a hurry over 300 ms |
| Driver asks for less | air | same |
| Shift torque cut | spark | must happen in a few milliseconds |
| Traction control, first response | spark | wheel is already spinning |
| Traction control, sustained | air | spark retard cooks the exhaust |
| Idle stability | both | air for the setpoint, spark for the fast correction |
| Catalyst heating | both | air for reserve, spark to dump it into the exhaust |
| Rev limiter | fuel cut | beyond both |

The pattern: spark for anything urgent, air for anything sustained, and
hand over from one to the other if the event lasts.

## The handover, and how it goes wrong

The interesting failures are all at the boundary.

If the air path does not know that a spark retard is deliberate, it
sees low torque and opens up to compensate. Now you have a cut that is
being cancelled by rising air, and when the retard ends all that air
becomes torque at once. That is the air-chase failure, it is the
subject of L12, and you will build it deliberately in Lab 5.

The fix is architectural rather than clever: the coordinator that asks
for the cut also tells the air path to hold where it was. In the code,
`update()` in `tools/shift/coordinator.py` returns both a spark command
and an air request, and the air request is the one that matters.

## Look at this in the app

Watch **Authority** while you drive. At light throttle it is small in
absolute terms. At full boost it is large but a smaller fraction of
total torque, because knock retard has already spent part of the range.

Then watch **Cut retard** during a shift. It is zero at the moment,
because your coordinator has not been written yet.

## Questions to be able to answer

1. Why is spark the right tool for a shift cut and the wrong tool for a
   long traction control intervention?
2. Why is fast-path authority smallest exactly when a transmission most
   wants it?
3. If air and spark can both set torque, why does the ECU need to
   decide which, rather than using whichever is convenient?
