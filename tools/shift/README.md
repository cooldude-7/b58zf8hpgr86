# Exercise: write the shift coordinator

The physics is already written (`tools/tqmodel/`). This is the **brain** — the
part that decides what to command, moment by moment, while the transmission
shifts.

Plain Python only: functions, dictionaries, `if`/`elif`, arithmetic. No
classes, no dataclasses, no enums.

## The job

Open `coordinator.py`, fill in four TODO blocks inside `update()`. About 25
lines of real logic.

| TODO | What it decides |
|---|---|
| 1 | Move from one phase to the next at the right time |
| 2 | What torque we are aiming for right now |
| 3 | What spark angle produces that torque |
| 4 | **How much air to ask for** — the one that makes or breaks it |

Written for you: `retard_for_fraction()`, `fraction_for_retard()` and
`ramp()`. Those are algebra, not architecture.

## Checking yourself

```cmd
python tools\shift\test_shift.py
python tools\shift\simulate.py
```

Run the tests first — each failure names the TODO to look at. Fresh out of the
box you get **2/6**; those two are "nothing bad happened" guards that pass
trivially. A correct implementation gets 6/6.

Then run the simulation to watch it:

```
your code              during cut  150.0 Nm (target 150)   peak after  400.0 Nm
with air-chase bug     during cut  277.1 Nm (target 150)   peak after  586.2 Nm
```

The cut lands exactly on target and returns with no overshoot. The bug version
dilutes the cut to 277 Nm and then overshoots to nearly double.

In the plot, notice **the spark traces are identical in both runs**. Same
commanded timing, completely different outcome. The difference is entirely
what the air path did underneath — which is the whole lesson.

## Python you need

Only four things, and you have met all of them:

```python
# a dictionary holds the controller's memory between ticks
c = {"phase": "idle", "time_in_phase": 0.0}
c["phase"] = "cutting"           # write
if c["phase"] == "cutting":      # read
    ...

# if / elif / else
if x == "a":
    ...
elif x == "b":
    ...
else:
    ...

# calling the helpers that are already written
degrees = retard_for_fraction(0.5)          # -> 30.0
value = ramp(400.0, 150.0, 0.5)             # -> 275.0

# printing while you debug
print(c["phase"], c["time_in_phase"])
```

## Two things that catch people

- **Milliseconds vs seconds.** `RAMP_IN_MS` is 50 (milliseconds), but
  `time_in_phase` counts in seconds. Compare against `RAMP_IN_MS / 1000.0`.
- **Reset the timer on every phase change.** Set
  `c["time_in_phase"] = 0.0` whenever you change `c["phase"]`, or the next
  phase starts partway through.

## Stuck?

Put a print at the top of `update()`:

```python
print(c["phase"], round(c["time_in_phase"], 3))
```

Run the simulation and you will see straight away whether the phases are
advancing.

No reference solution in this repo, on purpose. Ask for a hint on one TODO
rather than the whole thing.
