# ADR 0001 — Torque structure vs. load tables

**Status:** proposed
**Decides:** whether the core control strategy reasons in torque or in VE/load tables

---

## Context

A conventional aftermarket ECU is a load-table machine: RPM and load index into
a VE table and a spark table, and every feature is a modifier stacked on top. An
OEM ECU is a torque-structure machine: pedal becomes a torque request, all
influencers arbitrate into one coordinated target, and only then is it converted
to air, fuel and spark setpoints.

Torque structure is **not required** to ship a product — MaxxECU controls a
ZF8HP well from a VE-table architecture with a single-scalar torque estimate.
This is a cost/benefit decision, not a feasibility one.

## Pros

**1. Torque consumers compose instead of colliding.**
Traction control, launch control, cruise, speed and pit limiters, anti-lag,
idle, and shift torque reduction all want to influence engine output. In a
load-table ECU each is a bolt-on with its own retard or cut table, and they
interact badly — two features cutting simultaneously deliver roughly double the
intended cut, with no single place that knows. In a torque structure they are
requestors into one arbitration, resolved once, coherently, with priorities.
This is the most underrated benefit and it compounds with every feature added.

**2. Shift coordination that stays honest.**
An airflow-derived scalar estimate does not see spark retard, so it misreports
exactly during the shift that requested the cut. A structure models spark
efficiency and can report **available authority** — how much torque can be
removed right now given where spark already is. See
[transmission-control.md](../transmission-control.md#what-integration-actually-buys).

**3. Pedal feel becomes designable.**
Pedal-to-throttle-angle means the same pedal position produces wildly different
torque across RPM and boost. Pedal-to-torque produces a linear, predictable car.
This is a large and underappreciated part of why modern cars drive well.

**4. Boost control becomes a consequence, not a parallel system.**
Target torque implies required air charge implies wastegate position. No
separate boost-by-gear table fighting the fuel table.

**5. Protection strategies unify.**
Overboost, overheat, knock, low oil pressure all become torque limits that
arbitrate with everything else, rather than ad-hoc cuts that stack unpredictably.

**6. Hybrid torque blending has a seam to attach to.**
If an e-motor is ever added, the architecture already has the right place for it.

**7. Much of the work is already mandatory.**
The Level 2 safety monitor in
[architecture.md](../architecture.md#safety-concept) requires an independent
calculation of permissible torque, compared against torque actually produced.
Doing drive-by-wire responsibly means building most of a torque model regardless.

## Cons

**1. Calibration burden is the dominant cost.**
The model must hold across the whole operating space: air charge, spark
efficiency relative to MBT, lambda influence, cam position, friction and pumping
losses, temperature. That is a multi-dimensional map validated on a dyno, versus
a competitor's single calibration point. This is real money and real time, and
it is the main reason the aftermarket does not do it.

**2. Tuner adoption risk.**
The aftermarket tuning community is trained on VE and spark tables. Asking them
to calibrate a torque model while the ECU decides throttle position feels like
losing control of the car. This is a genuine commercial risk, plausibly the
actual reason incumbents stay with load tables.

**3. Legibility.**
More layers between pedal and actuator. "Why did it do that" becomes a question
about arbitration state rather than a table lookup. Load-table ECUs are easy to
reason about; that has real value during a track day at 11pm.

**4. Depends on a good air charge estimate.**
A torque model is only as good as the airflow model underneath it. Individual
throttle bodies, large cams, and heavy overlap make VE modelling poor — and
those are disproportionately the engines the aftermarket serves.

**5. More firmware surface.**
Arbitration, priorities, ramp rates, authority accounting, hand-back. Bugs here
produce emergent behaviour that is hard to reproduce.

**6. Slower to first start.**
A load-table ECU can run an engine in a weekend. A torque structure needs its
model before it does anything useful.

## Decision

**Build it torque-structured, but as a layer over a conventional core, not
instead of one.**

- The VE/spark core exists and is directly tunable.
- A **direct mode** (pedal to throttle, tables rule) is always available, for
  bring-up, for poorly-modelled engines, and for tuners who want it.
- **Torque mode** engages once the model is calibrated, and is required for
  integrated transmission control and for the Level 2 safety monitor.

This retires cons 1, 2 and 6 — nothing is blocked on model calibration, and
there is an escape hatch for users and engines the model does not suit.

The framing that settles it: given the drive-by-wire safety monitor is
non-negotiable, the real choice is not "torque structure or not". It is
"build most of a torque model anyway and use it, or build it and throw it away".
