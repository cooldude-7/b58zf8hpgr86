# Torque Model — Implementation Notes

The equations, the inverse path, and the things that bite when writing them.
Read [what-it-does.md](what-it-does.md) first for the overall shape.

## Forward model

```
air  = VE(rpm, MAP, cam_in, cam_ex) × (Vd / n) × MAP / (R · T_charge)

T_ind = BaseTorque(air, rpm)                 ← measured at MBT, λ=1
        × SparkEff(MBT − spark)
        × LambdaEff(λ)

T_brake = T_ind − FrictionTorque(rpm, load, temp)

T_crank = T_brake − AccessoryLoad             ← what the transmission wants
```

`Vd` is total displacement and `n` the cylinder count, so `air` is the
charge mass in one cylinder on one cycle -- what `tqmodel.model.air_mass`
and `fw/src/model.c` both return, and what an injector is sized against.

`SparkEff` and `LambdaEff` are near-universal curves — ship defaults, verify on
a dyno, do not author from scratch. `FrictionTorque` is a Chen-Flynn
correlation with four fitted coefficients, not a map.

## Inverse model

Control needs this direction, and it is not optional:

```
air_required = inverse_BaseTorque(
                   torque_target / (SparkEff(planned spark) × LambdaEff(λ))
               )
```

The divisor uses the spark the controller **plans** to run, not necessarily
where spark is right now. Two consequences:

- Knock-limited and retarded → the air requirement rises for the same torque.
  This is why a knock-limited turbo engine raises boost to hold a target. It
  falls out of the model, it is not a separate strategy.
- **Torque reserve** is created here: deliberately plan retarded spark, and the
  inverse model requests more air than the MBT case needs. Advancing back
  toward MBT then releases torque on the next combustion event.

`BaseTorque` must be monotonic in air mass so this inverts cleanly. Where an
analytical inverse is not available you are doing a numerical solve every
cycle — budget for it, or design the map to avoid it.

## Fast path and slow path

```
torque target
  ├─► slow path: air   (throttle, wastegate, cam phasing)   — 100s of ms
  └─► fast path: spark (retard, then cylinder cut)          — next event
```

Route by urgency. Driver demand and cruise go to air. Shift cuts and traction
control go to spark, because air physically cannot move in time.

Spark runs out of range around 50% torque reduction (~30° retarded); beyond
that combustion destabilises and EGT becomes destructive. For deeper cuts add
cylinder cut, and cut **fuel**, not spark — cutting spark with fuel flowing
sends raw fuel into the catalyst.

## The air-chase failure

The single most important coordination rule, and the easiest bug to write.

During a shift cut the air path must **hold**, not compensate:

```
WRONG:  air = driver_demand / SparkEff(current spark, including the cut)
RIGHT:  air = driver_demand / SparkEff(nominal spark, excluding the cut)
```

Getting this wrong, with a 400 Nm cruise and a cut to 150 Nm:

| | Air | Spark eff. | Torque |
|---|---|---|---|
| Before shift | 400 | 1.0 | 400 |
| Correct — hold | 400 | 0.375 | **150** ✓ |
| Bug — chase | 750 | 0.375 | 280 ✗ |

Two harms, at two different moments. **During** the shift the cut is diluted,
so the clutch absorbs far more energy than the pressure trajectory assumed —
slip, flare, heat. **After** the shift, spark returns to MBT while the extra air
is still in the manifold, so torque overshoots above where it started. Jerk.

Air is slow in both directions, so the overshoot rides out well past the shift.

Holding the air is also what keeps the turbo lit through the shift, so torque
returns on stored boost rather than after a re-spool.

Freeze or heavily rate-limit the air request for the duration of the shift.
Engine speed is falling fast during the inertia phase and you do not want the
air target wandering while the clutch is doing precise work.

## Coordinated shift sequence

1. Trans requests a cut — magnitude, ramp rate, duration
2. ECU reports **available authority**; trans commits its pressure trajectory
   against that promise
3. Spark retards. **Air freezes.**
4. Inertia phase — the clutch absorbs engine torque *plus* the kinetic energy
   released by decelerating the engine down the ratio step
5. Trans signals completion and requests a ramp-back slope
6. Spark ramps to MBT beneath the clutch's rising capacity. Air unfreezes

The asymmetry matters: **the cut goes in fast, the restore comes back slow.**
Going down, torque must be gone before the clutch starts work. Coming up, it
must arrive behind the clutch's capacity, and slowly enough not to shock the
driveline. So a torque request carries a ramp rate, not just a value.

## Implementation gotchas

**Conventions, fixed before the first line.** Spark sign (`degrees BTDC,
positive = advanced`, and never deviate). Air mass per cylinder per cycle
versus engine total versus mass flow. Nm, absolute pressure, lambda not AFR.

**Report the right torque.** The transmission wants crank torque net of
accessory loads. An A/C compressor cycling in is 5–15 Nm of otherwise
unmodelled error in the signal the transmission is trusting.

**Manifold filling dynamics.** The VE equation is steady-state. During a
transient the air actually entering the cylinder is not what it says. Model the
manifold as a control volume:

```
dm/dt = flow_in(throttle, upstream P) − flow_out(engine pumping)
```

First order and cheap. Without it the torque estimate is worst during tip-in,
shifts and traction events — exactly when it is being relied on.

**Phase-align to combustion events.** The air producing torque now entered the
cylinder an intake stroke ago; the MAP reading now is not the MAP that filled
this cylinder. Timestamp by engine event, not by task tick. Misalignment
produces errors that look like calibration error and waste weeks.

**Define the edges.** Overrun and fuel cut (indicated torque zero, reading pure
friction — negative torque is a distinct mode, not a small number), near-zero
air, WOT, cranking, and cold engine, where friction is much higher than the
warm-fitted coefficients assume.

**Latency is a budget.** Every filter costs phase lag. Choose time constants
against the ~300 ms shift window, not in isolation.

**Float versus fixed point, decided early.** The inverse model divides.
Retrofitting fixed-point into a model written in floats is miserable.

## Build order

Write the whole model in Python or MATLAB first and validate it offline against
the **Phase 0 factory DME logs** — compare computed torque against BMW's
broadcast torque across the operating range. Iterate where there is plotting, a
debugger, and no flash cycle.

Port to firmware only once the model is right. This is the strongest single
argument for doing Phase 0 properly.
