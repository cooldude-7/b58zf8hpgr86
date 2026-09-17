# L03 — Knock

## What it is

Normal combustion is a flame front travelling across the chamber at
tens of metres per second. Ahead of it sits unburnt mixture, the "end
gas", being compressed and heated both by the piston and by the
expanding burnt gas behind the flame.

If that end gas gets hot enough for long enough, it ignites on its own,
all at once, before the flame reaches it. That is knock.

The problem is not that it burns. It is that it burns everywhere
simultaneously instead of progressively. A normal burn is a controlled
pressure rise over forty degrees of crank rotation. Autoignition is a
near-instantaneous release that sends pressure waves ringing across the
chamber at the speed of sound, which is what you hear as the metallic
rattle.

## Why it destroys engines

Three mechanisms, in increasing order of how quickly they kill:

**Pressure spikes** far above what the design expects, hammering the
bearings and the ring lands.

**The pressure waves scrub away the boundary layer** of stagnant gas
that normally insulates the piston crown from the combustion heat.
Without it, heat goes into the aluminium instead of the gas. This is
the one that melts piston crowns, and it is why knock damage looks like
erosion rather than cracking.

**Pre-ignition**, which is a different and much worse thing that knock
can lead to. Something in the chamber gets hot enough to light the
mixture before the spark. Now you have combustion starting early,
raising temperature, making the hot spot hotter, which makes it start
earlier still. That runs away in a handful of cycles and there is no
ECU response fast enough to save it.

## What sets the limit

End gas autoignites if it is hot enough for long enough. Everything
that matters follows from that:

- **Load.** More air means more pressure means more temperature.
  Knock margin shrinks as boost rises, which is why the knock table
  falls steeply with manifold pressure.
- **Speed.** At high rpm there is less real time per crank degree, so
  the end gas has less time to autoignite before the flame arrives.
  Higher speed usually means more knock margin, not less.
- **Charge temperature.** Directly. A hot day, a heat-soaked intake, a
  failing intercooler all cost you timing.
- **Mixture.** Extra fuel evaporates and cools the charge, which is why
  full load runs rich. This is a large effect.
- **Fuel.** Which brings us to octane.

## Octane is resistance to autoignition, not energy

This trips everybody up at first. High octane fuel does not contain
more energy. It contains less tendency to spontaneously ignite under
heat and pressure.

The useful analogy: low octane is gunpowder, willing to go off if you
look at it wrong. High octane is a fuse, which burns steadily when lit
but does not care about being hot. What you want is a fuel that will
propagate a flame nicely from the spark but will not decide on its own
to let go.

That resistance is worth timing. A more knock-resistant fuel lets you
run closer to MBT, and closer to MBT is more torque. That is the entire
mechanism by which better fuel makes power: not more energy, more
timing.

Ethanol does this twice over. It has a high octane rating, and it also
has a much higher latent heat of vaporisation than petrol, so it cools
the charge substantially as it evaporates. Cooler charge, less knock,
more timing.

## The knock limit versus MBT

At light load MBT is reachable and knock is irrelevant. As load rises,
the knock limit falls faster than MBT does, and at some point it drops
below. From there on, the engine never sees MBT. The spark it runs is
whatever the knock limit allows, and the MBT table above that load is
theoretical.

This is why a boosted engine is calibrated around knock and not around
peak torque timing, and why Lab 3 matters more than Lab 2 for what you
are building.

## Detection

A knock sensor is an accelerometer bolted to the block, listening for
the chamber's ringing frequency, typically somewhere between five and
eight kilohertz depending on bore size. The signal processing is not
optional and it is not trivial:

- **Window** the measurement to the crank angles where knock can
  occur, because the rest of the cycle is full of valve and injector
  noise.
- **Filter** to the resonant frequency band.
- **Compare against a rolling background level** per cylinder, because
  an engine gets noisier with speed and load, and a fixed threshold
  will either miss knock at high load or cry wolf at idle.

When it fires, the response is to retard that cylinder immediately and
give the timing back slowly. Fast out, slow in: you want to escape
quickly and approach cautiously.

## Look at this in the app

Drive the simulator at full load in dyno mode and watch **Knock count**
and **Knock retard** in the datalog. Then advance the Knock Limit table
by five degrees and watch what happens.

Note that knock retard is a feedback loop, not a fault light. It pulls
timing and gives it back continuously. If it is permanently active your
table is wrong, not your engine.

## Questions to be able to answer

1. Why does knock margin generally improve at higher engine speed?
2. Why does running rich at full load buy you timing?
3. Two fuels have identical energy content but different octane. Which
   makes more power in a boosted engine, and by what mechanism?
4. Why must a knock detector be windowed to crank angle rather than
   simply listening all the time?
