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
| `decoder.c` | Crank and cam edges to engine position, plus cam position itself. The only module allowed to say where the engine is, and the only one allowed to say it does not know. |
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

## The cam is read as a pattern, not as one edge

BMW's cam target wheels carry several features with deliberately unequal
spacing, and BMW's own training material says why: the pattern exists so
the DME can run on the cam alone if the crank sensor fails, and so the
sensor can "provide feedback relating to the camshaft position for VANOS
control". A decoder that reads one edge per cycle throws that away.

The decoder matches on the SPACINGS between cam edges rather than on any
edge's absolute angle. A phaser translates the whole pattern rigidly, so
every angle moves and no spacing does. Three consequences follow:

- Phase survives the full travel of the phaser. The previous single-edge
  decoder had to allow a tolerance wide enough to pass a moving cam, and
  the shipped 25 degrees was far narrower than a real intake phaser's
  ~70 crank degrees of authority -- so past a quarter of its travel it
  never reached full sync, and since nothing fires without 720-degree
  phase, the engine cranked and did not start.
- Cam position becomes a measurement, in crank degrees, which is what a
  VANOS control loop needs and what `decoder_cam_advance` returns. It
  refuses rather than serving a stale number: a phaser is an integrating
  plant and a frozen measurement winds it into its stop.
- A jumped timing chain becomes detectable. The pattern still matches --
  the wheel is undamaged -- but it sits bodily outside the phaser's
  mechanical travel. A wide single-edge tolerance cannot tell those
  apart. This one latches until `decoder_init`, because it should need a
  human rather than a key cycle.

## Before this runs an engine

`decoder_config_b48()` is a guess, and now a larger one. The crank tooth
count, the gap position relative to cylinder 1 TDC, and both VANOS cam
patterns must come from a scope capture on the real engine.

60-2 is confirmed for the BMW DME family of this era -- BMW ST055 states
the DME increments crank position by 6 degrees per tooth -- but is not
published for the B48 specifically. The cam patterns currently carry the
rusEFI project's rising edges measured from a real N52, doubled into
crank degrees. An N52 is not a B48: treat the shape as right and the
numbers as a placeholder.

One thing the capture must also settle: these sensors are Hall, and BMW
crank sensors of this generation encode rotation direction in pulse
WIDTH so the DME can run auto start-stop. That makes the mark and space
deliberately unequal, and only one polarity is the true tooth edge. The
HAL carries the polarity for this reason.

The gate list is in `docs/ultracode-plan.md`.
