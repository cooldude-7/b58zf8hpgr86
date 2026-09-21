# The Project

Two products built on one engine model, in one repository.

**Lambda One** is tuning-education software: a desktop app with a simulated
engine whose true behaviour is hidden, so a student can learn to tune by
actually tuning rather than by watching someone else do it. This is the part
intended to be sold.

**TorqueTune** is a standalone engine management system for a modern
direct-injection, variable-valve, drive-by-wire engine — specifically a BMW B48
going into a GR86 — with transmission control designed in from the start rather
than bolted on. This is the long project.

They share a codebase because they share the physics. The tuner application does
not care whether it is connected to a simulated engine or a real one; the
simulator is simply one implementation of the same connection interface the real
ECU speaks. What a student learns in Lambda One is not a metaphor for tuning. It
is tuning, against an engine that happens to be made of arithmetic.

---

## 1. The idea everything hangs on

**Torque is the currency.**

Most aftermarket ECUs are organised around load tables: the pedal opens the
throttle, the throttle makes load, load indexes a fuel and spark table. That
works, and it is how the aftermarket has worked for thirty years.

This one is organised the way a factory ECU has been since the late 1990s. The
pedal does not request a throttle opening — it requests **newton-metres**. So
does every other subsystem that wants to influence the engine: the shift
controller asking for a torque cut, traction control, idle control, the rev
limiter, the safety monitor. An arbitration layer resolves all of them into one
coordinated target, and only then does an inverse model work out what the
actuators should do.

```
pedal  ─┐
shift  ─┤
trac.  ─┼──► arbitration ──► torque target ──► inverse model ──► actuators
idle   ─┤                                            │
limits ─┘                                            ├─► slow path: air
                                                     │   (throttle, wastegate, cams)
                                                     └─► fast path: spark
                                                         (retard, cylinder cut)
```

The reason this matters is the split at the bottom. Air is slow — the manifold
takes tens of milliseconds to fill or empty. Spark is instant. A gear shift
needs torque gone in milliseconds and back afterwards without a lurch, and that
is only expressible if both paths are driven by the same model of how much
torque the engine is currently making.

Full argument in [`docs/architecture.md`](docs/architecture.md) and
[`docs/decisions/0001-torque-structure.md`](docs/decisions/0001-torque-structure.md).

### The equation underneath it

Everything reduces to knowing how much air is trapped in a cylinder:

```
m_air = VE(rpm, MAP) × (Vd / n) × MAP / (R · T)
```

Volumetric efficiency is not calculated — it is *measured and calibrated*, which
is why a VE table exists at all and why filling one in correctly is the first
thing a tuner learns. Torque follows from air mass, corrected for how far the
spark is from MBT and how far the mixture is from stoichiometric.

---

## 2. Lambda One — the teaching product

### The problem it solves

Learning to tune is gated on having something to tune. A dyno session costs
hundreds of dollars an hour and a mistake costs an engine, so beginners learn by
watching videos and copying other people's maps, which teaches pattern-matching
rather than understanding.

The simulator removes the cost of being wrong. Blow it up, reload, try again.

### Why the engine is hidden and random

The simulator holds a **truth plant** — a real volumetric efficiency surface, a
real MBT timing surface, a real knock limit — that the tuner cannot see. The
student's tune is a separate set of tables which start wrong. Tuning is the
process of making one match the other using only the instruments a real tuner
has: measured lambda, knock events, torque.

Critically, **each installation gets its own engine**, generated from a seed
minted once per install. With a single shared plant, the first person to solve a
lab has solved it for everybody and "here is your engine" is a lie.

### What ships

- **9 calibration tables** — VE, lambda target, MBT spark, knock limit, base
  torque, boost target, and the direct-injection set (rail pressure target,
  injection timing, pilot fraction)
- **16 lessons** in `docs/course/`, from what makes torque through to the two
  control paths
- **6 graded labs** — VE, MBT, knock, lambda, shift coordination, direct
  injection — each graded against the hidden plant, which is the part no
  competitor can do, because grading requires knowing the right answer
- A live simulator with gauges, datalogging and a 3D surface view
- **Cell coverage and finding markers** on the table itself: which cells the
  engine has actually run in, and which are wrong and in which direction

### What it deliberately does not have

**Autotune.** Commercial tools will back-calculate VE corrections from measured
lambda and apply them for you. This one shows you the finding and makes you
apply it. The reasoning is that a student who presses a button has learned which
button to press; the point of the product is the other thing.

---

## 3. TorqueTune — the ECU

### Target

A BMW B48 (2.0 turbo, direct injection, Valvetronic, double VANOS, electric
wastegate) paired with a ZF 8HP automatic, going into a Toyota GR86. Chosen
because it is a genuinely modern engine: anything that can run a B48 can run
almost anything.

### Firmware

`fw/` is C, built two ways from one source tree. The **host** build swaps in a
software HAL so the whole control path can be compiled and tested on a PC; the
**target** build compiles for a Cortex-M7.

| Module | Responsibility |
|---|---|
| `decoder.c` | Crank and cam edges to engine position and cam phase. The only module allowed to say where the engine is, and the only one allowed to say it does not know. |
| `sched.c` | Angle-domain events to timer compares. Owns the rule that a charging coil always gets to fire. |
| `model.c` | The torque model, ported from the Python and checked against it. |
| `sensors.c` | ADC counts to physical units, with a plausibility check and a fallback chosen to fail in the safe direction. |
| `torque.c` | Pedal and idle to a torque target, and the inverse model back to an air mass and a manifold pressure. |
| `throttle.c` | Outer pressure loop, inner position loop, dual-sensor disagreement check. |
| `boost.c` | The wastegate, chasing the same pressure target the throttle does. |
| `fuel.c` | Charge mass to pulse width, plus the high-pressure pump loop. |
| `enrich.c` | Cranking, after-start, warmup and acceleration enrichment, and the decel cut. |
| `lambda.c` | Closed-loop fuel: a short-term PI trim over a long-term trim learned per cell. |
| `vanos.c` | Cam phaser control. |
| `aux.c` | Fuel pump, fan, tacho and lamp — including the rule that the pump stops when sync does. |
| `monitor.c` | Level 2 torque monitor — the safety layer. |
| `ecu.c` | Four-rate task structure: crank ISR, 1 ms, 10 ms, 100 ms. |
| `cal.c` / `proto.c` / `chan.c` | Calibration storage, the tuner link, and the live channel list the tuner reads its gauges from. |
| `hal/oc_core.c` | Output-compare scheduling as logic, separate from register writes, so the part that decides when a coil stops charging is testable. |

### Rules the firmware keeps

These are enforced, not aspirational:

- **Single precision everywhere.** The M7 has no double-precision unit, so a
  stray `double` becomes a library call inside a crank interrupt. CI
  cross-compiles against a single-precision-only FPU and greps the objects for
  `__aeabi_d*`, which turns the rule into something a script fails on.
- **No allocation, anywhere.**
- **Every timer comparison is a signed difference.** The microsecond counter
  wraps every 71 minutes and a bare `<` fails exactly once per wrap.
- **Nothing fires without 720° phase.** Crank sync alone would land half the
  sparks on an open intake valve.
- **Fuel is the fast cut.** Spark is only ever cut with fuel already off,
  because cutting spark alone pumps raw fuel into the exhaust and lights it
  there.

### Safety architecture

Three levels, following the structure production ECUs use:

1. **Level 1** — the functional control path.
2. **Level 2** — an independent torque monitor that computes what torque the
   pedal *permits* and shuts things down if the engine exceeds it. Dual pedal
   and throttle sensors, plausibility checked.
3. **Level 3** — a watchdog kicked only while the fast task is demonstrably
   still running, because a stopped fast task is precisely the failure the
   watchdog exists for.

---

## 4. Repository layout

```
tqmodel/     the torque model in Python — the reference implementation
tuner/       the desktop application (PySide6): tables, gauges, course, simulator
fw/          the ECU firmware in C, plus its HAL and tests
tools/       desk tools, including tools/trigger (scope capture -> decoder config)
docs/        architecture, roadmap, hardware, course material, decision records
tests/       Python test suites
```

Roughly 6,700 lines of C, 8,600 of Python, 6,000 of tests and 3,300 of prose,
across 71 commits.

### The Python is the reference

Where a module exists in both languages, **the Python is authoritative**.
`fw/tests/data/golden.txt` is generated from `tqmodel` and the C is checked
against it to 1e-4. If they disagree, the C is wrong.

This turns out to matter more than it sounds. Every module with an independent
cross-check has stayed clean; the defects found so far have all been in modules
that had none.

---

## 5. Honest status

### What is real

- The tuner application runs, loads and saves tunes, and talks to the simulator
  over the same protocol the real ECU speaks — `tests/test_serial_link.py` runs
  the actual firmware as a subprocess and drives it down a pipe.
- The full control path compiles and is tested on a PC: **321 Python tests and
  16 C suites**.
- The firmware **cross-compiles for Cortex-M7** under `-Wall -Wextra -Werror`
  with no double-precision calls.
- The whole chain from sensor counts to actuators exists and is under test:
  crank and cam decoding, angle-domain scheduling, the sensor layer, the torque
  coordinator and its inverse model, the throttle and wastegate loops, fuel,
  transient enrichment, closed-loop lambda, the pump, cam phasing, the auxiliary
  outputs and the Level 2 monitor.

### What is not real

- **Nothing has ever run on silicon.** The target build compiles but cannot
  *link*: there are no interrupt vectors, no linker script, no startup code and
  no clock tree. Those arrive with a board, and inventing them without one
  produces files that look finished and are wrong.
- **Every calibration in it is provisional.** The injector short-pulse curve,
  the dwell table, the sensor transfer functions and all of the loop gains are
  shaped correctly and sized by judgement. They are the sort of numbers that
  look finished, which is why each carries a comment saying what would replace
  it — a flow bench, a current probe, a known pressure.
- **There is no CAN layer and no calibration storage.** `hal_can_*` and
  `hal_flash_*` are declared and nothing calls them, so a tune lives in RAM.
- **The B48 trigger numbers are guesses.** BMW documents confirm the
  architecture but never publish the wheel geometry. `tools/trigger` exists to
  replace them from a scope capture, and `dec_config_t` carries a `measured`
  flag so the binary itself knows whether its numbers are measurements.

`tests/test_no_dead_interfaces.py` holds that list mechanically and fails the
build if it grows.

---

## 6. Roadmap

Staged so every phase produces something independently useful, and so the
reference car is **driving on its factory ECU throughout** rather than waiting
years for the platform.

| Phase | Goal |
|---|---|
| 0 | Reference car running on the factory DME, with baseline CAN logs captured |
| 1 | CAN gateway and logger, as a standalone product |
| 2 | Core EMS on a simple port-injected engine, including the full safety monitor |
| 3 | Transmission supervisor against the real ZF 8HP |
| 4 | GDI power stage, bench only |
| 5 | Full integration: the B48 running entirely on the platform |
| 6 | Deeper transmission control |

Honest estimate for phases 0–5, one person working evenings and weekends:
**several years.** Phase 6 is comparable in size to everything before it.

Full detail in [`docs/roadmap.md`](docs/roadmap.md).

---

## 7. Building and testing

```bash
# Python: application and model
pip install -e ".[test]"
python -m pytest

# Firmware: host build and tests
cmake -S fw -B build/fw && cmake --build build/fw && ctest --test-dir build/fw

# Firmware: cross-compile for the real target and check for double precision
fw/tools/crosscheck.sh
```

The firmware suite includes a cross-compile check that skips cleanly if no
`arm-none-eabi-gcc` is installed, so a contributor without one is not blocked.

---

## 8. Where to read next

| Document | What it covers |
|---|---|
| [`docs/what-it-does.md`](docs/what-it-does.md) | The one-page version of the control concept |
| [`docs/architecture.md`](docs/architecture.md) | Why torque structure, and the module breakdown |
| [`docs/torque-model.md`](docs/torque-model.md) | The maths, including the inverse model |
| [`docs/hardware.md`](docs/hardware.md) | MCU selection, GDI power stage, I/O budget, bench kit |
| [`docs/transmission-control.md`](docs/transmission-control.md) | The engine–transmission integration contract |
| [`docs/roadmap.md`](docs/roadmap.md) | Phases and exit criteria |
| [`fw/README.md`](fw/README.md) | Firmware rules and what still needs a scope |
| [`docs/course/`](docs/course/) | The 16 lessons, readable on their own |
