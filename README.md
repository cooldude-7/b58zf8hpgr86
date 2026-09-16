# Open Powertrain Controller (working title)

A standalone engine management system for **modern** engines, with
**transmission control as a first-class part of the architecture** rather than a
bolt-on.

Status: **architecture / pre-hardware.** Nothing here is built yet. These
documents exist to make the expensive decisions before any PCBs are ordered.

## Thesis

The aftermarket is well served at the "run an old port-injected engine" end and
at the "$8k professional motorsport ECU" end. The gap is a controller that
handles what a 2015+ factory engine actually does — direct injection, variable
lift, drive-by-wire, electric boost and thermal actuators, CAN-FD body
integration — *and* controls the automatic transmission bolted to it, with the
engine and transmission sharing one coordinated torque model.

That last clause is the whole product. See
[docs/architecture.md](docs/architecture.md#why-torque-structure-first).

## The one decision everything else depends on

Build the control strategy in the **torque domain**, not the load-table domain.

Pedal position becomes a *torque request*. Every other subsystem that wants to
influence the engine — shift control, traction control, cruise, idle, limp
modes — becomes another *torque requestor*. An arbitration layer resolves them
into a single coordinated target, which is only then converted into air, fuel
and spark setpoints.

This is how OEMs do it, and it is the reason a factory automatic shifts better
than an aftermarket ECU bolted to an aftermarket TCU. The transmission's request
for a torque cut during the inertia phase of a shift is not a special case — it
is just another requestor, arbitrated with correct authority limits and ramp
rates.

Load-table-first architectures cannot retrofit this. Torque-first gets
integrated transmission control almost for free.

## Document map

| Document | Covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Torque structure, module split, CAN backbone, safety concept |
| [docs/transmission-control.md](docs/transmission-control.md) | Supervisor vs. direct mechatronic control, what shift control actually requires |
| [docs/hardware.md](docs/hardware.md) | MCU selection, GDI power stage, I/O budget, per-module sketches |
| [docs/roadmap.md](docs/roadmap.md) | Staged milestones with exit criteria |

## Reference target

First integration target is a **BMW B48 + ZF8HP in a GR86/ZN6 chassis** — the
build that prompted this project. It is a good forcing function: direct
injection, Valvetronic, DBW, electric wastegate, and a factory-paired 8-speed
automatic whose mechatronic unit speaks CAN. If the platform can run that, it
can run most of the 2015+ field.

## Scope warning

This is a multi-year project that spans embedded firmware, power electronics,
control theory, and protocol reverse engineering. The roadmap is staged so that
each phase produces something independently useful and testable, and so the
reference car is driving on its factory DME the entire time rather than sitting
on jackstands waiting for the platform to mature.
