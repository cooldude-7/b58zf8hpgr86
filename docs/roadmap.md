# Roadmap

Staged so that every phase produces something independently useful, and so the
reference car is **driving on its factory DME throughout** rather than waiting
years for the platform.

Exit criteria are deliberately concrete. A phase is done when its criterion is
demonstrably met, not when it feels close.

---

## Phase 0 — Reference car running

Get the B48 + ZF8HP into the GR86 on the **factory DME and factory mechatronic
unit**, with a bench harness and a CAN gateway feeding the factory cluster.

*Why first:* de-risks all the mechanical work, and gives you a known-good
reference to measure every later control decision against. Without it you will
be debugging your ECU and your engine installation simultaneously, and you will
not know which one is wrong.

**Exit:** car drives normally, factory cluster correct, baseline datalogs of
engine and transmission CAN traffic captured across the full operating range.

---

## Phase 1 — Gateway and observation

Build the CAN gateway/logger module as a standalone product.

Immediately useful (every swap needs one), teaches you the buses you will later
have to speak, and it is a low-risk first PCB to make manufacturing mistakes on.

**Exit:** gateway drives the GR86 cluster correctly from BMW powertrain CAN,
with full-rate logging of all three buses to removable storage.

---

## Phase 2 — Core EMS on a simple engine

Port-injected, naturally aspirated, no GDI. The FA20/FA24 you removed is ideal —
you already own it and its failure is cheap.

Validates crank/cam decode, sequential scheduling, closed-loop lambda, cam
phasing, DBW **including the full three-level safety monitor**, and the first
implementation of the torque structure.

*Do not skip the torque structure here because the engine is simple.* Phase 2 is
where it gets debugged in an environment where mistakes are survivable.

**Exit:** engine runs and drives on the new controller, fault injection on the
bench demonstrates correct Level 2 and Level 3 reactions, torque model validated
against a dyno.

---

## Phase 3 — Transmission supervisor

TCM in supervisor mode against the ZF8HP mechatronic unit. Implements the full
[integration contract](transmission-control.md#integration-contract),
including coordinated torque reduction, against a real transmission.

Bench first, then the reference car — which can now run its transmission on your
TCM while the engine is still on the factory DME, if the gateway work from Phase
1 is solid.

**Exit:** all gears, torque-coordinated shifts, lockup control, sane fault
handling and limp modes. Shift quality measurably comparable to factory.

---

## Phase 4 — GDI power stage

Bench only. Single injector, pressure rig, scope. Then multi-injector. Then
closed-loop HPFP control on a running engine.

Separable from everything above, which is the point of putting it on its own
board — it can be developed in parallel by someone else, or paused, without
blocking the platform.

**Exit:** stable closed-loop rail pressure across the full flow range, correct
current shaping verified on a scope, multiple injection events per cycle at
redline flow.

---

## Phase 5 — Full integration on the reference car

B48 running entirely on the platform: GDI, DBW, cam phasing, electric wastegate,
Valvetronic locked, ZF8HP under supervisor control. Factory DME removed.

**Exit:** the reference car is a daily driver on the platform.

---

## Phase 6 — Deeper transmission control

Two candidate paths, and the cheaper one should be evaluated first.

**6a — OEM TCU reflash (evaluate first).** Replace the mechatronic unit's
firmware, keep ZF's hydraulic control, own the strategy layer. This is what
MaxxECU does, so it is proven reachable. Reaches most of the capability of
direct control for a fraction of the effort. Gated on reverse engineering and
on flashing tooling you do not control, and is variant- and generation-specific.

**6b — Direct mechatronic control.** Clutch-level control: fill learning, torque
and inertia phase management, line pressure, slip and lockup modulation,
adaptation. The only path with no ceiling, and a project comparable in size to
Phases 0–5 combined. Requires the transmission bench from
[hardware.md](hardware.md#bench-infrastructure) — it cannot be developed in a
car.

Enter 6b knowingly and late. It is not the opening move.

**Exit:** shift quality measurably exceeding supervisor mode, with calibratable
shift aggression.

---

## Notes on sequencing

Phases 1, 2 and 4 are genuinely parallelisable if more than one person is
working. Phase 3 depends on Phase 1. Phase 5 depends on everything. Phase 6
depends on Phase 3's interface contract being right, which is why that contract
is worth over-thinking now — both 6a and 6b must sit behind the same interface.

The realistic honest estimate for Phases 0–5, for one competent person working
evenings and weekends, is **several years**. Phase 6 is a project of comparable
size to all of the preceding phases combined.

The staging is designed so that abandoning the project at the end of any phase
still leaves something working and worth having.
