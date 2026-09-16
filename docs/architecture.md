# Architecture

## Why torque structure first

A conventional aftermarket ECU is a **load-table machine**. RPM and a load axis
index into a VE table and a spark table; every feature after that is a modifier
stacked onto those tables. It works, it is easy to tune, and it is a dead end
for anything that needs coordinated authority over the engine.

A modern OEM ECU is a **torque-structure machine**:

```
  pedal position ──► driver demand interpretation ──► driver torque request
                                                             │
  shift control ──────────────────────────────────────────┐  │
  traction control ───────────────────────────────────────┤  │
  cruise / speed limiter ─────────────────────────────────┤  │
  idle governor ──────────────────────────────────────────┤  │
  protection & limp strategies ───────────────────────────┤  │
                                                          ▼  ▼
                                                   torque arbitration
                                                          │
                                        ┌─────────────────┴────────────────┐
                                        ▼                                  ▼
                              slow path (air)                    fast path (spark/fuel)
                              throttle, wastegate,               ignition retard,
                              cam phasing, lift                  cylinder cut
                                        │                                  │
                                        └─────────────────┬────────────────┘
                                                          ▼
                                                  actuator setpoints
```

Two properties fall out of this that matter enormously:

**1. Shift torque reduction becomes ordinary.** During the inertia phase of an
upshift, the transmission needs crank torque pulled down hard for a few hundred
milliseconds so the oncoming clutch can synchronise without a flare or a bang.
In a torque structure that is one more requestor, arbitrated with proper
authority limits, ramp rates, and a defined hand-back. In a load-table ECU it is
a hack — a CAN message that triggers a fixed retard table, with no model of how
much torque was actually removed.

**2. The fast/slow path split is explicit.** Air is slow (throttle plate, turbo
inertia, manifold filling). Spark and fuel are fast (next combustion event).
Torque structure forces you to model both and to reserve spark authority so the
fast path always has room to act. This is exactly what shift control, traction
control, and knock protection all need.

The cost is that you need a **torque model** — an inverse map from desired
torque to air charge, and a forward map from air/spark/lambda to produced
torque. That is real calibration work and it is the main reason the aftermarket
mostly does not do it. It is also the moat.

## Module split

Monolithic single-box designs collapse under connector count, thermal load, and
the fact that every feature competes for the same board area. A modular
architecture over a private CAN-FD backbone lets each hard problem be developed,
revised, and destroyed independently.

```
                    ┌──────────────────────────────┐
                    │   Core Controller  (CCU)     │
                    │  torque structure, decode,   │
                    │  scheduling, calibration     │
                    │  + independent safety monitor│
                    └──┬────────┬────────┬─────────┘
                       │        │        │      private CAN-FD backbone
        ┌──────────────┘        │        └──────────────┐
        ▼                       ▼                       ▼
┌───────────────┐      ┌────────────────┐      ┌────────────────┐
│ GDI Driver    │      │ Transmission   │      │ Power Dist.    │
│ (GID)         │      │ Control (TCM)  │      │ (PDM, optional)│
│ boost conv.,  │      │ supervisor or  │      │ eFuses, solid- │
│ MC33816 x N,  │      │ direct control │      │ state switching│
│ HPFP loop     │      │                │      │                │
└───────────────┘      └────────────────┘      └────────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  vehicle CAN gateway  │
                    │  factory cluster,     │
                    │  ABS, body, OBD-II    │
                    └───────────────────────┘
```

**Core Controller (CCU)** — crank/cam decode, injection and ignition
scheduling, closed-loop control, the torque structure, calibration storage,
logging. This is where the intellectual property lives.

**GDI Driver Module (GID)** — deliberately separate. It carries a 60–70 V boost
converter and current-shaped injector drivers, which is a different discipline
(power electronics), a different thermal problem, and a different failure mode
from everything else. Isolating it means a blown driver stage does not take the
engine controller with it, and lets the GDI board go through its own PCB
revision cycle. Port-injection-only installs simply omit it.

**Transmission Control Module (TCM)** — see
[transmission-control.md](transmission-control.md).

**Power Distribution Module (PDM)** — optional, but modern swaps want it and it
is the easiest module to build.

## Bus topology

Three logically separate buses, minimum:

- **Private backbone (CAN-FD, 2/5 Mbit)** — inter-module traffic. Deterministic,
  known participants, tight cycle times for the torque coordination messages.
- **Vehicle bus (CAN / CAN-FD)** — the donor chassis. Gateway duty: synthesise
  the messages the factory cluster, ABS, and body modules expect so the car
  behaves normally. For swaps this is not a nicety, it is most of what makes the
  product usable.
- **Powertrain peripheral bus** — OEM mechatronic units, electric wastegate
  actuators, LIN thermal devices. Often has to be its own segment because you do
  not control the timing or the participants.

Keeping the backbone private is what lets you do 5 ms torque coordination
without a body module's chatter causing arbitration delay.

## Safety concept

You will not certify to ISO 26262 as a small team. You should still adopt its
structure, because drive-by-wire on a public road is the one place where "it's
open source, use at your own risk" is not an adequate answer.

Adopt the three-level monitoring concept:

- **Level 1 — function.** Normal control: the torque structure and its actuators.
- **Level 2 — function monitoring.** An independent calculation of permissible
  torque from pedal position and vehicle state, continuously compared against
  the torque actually being produced. Disagreement beyond a threshold and time
  triggers a defined reaction (torque limit, throttle limp, fuel cut).
- **Level 3 — controller monitoring.** A physically separate watchdog device
  that challenges the main MCU with a question-answer protocol, and that can
  **de-energize the throttle H-bridge and the injector supply without the main
  CPU's cooperation.** Not a GPIO the main CPU could hold high on its own.

Concretely, for DBW: dual redundant pedal sensors with opposing slopes, dual
redundant throttle position feedback, cross-plausibility checking on both, and a
hardware enable line gated by the Level 3 monitor.

This costs maybe 15% of the firmware effort and it is the difference between a
project people can responsibly drive and a project people can responsibly only
dyno.

## Modern-engine feature requirements

The floor for "runs a 2015+ engine":

- Direct injection, multiple events per cycle, plus **simultaneous port
  injection** — many modern engines have both (Toyota D4-S, VW EA888 Gen3) and
  the dual-injection blend is a real calibration axis.
- Closed-loop high-pressure fuel control, 150–350 bar, cam-synchronous.
- Up to four cam phasers, plus variable lift systems where feasible.
- Per-cylinder windowed knock detection with real frequency-domain analysis.
- Drive-by-wire, to the safety standard above.
- Electric wastegate actuators with position feedback; electric coolant pumps
  and map-controlled thermostats, often over LIN.
- CAN-FD, multiple buses, gateway and message synthesis.
- Flex fuel, and enough headroom to add hybrid torque coordination later — the
  torque structure already gives you the right place to put it.

## Deliberately out of scope (for now)

- **Valvetronic and equivalent proprietary lift systems.** Lock at full lift and
  use the throttle. Revisit once the platform runs.
- **Emissions compliance / OBD-II readiness monitors.** Diagnostics-capable, but
  not certified. Know your jurisdiction.
- **Dual-clutch transmissions.** Far harder than a torque-converter automatic —
  clutch handover with no converter to absorb error. Not a first target.
