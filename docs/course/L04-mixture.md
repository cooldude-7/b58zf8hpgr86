# L04 — Mixture

## Lambda, not air-fuel ratio

Stoichiometric is the mixture where there is exactly enough air to burn
all the fuel with nothing left over of either. For pump petrol that is
about 14.5 parts air to one part fuel by mass.

Lambda is your actual ratio divided by that one:

| Lambda | Meaning |
|---|---|
| 1.00 | stoichiometric |
| below 1.00 | rich, excess fuel |
| above 1.00 | lean, excess air |

Use lambda rather than the raw ratio because the raw ratio depends on
the fuel. E85 is stoichiometric near ten to one, methanol lower still.
Lambda 0.85 means the same physical thing on any of them: fifteen
percent more fuel than the chemistry needs. Change fuel and your lambda
targets survive; your air-fuel numbers do not.

## Where best torque is

Not at stoichiometric. Best torque is slightly rich, around lambda
0.88, and the curve either side of it is gentle. In this repository
that is `lambda_efficiency` in `tqmodel/model.py`.

The reason is that combustion is not perfectly mixed. A slight excess
of fuel raises the probability that every oxygen molecule finds a fuel
molecule to react with, at the cost of some fuel going out unburnt.
Beyond that you are just wasting fuel and cooling the charge.

## Why full load runs richer than best torque anyway

Production calibrations run high load richer than 0.88, often down
toward 0.80. Not for torque, for survival.

**Charge cooling.** Fuel that evaporates in the cylinder takes its
latent heat from the charge. A cooler charge resists knock, and knock
resistance buys timing, and timing is torque. Below about lambda 0.88
you are losing a little combustion efficiency and gaining more back in
spark advance. That trade is why it is done.

**Exhaust temperature.** Unburnt fuel leaving the chamber carries heat
with it that would otherwise be in the gas hitting the turbine wheel.
A turbine inlet temperature limit is a real constraint, and mixture is
the cheapest way to hold it.

## Why cruise runs at exactly 1.00

Because of the catalytic converter, which is doing two chemically
opposite jobs at once: stripping oxygen off nitrogen oxides, and adding
it to carbon monoxide and unburnt hydrocarbons. It can only do both
inside a very narrow window around stoichiometric. Outside it, one of
the two reactions stops.

At light load there is no heat problem and no knock problem, so there
is nothing to buy by going rich, and a catalyst and a fuel bill to pay
for it.

## The dangerous direction

Slightly lean of stoichiometric is the worst place to be under load.
The flame is slower and combustion temperature peaks there, which is
precisely the combination that produces knock and melts exhaust valves.
Far lean is actually cooler again, but the burn is too slow to be
useful and you will misfire before you get there.

So the mixture curve is not symmetrical in consequence. Two percent
rich costs you a little fuel. Two percent lean at full boost can cost
you an engine.

## Mixture as a measurement

The reason lambda gets so much attention in calibration is not only
that it matters, but that it is observable. A wideband sensor in the
exhaust reports it directly, cheaply and continuously.

That makes it the measurement by which airflow is calibrated, because:

```
lambda_measured / lambda_target  =  air_actual / air_estimated
```

You chose the target, you measured the result, and the ratio is
therefore the error in your airflow estimate. That equation is Lab 1
and most of your working life as a calibrator.

## Look at this in the app

Open the **Lambda Target** table. Notice it sits at 1.00 up to
atmospheric pressure and ramps richer as boost arrives, reaching the
mid eighties. That shape is the argument of this lecture drawn as a
surface.

## Questions to be able to answer

1. Why does the course tune's cruise target of 0.93 fail Lab 4?
2. Why is lambda 0.95 at full boost more dangerous than lambda 0.80?
3. You switch from petrol to E85 without changing the lambda table.
   What happens to the injected fuel mass, and why is the table still
   correct?
4. Derive the Lab 1 correction formula from the relationship above.
