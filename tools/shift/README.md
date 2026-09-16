# Exercise: write the shift coordinator

The physics is done (`tools/tqmodel/`). This is the **brain** — the part that
decides what to command, moment by moment, while the transmission shifts.

## The job

Open `coordinator.py` and fill in four TODO blocks inside
`ShiftCoordinator.update()`. Roughly 25 lines of real logic in total.

| TODO | What it decides |
|---|---|
| 1 | State machine: CUTTING → HOLDING → RESTORING → IDLE |
| 2 | The torque target right now (ramp down, hold, ramp up) |
| 3 | The spark angle that produces that target |
| 4 | **The air request** — the rule that makes or breaks the shift |

## Checking yourself

```cmd
python tools\shift\test_shift.py     :: six pass/fail checks
python tools\shift\simulate.py       :: plots what your code actually did
```

Run the tests first — each failure names the TODO to look at. Then run the
simulation to see it.

A correct implementation produces:

```
your code              during cut  150.0 Nm (target 150)   peak after  400.0 Nm
with air-chase bug     during cut  277.1 Nm (target 150)   peak after  586.2 Nm
```

The cut lands exactly on target, and torque returns to the driver's request
with no overshoot. The bug version dilutes the cut to 277 Nm and then
overshoots to nearly double.

Note in the plot that **the spark traces are identical in both runs**. Same
commanded timing, completely different outcome — the difference is entirely
what the air path did underneath. That is the lesson.

## Python refresher

Things this exercise uses, in case it has been a while:

```python
# dataclass -- a class that is just fields, no boilerplate
@dataclass
class Thing:
    value: float = 0.0
t = Thing(value=3.0);  t.value

# enum -- named constants. compare with "is"
class State(Enum):
    IDLE = "idle"
if self.state is State.IDLE: ...

# self -- the instance. self.x persists between calls, a plain x does not
self.t_in_state += dt          # remembered next tick
local = 5                      # forgotten immediately

# linear interpolation from a to b, fraction f of the way
value = a + (b - a) * f

# clamp to 0..1
f = np.clip(x, 0.0, 1.0)

# f-string, for printing while debugging
print(f"state={self.state} target={torque_target:.1f}")
```

Two things that catch people here:

- **Milliseconds vs seconds.** `ShiftRequest` times are in ms, `dt` is in
  seconds. Divide by 1000.
- **Reset the timer on every state change.** `self.t_in_state = 0.0`, or the
  next state's ramp starts partway through.

## Stuck?

Print things. Add `print(f"{self.state} {self.t_in_state:.3f}")` at the top of
`update()` and run the simulation — you will see immediately whether the state
machine is moving.

There is no reference solution in this repo on purpose. Ask me if you want a
hint on a specific TODO rather than the whole thing.
