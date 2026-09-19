# What This ECU Does

The one-page version. Everything else in `docs/` elaborates on this.

## Core idea

**Torque is the currency.**

The pedal does not ask for a throttle opening. It asks for Nm. So does every
other subsystem that wants to influence the engine. One arbitration layer
resolves them all into a single target, and only then does the controller work
out what the actuators should do.

## The loop

```
pedal  ─┐
shift  ─┤
trac.  ─┼──► arbitration ──► torque target ──► inverse model ──► actuators
idle   ─┤                                            │
limits ─┘                                            ├─► slow path: air
                                                     │   (throttle, wastegate, cams)
                                                     └─► fast path: spark
                                                         (retard, cylinder cut)

forward model ──► torque produced + authority remaining ──► feedback + CAN
```

Path selection is by urgency: air for steady requests, spark for anything
needed in under ~100 ms.

## The math

```
air = VE(rpm, MAP, cams) × (Vd / n) × MAP / (R · T_charge)

T   = BaseTorque(air, rpm) × SparkEff(MBT − spark) × LambdaEff(λ) − friction
```

## Calibration

| Item | Source |
|---|---|
| VE | Measured — engine-specific, the main job |
| MBT | Measured — stored **separately** from the knock limit |
| Base torque | One dyno pass, seeded from compression ratio |
| Friction | Four Chen-Flynn coefficients |
| Spark & lambda curves | Shipped as defaults, verified not authored |

## Rules that must not be broken

1. **MBT is the reference.** It anchors both the torque magnitude (base torque
   is measured at MBT) and the zero point of the spark efficiency axis. An error
   in MBT corrupts the torque number *and* the authority estimate.

2. **Store MBT and the knock limit separately.**
   `actual spark = min(MBT, knock limit) − margin`.
   Collapsing them into a single spark table is what makes a conventional ECU
   structurally unable to report authority — it forgets where MBT was.

3. **VE must be physically true, not merely self-consistent.** Characterise
   injectors independently so their error cannot hide inside the VE table. A
   VE number that produces correct fueling can still be wrong, and in torque
   mode that error propagates straight to the transmission.

4. **The model must run backwards.** Torque → air → throttle. Decide the
   inversion strategy before writing firmware, not after.

5. **It is an estimate, not a measurement.** There is no torque sensor. Validate
   against a dyno, cross-check against vehicle acceleration and known inertia,
   and keep the Level 2 safety monitor an genuinely independent calculation.

6. **Bias the estimate high.** Under-reporting torque makes the transmission
   under-pressurise and slip a clutch. Over-reporting only makes shifts firm.
   The consequences are asymmetric.

## Why it differs from what exists

| | Torque |
|---|---|
| Speeduino | No concept of it |
| MaxxECU | A **readout** — airflow × one scalar, computed live but blind to spark, then mailed out on CAN |
| This | A **command** — on the control path, driving the actuators |

> A VE-based ECU can tell you what torque it is making.
> This one can be told what torque to make.

Both compute torque continuously. The difference is that one of them acts on it.

## What that buys

- Coordinated shift torque reduction with a real **available authority** signal
- Traction control, launch, cruise and limiters that compose instead of colliding
- Pedal feel as a design parameter rather than a consequence of throttle geometry
- **Torque reserve** — deliberately retarded with extra air, so torque can be
  added on the next combustion event. Rock-steady idle under load steps, and
  catalyst heating without the idle collapsing.
- Flex fuel as a single parameter rather than a duplicate calibration set
