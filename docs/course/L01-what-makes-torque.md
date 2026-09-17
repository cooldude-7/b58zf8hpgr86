# L01 — What actually makes torque

## The one-sentence version

An engine is a machine that converts the chemical energy in fuel into
work on a crankshaft, and the amount of fuel it can burn is set by the
amount of air it can get into the cylinder.

Everything else in this course is a detail of that sentence.

## Air is the limit, not fuel

Fuel is cheap and a pump can deliver as much as you like. Air is what
you cannot have more of. Atmospheric pressure is fixed, the cylinder is
a fixed size, and it fills once every two revolutions. That is why
forced induction exists: a turbocharger is a device for getting more
air into the same cylinder, and the extra fuel simply follows.

So the first number in any engine calculation is the mass of air
trapped in a cylinder on one cycle. In this codebase it is in grams and
it is called air mass per cylinder per cycle.

```
air = VE × displacement_per_cylinder × pressure / (R × temperature)
```

The pressure and temperature terms are the ideal gas law: they tell you
the density of the air in the manifold. The displacement tells you the
volume. Multiply and you have the mass the cylinder would trap if it
filled perfectly.

`VE` is the correction for the fact that it does not.

## Volumetric efficiency

A cylinder does not fill to manifold density. Valves are only open for
part of the cycle, the gas has inertia, the ports have friction, and
some exhaust gas stays behind. Volumetric efficiency is the ratio of
what actually got trapped to what the geometry says should have.

Around 0.85 is typical at low speed. Near the torque peak it can exceed
1.0, because a well-designed intake resonates and rams charge in after
the piston has stopped drawing. That is what a torque curve is: a plot
of volumetric efficiency against engine speed, rescaled.

Two things about it that matter for the rest of the course:

**It is not a constant.** It varies with speed and with manifold
pressure, which is why it is a table and not a number.

**Boost is not in it.** Manifold pressure is already in the equation,
separately. A turbocharged engine at two bar has roughly the same
volumetric efficiency as the same engine at one bar, and twice the air.
Confusing the two is the most common beginner mistake in this subject.

## From air to torque

Once you know the air, the fuel follows from the mixture you want, and
the energy follows from the fuel. Petrol carries about 44 megajoules
per kilogram. An engine converts something like 35 to 40 percent of
that into work at its best.

```
fuel     = air / (stoichiometric ratio × lambda)
energy   = fuel × 44 MJ/kg
work     = energy × thermal efficiency
torque   = work per cycle / (4π)          [four-stroke: two revolutions]
```

That chain is implemented in `tqmodel/model.py` and it is the backbone
of the whole ECU. Look at `base_torque`.

## Why it is only the backbone

The chain above gives indicated torque at ideal conditions: perfect
spark timing, best-power mixture. Real torque is less, for reasons that
are the subject of the next three lectures:

- spark that is not at the optimum (L02)
- spark that cannot be at the optimum because the engine would
  detonate (L03)
- a mixture that is not at best power (L04)

and then friction, which is subtracted at the end and modelled here by
the Chen-Flynn correlation in `friction_torque`.

## Look at this in the app

Open the **Base Torque** table under Torque. Its axes are engine speed
and air mass, not manifold pressure. That is deliberate: torque follows
air, and air is where the pressure and temperature have already been
accounted for. The surface is almost a straight ramp in air, which is
the statement that a gram of air is worth a fixed amount of torque.

## Questions to be able to answer

1. Why does a turbocharged engine make more torque, in terms of the
   equation above?
2. An engine at 6000 rpm has a lower volumetric efficiency than at 4000
   but makes more power. How?
3. If you double manifold pressure and volumetric efficiency is
   unchanged, what happens to torque, and what happens to the fuel
   required?
