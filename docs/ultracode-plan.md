# Plan: from simulator to a real-car ECU

Status: Phases A to D built and tested on the host. Phase E needs
hardware. See "What is done" below.

Source: a 143-agent audit of the repo (6 subsystem maps, 8 adversarial
lenses, 3 independent refuters per critical/high finding). 46 findings
survived all three refuters; none were refuted; 167 medium/low findings
are carried unverified in the audit output.

## 1. Honest scope

What this push can deliver in software, verified on a PC:

- A tuner that behaves like real tuning software: explicit table
  read/write/burn protocol, armed live-write, per-cell LOCAL/RAM/FLASH
  state, validation of every value that reaches the engine, correct
  dirty/save semantics, a frozen exe that actually launches.
- A simulator with a hidden "truth" plant so VE, MBT and knock can
  genuinely be tuned (today the sim reads the answers from the tune).
- Safety logic in pure Python that is later ported one-to-one to C:
  drive-by-wire monitor, overboost, over-rev shift inhibit, coordinator
  authority clamp and fault handling.
- A firmware skeleton in C (`fw/`) with host build and tests: HAL
  interface, crank/cam decoder, angle-domain event scheduler, fuel path,
  HPFP loop, torque structure ported from `tqmodel`. Tested against the
  Python golden reference with synthetic tooth streams.
- A real test suite (pytest, headless Qt, no audio) and CI.

What needs hardware, a bench, and then a dyno:

- Decoder validation on a signal generator, then on the real B48 crank
  and VANOS cam wheels (pattern must be scoped first).
- Injector/coil/HPFP/throttle drivers, ADC scaling, CAN to the ZF 8HP.
- Every table: the truth plant is a stand-in, the dyno is the truth.

What software cannot achieve alone: a car that runs. This plan gets the
code to the point where the only unknowns are electrical and calibration.

## 1a. What is done

Phases A, B, C and D are implemented and under test: 145 Python tests and
six C suites, all passing in CI.

- **A.** Table and tune validation, physical bounds, split save/burn
  state with three per-cell baselines, the full connection protocol with
  CRC-verified burn, armed live write, a fixed frozen-executable entry
  point, pytest and CI.
- **B.** A truth plant distinct from the tune, a real fuel path, measured
  lambda as a consequence of the VE table, a knock model, and the
  coordinator's air request driving the air path.
- **C.** The Level 2 torque monitor, overboost and over-rev protection,
  and the shift coordinator treated as untrusted code.
- **D.** `fw/`: HAL interface, crank and cam decoder, angle-domain
  scheduler, torque model cross-checked against the Python to 1e-4, fuel
  and pump path, monitor port, and the four-rate task structure. Host
  build and tests in CI.

The tuner link is done too: `fw/src/proto.c` and `tuner/core/link.py`
speak the same framing, and `tests/test_serial_link.py` runs the real
firmware as a subprocess and drives it down a pipe, so the burn CRC is
checked across the actual boundary rather than against an imitation of
it. Trigger and safety settings pages exist and write to the tune.

Direct injection is in: multi-pulse scheduling, the injector current
profile with its boost recharge constraint, angle-scheduled pump valve
control, and rail pressure target, injection timing and pilot fraction
tables. The simulator models rail droop when the pump runs out of
capacity, which is the failure that leans an engine out at full load.

Not done, and needing hardware: the STM32H7 HAL (`fw/hal/hal_stm32h7.c`
documents the peripheral plan and refuses to build), and the physical
port picker in the tuner. The B48 trigger numbers, the injector drive
profile and the pump lobe geometry are placeholders until someone scopes
them and reads the data sheets; the trigger and direct injection pages
both say so on their face.

## 2. Phases

Each task names its verification. "Fleet" says whether parallel agents
can do it and how it splits.

### Phase A. Trustworthy tuner (software only)

Goal: nothing the tuner does can silently corrupt a tune or lie about
what is in the ECU.

| Task | Files | Verified by |
|---|---|---|
| Split `file_dirty` from `ecu_dirty`; burn never clears file dirty; per-cell "value at last burn" | `tuner/core/tune.py`, `tuner/ui/main_window.py`, `table_editor.py` | `tests/test_editor_gui.py`: edit, burn, close prompts; undo after save shows real diff |
| `Table` gets dtype, lo, hi, `validate()`; reject NaN/inf/out-of-range at set, paste, axis dialog, `from_tsv`; `allow_nan=False` on save, strict parse on load | `tuner/core/table.py`, `tableops.py`, `tune.py` | `tests/test_table.py`, `tests/test_tableops.py`: NaN paste rejected, descending axes raise, lookup clamps |
| `Tune.validate()`: required tables, shapes, monotonic axes, scalar ranges, chen_flynn length; called on load and before `_replace_tune`; sim tick catches and stops on error | `tune.py`, `main_window.py`, `sim_ecu.py` | test loading a tune missing `knock` shows a message, sim keeps running old tune |
| `ECUConnection` contract: `identify`, `describe_tables`, `read_table`, `write_cell`, `write_table`, `burn`, `error` signal; fixed table dimensions from descriptors; burn moves off `MainWindow` | `tuner/core/connection.py`, `sim_ecu.py`, `main_window.py` | `tests/test_live.py`: write → echo → cell shows RAM; burn → CRC match → FLASH |
| Armed live-write mode with visible indicator; unarmed edits stay LOCAL | `table_editor.py`, `main_window.py` | GUI test: unarmed edit does not change sim output |
| Frozen exe: launcher script, ship `tools/shift` as data, resolve `_MEIPASS` | `packaging/launcher.py`, `tuner.spec`, `sim_ecu.py` | build then run `LambdaOne.exe --screenshot` on Windows (manual gate) |
| Convert tests to pytest, `conftest.py` with offscreen Qt and shared QApplication, add `test` extra, GitHub Actions | `tests/`, `pyproject.toml`, `.github/workflows/ci.yml` | CI green |

Fleet: yes, 4 agents by row groups (dirty/validate, connection/live-write, packaging, tests). Exit: all tests pass in CI; a NaN cannot reach the sim by any path.

### Phase B. Simulator that can be tuned

Goal: the sim hides a truth plant so tuning has something to find.

| Task | Files | Verified by |
|---|---|---|
| Truth plant: `truth_ve`, `truth_mbt`, truth knock surface, injector flow that differs from the tune | `tuner/core/sim_ecu.py`, `tqmodel/synth.py` | `tests/test_ve_autotune.py`: VE back-calc converges to truth within 2 % |
| Fuel path: fuel mass from air/lambda target, corrections, injector PW from rail pressure and dead time; publish `pw_ms`, `duty`; lambda measured = truth air / fuel | `sim_ecu.py`, `tune.py`, `connection.py`, `gauges.py` | spark sweep in dyno mode shows a torque peak at truth MBT; lambda responds to VE edits |
| Knock plant: `knock_count`, `knock_retard`, recovery, per-cell "knock seen" overlay | `sim_ecu.py`, `table_editor.py` | test: advancing past truth knock limit produces retard |
| `spark_efficiency` with zero slope at MBT; shared by `tqmodel` and coordinator; coordinator gets true MBT and current spark | `tqmodel/model.py`, `tools/shift/coordinator.py`, `sim_ecu.py` | `tests/test_model.py` numeric anchors; cut fraction correct under knock retard |
| Coordinator's `air_request` drives the air path; sim freeze becomes wedge guard only | `sim_ecu.py` | test flips `chase_air_bug` and asserts overshoot only in bug case |
| Clutch capacity, slip and inertia-phase torque so a missing cut visibly harms | `sim_ecu.py`, `mimic.py` | test: no cut → slip spike; cut → bounded slip |
| `tests/test_model.py` for every `tqmodel` function, inverse round trips to 1e-9 | `tests/` | pytest |

Fleet: yes, 3 agents (plant+fuel, knock+spark, shift dynamics). Exit: a fresh default tune can be tuned to the truth plant using only the app.

### Phase C. Safety logic in Python (port target for C)

| Task | Files | Verified by |
|---|---|---|
| `tuner/core/monitor.py`: dual pedal/TPS plausibility, permissible torque, monitor state, limp levels, fault codes; new channels | `monitor.py`, `connection.py`, `sim_ecu.py` | tests inject pedal disagreement → limp |
| Overboost: `boost_max_kpa`, `overboost_cut_kpa`, fuel cut plus fault | `sim_ecu.py`, `tune.py`, `settings_page.py` | test |
| Over-rev shift inhibit on manual and auto downshift | `sim_ecu.py` | test |
| Coordinator clamp to `[base − MAX_CUT_RETARD, base]`, reject non-finite; try/except with `coord_fault` channel and visible error | `sim_ecu.py`, `sim_dock.py` | test: coordinator raising → engine keeps running on base spark |

Fleet: yes, one agent per row. Exit: every fault path has a test and a visible indicator.

### Phase D. Firmware skeleton (C, host-tested)

| Task | Files | Verified by |
|---|---|---|
| `fw/` tree: CMake, host target, HAL interface (input capture, scheduled outputs, ADC, CAN-FD, flash), STM32H7 stub | `fw/` | host build in CI |
| Crank/cam decoder state machine with synthetic tooth streams (variable rpm, missing/extra teeth, noise, cranking) | `fw/decoder/` | `fw/tests/` |
| Angle-domain event scheduler: dwell, spark, SOI/EOI per cylinder, late-update rules | `fw/sched/` | tests against recorded schedule |
| Torque structure port of `tqmodel` in single-precision C; fuel path; HPFP MSV angle event plus PI loop | `fw/model/`, `fw/fuel/` | C vs Python golden reference within 1e-4 |
| Serial/CAN protocol implementing the Phase A `ECUConnection` contract; tuner talks to the host build | `fw/proto/`, `tuner/core/serial_connection.py` | `tests/test_live.py` against host build |
| Trigger/sensor settings page and tune schema fields | `settings_page.py`, `tune.py` | GUI test |

Fleet: yes, 4 agents (HAL+build, decoder+scheduler, model+fuel, protocol). Exit: tuner connects to the host-built firmware and burns a tune; decoder syncs on every synthetic stream.

### Phase E. Hardware (not software; listed for the gates)

Bench signal generator → decoder on STM32H7 → drivers on a bench engine → car.

## 3. Real-car gates

Before first key-on:

1. Phases A–D complete and CI green.
2. B48 crank and cam patterns scoped and decoder synced on the real signals, engine cranked by starter with injectors and coils disconnected.
3. Level 2 monitor forces limp on pedal disagreement (bench test with a pedal).
4. Throttle limp-home position verified with power cut to the H-bridge.
5. Rail pressure loop stable with pump on, injectors off.
6. Overboost cut and rev limit tested on the bench with simulated MAP and rpm.
7. Burn → read-back CRC verified through the real link.

Before first drive:

1. Idle and free-rev on the dyno with lambda within target.
2. Knock detection windows validated with a known knock event.
3. Shift cut verified on the dyno in gear with the ZF 8HP: bounded slip, no flare.
4. Limp mode driven and confirmed to stop the car safely.

## 4. Findings addressed

| Confirmed finding | Phase |
|---|---|
| No firmware, HAL, build system | D |
| No crank/cam decoder | D |
| No event scheduler | D |
| No fuel calculation or injector drive | B (sim), D (firmware) |
| No HPFP control | D |
| No drive-by-wire monitor | C, D |
| `ECUConnection` lacks read/write/burn/identify | A |
| Burn lives in `MainWindow`, sim-only | A |
| Keystrokes instantly "in the ECU" | A |
| No value validation, NaN accepted (5 findings) | A |
| Axis editing changes dimensions | A |
| Save clears "Burn required"; burn clears file dirty (4 findings) | A |
| Undo restores stale dirty mask | A |
| Missing table crashes sim tick (2 findings) | A |
| Sim couples VE to torque, lambda is target plus noise (2 findings) | B |
| Sim MBT is the table; no knock model (2 findings) | B |
| Coordinator given knock-limited spark as MBT | B |
| `spark_efficiency` slope at MBT | B |
| `air_request` discarded (2 findings) | B |
| Shift elements display-only | B |
| Coordinator exception freezes engine (2 findings) | C |
| Unbounded coordinator retard | C |
| Manual downshift past rev limit | C |
| No boost limit | C |
| Frozen exe crashes; coordinator missing from bundle | A |
| No `tqmodel` tests; no shift-in-sim test; tests not pytest (5 findings) | A, B |

Refuted claims: none. Every critical/high finding put to three refuters was confirmed.

## 5. Open decisions

1. **MCU target for Phase D.** STM32H7 as `docs/hardware.md` says, or start straight on S32K344. Changes the HAL stub and toolchain.
2. **Tuner link protocol.** Own binary framing over USB-CDC and CAN, or adopt an existing one (Speeduino-style serial, or MegaSquirt-compatible) so other tools can connect. Changes Phase A's connection contract and Phase D's protocol module.
3. **Who owns the shift air freeze.** Coordinator (the exercise stays meaningful) or firmware (safer, less teachable). Phase B assumes coordinator.
4. **Phase order.** A→B→C→D as written, or D first to get hardware moving in parallel. Recommendation: A and C first, they are cheap and every later phase leans on them.
5. **Licence** for the `fw/` tree before any of it is public.
