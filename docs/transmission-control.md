# Transmission Control

This is the differentiating subsystem. It is also two entirely different
products wearing the same name, and picking the wrong one first will sink the
schedule.

## Two approaches

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

### Recommendation

**Ship A for breadth, build B for one flagship.**

Supervisor mode for the common transmissions gets you a usable product and
real-world installs early. Direct control on a single well-chosen target proves
the hard capability and is the thing nobody else in the price bracket has.

The flagship should be the **ZF8HP**. It is everywhere (BMW, Dodge, Jaguar,
Chrysler, Ram, Audi), the aftermarket demand is enormous, the mechanical
internals are well documented, and its eight ratios and fast shift capability
show off good control in a way a four-speed cannot.

## Why integration beats two boxes

The standard aftermarket setup is an ECU from one vendor and a TCU from another,
exchanging a handful of CAN messages. This fails in a specific and consistent
way, and understanding it is the product argument:

**Torque reduction is a negotiation, and the two boxes are not speaking the same
language.** The TCU asks for "torque reduction" and the ECU applies a spark
retard from a table. Neither knows how much torque was actually removed, or
whether the engine had the spark authority to remove it (it may already be
retarded for knock, or at a hard limit). There is no feedback on delivery. The
timing is whatever the CAN cycle time happens to be, typically 10–20 ms, against
an inertia phase that lasts 200–400 ms and needs its ramp shaped.

**In an integrated torque structure, none of that is true.** The shift
controller places a torque request into the same arbitration everything else
uses. The engine side knows its current authority, reports back what it can
actually deliver, and the shift controller adapts its pressure trajectory
accordingly. The coordination happens at the internal task rate, not a bus
cycle. And crucially, when the engine *cannot* honour the request, the shift
controller finds out in time to do something about it instead of committing to a
pressure profile that assumed help it never received.

That is a measurably better shift, and it is not something a two-box setup can
retrofit.

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
