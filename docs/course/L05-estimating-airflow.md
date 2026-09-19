# L05 — Estimating airflow

## The problem

Everything in L01 started with the mass of air trapped in the cylinder.
The ECU has to know that number, every cycle, before the intake valve
has even closed, because it has to decide how much fuel to inject and
it cannot wait to find out.

Nothing measures it directly. There is no sensor that reports grams per
cylinder per cycle. So the ECU estimates it, and the quality of that
estimate sets the quality of everything downstream.

## Speed density

The method this ECU uses. Measure manifold pressure and temperature,
which give you the density of the air available. Multiply by the
cylinder volume to get the mass that would be trapped if filling were
perfect. Multiply by a calibrated factor for the fact that it is not.

```
air = VE(rpm, MAP) × (Vd / n) × MAP / (R × T)
```

`Vd` is the engine's total displacement and `n` its cylinder count, so
`Vd / n` is the volume of one cylinder and `air` is the charge mass
trapped in one cylinder on one cycle. That is the quantity the injector
has to be sized against, which is why the ECU works in it rather than in
total flow. `MAP / (R × T)` is the ideal gas law: the density of the air
available to be trapped.

The calibrated factor is the volumetric efficiency table, and
calibrating it is Lab 1.

The alternative is a mass airflow sensor, a hot wire in the intake
measuring mass flow directly. It needs less calibration but it is a
restriction in the intake, it dislikes reversion pulses, it has to be
sized for the engine, and it measures flow into the engine rather than
flow into the cylinder, which differ during transients. Most standalone
systems use speed density. This one does.

## What the VE table absorbs

In principle the table describes cylinder filling. In practice it
absorbs every error in the chain:

- real filling efficiency, which is what it is supposed to hold
- errors in your injector flow number
- errors in your fuel pressure assumption
- manifold temperature not being charge temperature
- the manifold pressure sensor's calibration

This is why L05 comes with a warning. If your injector data is wrong by
five percent, the VE table will happily absorb that five percent and
look perfectly calibrated, right up until the fuel pressure changes and
the error reappears somewhere else.

Get the things that are measurements rather than choices right first:
injector flow and dead time, sensor scaling, fuel pressure. Then
calibrate VE. The order matters.

## Why lambda is the right measurement for it

You cannot measure air directly, but you injected a known mass of fuel,
and the exhaust tells you the ratio. Work backwards:

```
fuel injected  = air_estimated / (AFR × lambda_target)
lambda_measured = air_actual / (fuel injected × AFR)
```

Substitute and the injected fuel cancels:

```
lambda_measured / lambda_target = air_actual / air_estimated
```

The ratio of measured to target lambda is exactly the ratio of real
airflow to your estimate. So:

```
VE_new = VE_old × (lambda_measured / lambda_target)
```

That is the whole method. It converges in one pass because the
relationship is exact and linear, which you will see in Lab 1.

## Transients, and why this is only the steady-state answer

The equation assumes the manifold is in equilibrium. During a tip-in it
is not: pressure is rising, and the flow past the throttle is not yet
the flow into the cylinder. `tqmodel/dynamics.py` has the manifold
filling model that describes this properly.

There is a second transient problem this ECU does not yet address. On a
port injected engine, fuel puddles on the port wall and takes time to
evaporate, so a sudden throttle opening goes lean before the wall film
catches up. That is what acceleration enrichment compensates for, and
the navigator still says "todo" next to it. Direct injection reduces
but does not eliminate the problem.

Calibrate steady state first. Transient compensation on top of a wrong
steady-state table is guesswork.

## Look at this in the app

Open the **VE Table**. The surface rises into the mid range and falls
away at both ends. That is the breathing of the engine, and its shape
should look like the torque curve, because it is.

In `tuner/core/sim_ecu.py`, find `plant_ve`. That is the surface the
simulated engine actually has, and your table is not it. Do not read
the function if you want Lab 1 to mean anything.

## Questions to be able to answer

1. Why can the VE table be wrong and the engine still run acceptably?
2. Your injector flow number is ten percent too high. What does the
   calibrated VE table look like, and when does the error reappear?
3. Why does the correction formula converge in one pass rather than
   needing to be iterated?
