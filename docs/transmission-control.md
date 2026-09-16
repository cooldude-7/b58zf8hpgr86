# Transmission Control

This is the differentiating subsystem. It is also three entirely different
products wearing the same name, and picking the wrong one first will sink the
schedule.

## Three approaches

### A. Mechatronic supervisor

Leave the OEM transmission controller in place and talk to it over CAN. You
send it engine speed, produced and requested torque, pedal position, brake
state, and gear requests. It runs its own clutch pressures, shift scheduling,
and adaptation.

**Cost per transmission:** protocol reverse engineering. Realistically 2–6
months for a transmission with an active community (ZF8HP, ZF6HP, GM 8L90), much
longer for something obscure.

**What you get:** OEM shift quality and OEM adaptation, immediately. The
mechatronic unit has decades of calibration baked into it.

**What you give up:** you can only ask for what the OEM protocol exposes.
Aggressive shift calibration, custom shift maps, and motorsport behaviour are
bounded by what the factory unit will accept. You are also permanently exposed
to variant differences — the same physical transmission with different firmware
may speak a meaningfully different dialect.

### B. Direct mechatronic control

Drive the solenoids yourself. You own line pressure, clutch fill, the torque
phase and inertia phase of every shift, slip control, lockup modulation, and
adaptation.

**What this actually requires:**

- **Turbine/input speed sensing** in addition to output shaft speed. Without
  input speed you cannot measure slip, and without slip you cannot close the
  loop on a shift.
- **Clutch fill modelling.** An oncoming clutch has to be stroked to the kiss
  point before it can carry torque. Fill time varies with temperature, line
  pressure, wear, and how long the clutch has been released. Get it wrong and
  you either flare (underfill) or bind (overfill). Every OEM does adaptive fill
  learning; you will have to as well.
- **Torque phase management.** Handing torque from the offgoing to the oncoming
  clutch without a dip or a bump, which means controlling two pressures against
  each other while the engine is still making its own contribution.
- **Inertia phase management.** Pulling engine speed down the ratio step at a
  controlled rate — this is where the coordinated torque request to the engine
  does its work.
- **Line pressure control** as a function of torque, temperature, and gear, with
  enough margin to avoid slip and little enough to avoid parasitic loss and
  harshness.
- **Thermal modelling** of clutch energy so you can protect the pack.

This is where the real product is, and it is a multi-year control problem on its
own. It is also unforgiving: a bad calibration destroys a transmission, and
transmissions are expensive.

### C. OEM TCU reflash

Keep the OEM mechatronic hardware, but replace its firmware with your own. You
inherit ZF's validated low-level hydraulic control — clutch fill, pressure
control, the adaptation machinery — while owning the strategy layer above it:
shift scheduling, shift points, mode logic, and special functions.

**Prior art: this is what MaxxECU does.** Their GEN1 8HP support reflashes the
stock TCU using a Yanhua ACDP-2 tool, giving "more direct control of actuators,
clutches and other internal components." That buys them adjustable shift points
to 9000 rpm, a transbrake with bump, kickdown, and virtual clutch / clutch-kick
functions — none of which a supervisor could obtain through the OEM protocol.
See <https://www.maxxecu.com/features/8hp_gearbox>.

**Cost:** reverse engineering proprietary firmware, plus specialised flashing
tooling. Per transmission variant, and generation-locked — GEN1 support does not
imply GEN2.

**What you give up:** the OEM hydraulic control strategy is still the OEM's. You
can schedule shifts however you like, but you cannot fundamentally change how a
clutch handover is executed. Also: flashing OEM firmware is legally grey in most
jurisdictions and dependent on third-party tooling you do not control.

### Comparison

| | A. Supervisor | C. Reflash | B. Direct control |
|---|---|---|---|
| Low-level clutch control | ZF's | ZF's, retained | Yours, from scratch |
| Strategy layer | OEM's | Yours | Yours |
| Effort | Months | Months + reverse engineering | Years |
| Ceiling | OEM protocol | OEM hydraulics | None |
| Risk | Low | Legal/tooling dependency | Destroyed transmissions |

### Recommendation

**Ship A for breadth, evaluate C for the flagship, hold B as the long goal.**

C is almost certainly the right flagship approach rather than B. It reaches
most of the capability for a small fraction of the effort, and it is proven in
the market. B remains the only path with no ceiling, but it should be entered
knowingly and late, not as the opening move.

Original framing, retained for the record:

supervisor mode for the common transmissions gets you a usable product and
real-world installs early; direct control on a single well-chosen target proves
the hard capability. That second half is now better served by C in the near
term.

The flagship should be the **ZF8HP**. It is everywhere (BMW, Dodge, Jaguar,
Chrysler, Ram, Audi), the aftermarket demand is enormous, the mechanical
internals are well documented, and its eight ratios and fast shift capability
show off good control in a way a four-speed cannot.

## What integration actually buys

An earlier draft of this document claimed that a coordinated torque structure is
what makes integrated transmission control *possible*. That is too strong, and
the counterexample matters.

**MaxxECU is not torque-structure based.** Its
[main fuel table](https://www.maxxecu.com/webhelp/settings-tuning-main_fuel_table.html)
is a conventional VE table with a lambda target table. Torque is *derived* from
it via a single scalar "Torque Factor", calibrated from one point on a dyno run.
There is no driver-demand interpretation and no arbitration layer — torque is an
observer hanging off the airflow model, not the currency the controller reasons
in. And MaxxECU ships well-regarded 8HP control regardless.

So the honest claim is narrower:

> You need *a torque estimate* to control a modern automatic. You do **not**
> need a torque structure to ship. The structure is a quality and robustness
> argument, not a feasibility argument.

### Where the estimate-only approach runs out

A single scalar factor scaling off VE is essentially an **airflow-proportional**
torque estimate. That is fine at steady state near the calibration point. It
degrades in exactly the conditions a shift creates:

- **Spark retard removes torque without changing airflow.** Unless a spark
  efficiency correction is layered on top, the estimate does not see the very
  torque reduction the shift requested. The signal is least trustworthy at the
  moment it matters most.
- **Cam phasing, lambda, and charge temperature** all change produced torque for
  the same VE, and a one-point calibration cannot track them.
- **There is no authority concept.** The estimate says what torque *is*. It
  cannot say what torque the engine *could remove right now* — which depends on
  how much spark advance is left after knock retard, limits, and protection
  strategies have taken their share.

### The signal that only a structure can provide

The field in the contract below that a load-table ECU structurally cannot
populate honestly is **available authority**: "here is how much torque I can
remove right now on the fast path, given where spark already is."

Without it, a shift controller commits to a pressure trajectory assuming a
torque cut it may not receive, and finds out only from the resulting slip. With
it, the shift controller plans against what is actually on offer, and degrades
gracefully when the answer is "not much."

That is a real edge. It is also a narrower one than the earlier draft implied,
and the bar is higher than "nobody does this" — the incumbent already delivers
shift quality most users are happy with. Differentiation has to be argued on
robustness across operating conditions, not on capability that does not exist
elsewhere.

## Integration contract

Whether the TCM runs supervisor or direct mode, its interface to the core
controller should be identical. Sketch:

**TCM → CCU**
- Torque request (value, ramp rate, duration, priority)
- Shift in progress / phase indication
- Current and target gear, ratio
- Torque converter state, lockup slip
- Transmission oil temperature
- Fault state and requested degradation level

**CCU → TCM**
- Produced torque estimate, and **available torque authority** (fast path and
  slow path separately — the distinction matters)
- Engine speed, engine acceleration
- Driver torque request, pedal position and rate
- Vehicle speed, brake state
- Engine operating mode, protection state

The critical field is **available authority**. "Here is how much torque I can
pull right now, on the fast path, given where spark already is." That single
signal is what a two-box setup structurally cannot provide, and it is what lets
the shift controller plan rather than hope.

Defining this contract early, and holding both supervisor and direct
implementations to it, means the flagship direct-control work can drop in behind
a proven interface.
