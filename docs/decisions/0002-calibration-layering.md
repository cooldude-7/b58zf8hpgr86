# 2. The plant is not the calibration

Status: accepted

## Context

The simulator originally read the tune to decide what the engine did.
Measured lambda was the lambda target plus noise. The plant's MBT was
the MBT table. There was no knock model at all.

Every table therefore confirmed itself. A spark sweep found no peak,
because the peak was wherever the table said it was. Volumetric
efficiency could not be corrected against anything, because the
measurement was derived from the number being corrected. The app looked
like a tuning tool and could not be tuned on.

This is not only a simulator problem. The same confusion in firmware
produces an ECU that cannot learn: fuel trims that trim toward their own
target, knock control that never sees knock.

## Decision

Two layers, and they never read each other.

**The plant** is what the engine does. In the simulator it is
`plant_ve`, `plant_mbt` and `plant_knock_limit`, deliberately different
from the shipped tables. On a real car it is the engine.

**The calibration** is what the ECU believes. The VE table sizes the
injection. The MBT and knock tables decide the spark. The lambda table
says what mixture is wanted.

Everything measured is a *consequence* of the difference between the
two. Fuel comes from the tune's VE; air comes from the plant's; measured
lambda is the ratio, and it is wrong by exactly the VE error. Commanded
spark comes from the tables; whether the engine rattles is the plant's
answer, and knock retard is the feedback.

## Consequences

Tuning works, in the app and later on the dyno, by the same procedure:
change a table, watch a measurement that the table does not control,
converge.

The shipped base map is deliberately imperfect against the simulator's
plant. That is honest. A base map that is already exact is a base map
that teaches nothing and hides every bug in the correction path.

Any future feedback loop, fuel trims, knock learning, torque adaptation,
has an unambiguous place to live: it adjusts the calibration using a
measurement that comes from the plant. A loop that cannot be expressed
that way is a loop that is reading its own output.

The cost is that the simulator carries surfaces nobody tunes and nobody
ships. They are small, they live in `sim_ecu.py` next to a comment
saying why, and they are the reason the tests in `test_sim.py` can
assert that lowering VE leans the mixture out rather than asserting that
lowering VE lowers a number derived from VE.
