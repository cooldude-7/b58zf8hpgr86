# L06 — The torque structure

## Two ways to build an ECU

**Load based.** The pedal maps to a throttle position. Throttle
position and engine speed give load. Load and speed index the fuel and
spark tables. The engine produces whatever torque it produces, and
nothing in the ECU knows what that number is.

**Torque based.** The pedal maps to a torque request in newton metres.
Everything the engine could be asked to do is expressed in newton
metres. Something arbitrates between the requests, and an inverse model
works out what air and spark would produce the winner.

The first is simpler. The second is what this project is.

## Why bother

Because the moment more than one thing wants to influence the engine,
a load-based ECU has no common currency for the argument.

Consider what wants a say: the driver, the idle governor, the traction
control, the cruise control, the rev limiter, the catalyst heating
strategy, the air conditioning compressor, the alternator, and the
transmission during a shift. In a load-based system each of these is
a special case bolted onto the throttle or the spark, and they
interact in ways nobody designed.

In a torque-based system they are all requests in the same units. A
single arbitration step picks the winner, usually the minimum of the
limits and the maximum of the demands, and one inverse model turns the
answer into actuator commands. Adding a new participant is adding a
number to a list.

The transmission is the case that matters here. A transmission needs to
know how much torque is arriving at the input shaft so it can size its
clutch pressure, and it needs to be able to ask for less during a
shift. Both of those are trivial in newton metres and nearly
impossible in throttle percent. That is why factory automatic
transmissions ride on torque-based engine management, and why building
the 8HP onto this engine requires it.

## The chain

```
pedal position
    → driver torque request         (a pedal map)
    → arbitration                   (against limits and other requests)
    → torque target
    → inverse model                 (what air produces this, at the spark I plan to run?)
    → air target
    → throttle and wastegate
```

with spark running alongside as the fast correction, which is L07.

## The inverse model

The forward model says: given air, speed, spark and mixture, here is
the torque. The inverse says: given the torque I want, and the spark I
intend to run, how much air do I need?

Look at `required_air` in `tqmodel/model.py`. Note carefully what it
divides by:

```python
eff = spark_efficiency(mbt - planned_spark) * lambda_efficiency(lam)
t_at_mbt = t_ind_needed / max(eff, 1e-6)
```

It uses the spark the controller **plans** to run, not MBT. If you
plan to run retarded, you need more air for the same torque. That is
not a bug, it is the mechanism behind torque reserve: deliberately
carry extra air and hold it back with retard, so you can release it
instantly. Catalyst heating and idle stability both use it.

It is also the mechanism behind the failure in L12. If a shift cut is
allowed into that calculation, the air path sees "retarded spark, need
more air" and opens the throttle to compensate for a cut you asked for
on purpose.

## Two models, not one

A torque-based ECU needs the model to be good, and it also needs the
airflow estimate underneath it to be good, because the torque model
consumes air mass.

So there are two layers to calibrate, and they are the same two the
labs cover:

- **The VE table** decides how much air the ECU thinks it has. Wrong
  here and both fuelling and the torque estimate are wrong.
- **The spark tables** decide how much of that air's energy is
  harvested. Wrong here and the torque estimate is wrong even with
  perfect air.

The base torque table sits between them and is largely physics.

## Look at this in the app

The readouts under the gauges show **Torque**, **Requested** and
**Authority** side by side. Requested is what the arbitration settled
on, Torque is what the model believes is being made, and Authority is
the subject of the next lecture.

## Questions to be able to answer

1. Why does a load-based ECU struggle to coordinate with an automatic
   transmission?
2. Why does `required_air` divide by the efficiency of the planned
   spark rather than by MBT efficiency?
3. What is a torque reserve, mechanically, and what would you use one
   for?
