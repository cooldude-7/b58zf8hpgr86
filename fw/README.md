# fw — the firmware

C that runs the engine. It is built two ways from the same sources:

- **host**, with `hal/hal_host.c`, so the whole control path can be
  compiled and tested on a PC. This is what CI runs.
- **target**, with `hal/hal_stm32h7.c`, which is not written yet and
  fails the build loudly if you try.

```
cmake -S fw -B build/fw && cmake --build build/fw && ctest --test-dir build/fw
```

## What is here

| Module | What it does |
|---|---|
| `decoder.c` | Crank and cam edges to engine position. The only module allowed to say where the engine is, and the only one allowed to say it does not know. |
| `sched.c` | Angle-domain events to timer compares. Owns the rule that a charging coil always gets to fire. |
| `model.c` | The torque model, ported from `tqmodel`. Checked against `tests/data/golden.txt`, which the Python generates. |
| `fuel.c` | Charge mass to pulse width, and the high pressure pump loop. |
| `monitor.c` | Level 2 torque monitor, ported from `tuner/core/monitor.py`. |
| `ecu.c` | Task structure: crank ISR, 1 ms, 10 ms, 100 ms. |

## What is deliberately not here

No interrupt vectors, no linker script, no startup code, no clock tree.
Those arrive with the board, and inventing them without one produces
files that look finished and are wrong.

## The rules this code keeps

- Single precision everywhere. The M7 and the S32K3 have no double unit,
  and a stray `double` turns a one-cycle multiply into a library call
  inside a crank interrupt.
- No allocation, anywhere.
- Every timer comparison is a signed difference, never `<`. The
  microsecond counter wraps every 71 minutes and a direct comparison
  fails once per wrap, which is the kind of fault that only shows up on
  a long drive.
- Nothing fires without 720-degree phase. Crank sync alone is not
  enough: half the sparks would land on an open intake valve.
- Fuel is the fast cut. Spark is only ever cut with fuel already off,
  because cutting spark alone pumps raw fuel into the exhaust.

## Before this runs an engine

`decoder_config_b48()` is a guess. The crank tooth count, the gap
position relative to cylinder 1 TDC, and both VANOS cam patterns must
come from a scope capture on the real engine. Everything else in the
decoder is tested; those four numbers are not measurements yet.

The gate list is in `docs/ultracode-plan.md`.
