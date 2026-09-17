# L15 — Taking it to a real engine

The final session, and it is not a lab. It is the list of every way in
which the previous fourteen have been easier than the real thing.

## What genuinely transfers

The order of operations. Air before spark before knock, because each
is measured by something the others do not disturb. That is not a
convention, it is what makes the measurements mean anything, and it is
identical on a dyno.

The volumetric efficiency formula. Measured lambda over target lambda,
multiply the cell. Exactly the same on an engine.

The shape of an MBT sweep, including the flat top and the steeper fall
on the advanced side.

What knock retard means, and that it is a feedback loop rather than a
fault.

The discipline. Change one thing, wait for it to settle, read, record.

## What does not transfer

**Every number.** All of it is fitted to a plant that was invented. The
real engine has its own volumetric efficiency surface, its own MBT, its
own knock limit, and none of them are these.

**The trigger configuration.** The crank tooth count, the gap position
relative to cylinder one, and the cam phasing in this repository are
placeholders. Nothing else you calibrate means anything until those are
measured, because if the gap-to-TDC number is wrong then every spark
lands somewhere other than where the table says.

**The injector and pump data.** Also placeholders. Data sheets and a
scope, not guesses.

**Consequences.** Here you can command forty degrees at full boost and
watch a counter increment. There, a few cycles of heavy detonation is a
piston.

## The order on a real engine

Everything below is in `docs/ultracode-plan.md` under Real-car gates.
The short version:

1. **Measure what is measurable before calibrating anything.** Trigger
   pattern, injector flow and dead time, sensor scaling, fuel pressure.
   These are facts, not choices. An error here gets absorbed into every
   table you subsequently build and reappears the moment conditions
   change.

2. **Crank it with the coils and injectors unplugged.** Confirm the
   decoder syncs on the real wheel and the cam phase is right. If the
   trigger numbers are wrong you find out here, with nothing able to
   fire.

3. **Set base timing with a timing light.** Until commanded advance and
   actual advance agree, your spark tables are fiction.

4. **First start, idle, warm up.** Watch coolant, watch rail pressure,
   get closed loop lambda working.

5. **Volumetric efficiency on the road.** You need a wideband sensor
   and nothing else. No load control required.

6. **Part-load MBT on the road**, using the trick that does not need a
   dyno: at a steady speed the torque is fixed by the road load, so
   sweeping spark does not change torque, it changes the air required
   to hold that speed. MBT is where that requirement is at a minimum,
   and this ECU already computes required air.

7. **The knock limit last, with load you control**, and with real knock
   detection working. This is the one part that genuinely wants a dyno,
   or at minimum a hill, a tall gear, and a great deal of caution.

## What is still missing from this ECU

Be clear-eyed about it. As of this course being written there is no
cold start strategy, no acceleration enrichment, no closed loop lambda,
no knock signal processing, no cam control, no throttle position
controller, no sensor fault handling, no CAN link to the transmission,
and no hardware layer for the target processor. The list is in the plan
document.

The calibration knowledge from this course is portable to any of those
systems. The software is not finished, and knowing which is which is
the most useful thing to take away from fifteen sessions.

## Final question

You have a freshly assembled B48, this ECU, a wideband sensor and a
week. What do you do first, and what do you refuse to do at all until
something else is true?
