# L11 — Lab 4: Mixture strategy

**Pass mark:** stoichiometric below 95 kPa, between 0.78 and 0.90 above
170 kPa.

## What is different about this lab

The other labs have a hidden truth. There is a real volumetric
efficiency surface, a real MBT, a real knock limit, and your job is to
find them.

This one does not. The engine will run at whatever mixture you ask for.
Nothing in the plant prefers one target over another. The marker is
not checking against physics, it is checking against **reasons**, and
the reasons are the content of L04.

That makes this the lab that is hardest to pass by fiddling and
easiest to pass by understanding.

## What the course tune gets wrong

Two deliberate errors, both of which you will meet in the wild.

**It runs 0.93 at cruise.** Rich everywhere feels safe. It is not: it
destroys the catalytic converter, which only works in a narrow window
around stoichiometric, it costs fuel continuously, and it washes oil
off the bores. It buys nothing at light load because there is no heat
problem and no knock problem to solve there.

**It runs 0.95 at full boost.** This is the dangerous one, and it is
dangerous precisely because it looks good. Slightly lean of best torque
makes decent power on a single dyno pull. It also puts you at the
combustion temperature peak, with no charge cooling, with the least
knock margin you could have arranged, on a turbocharged engine. This
is how people melt pistons while looking at a graph that is going up.

## Procedure

1. Open the **Lambda Target** table.
2. Select the region at and below atmospheric pressure. Set it to 1.00
   with `=`.
3. Select the high load region. Set it toward 0.85.
4. Interpolate between them with `I` so the transition is smooth rather
   than a step. An engine crossing a cliff in the target table will
   surge.
5. Mark the lab.

Then, and this is the part people skip: **go back and re-check Lab 3**.
You have just changed the charge cooling at high load. A richer mixture
resists knock, so the knock limit has moved, and there may be timing
available that was not there before.

## What you should notice

Changing the mixture changes torque, but it does not invalidate your
volumetric efficiency work. VE is about air. Lambda is about how much
fuel you put with it. They are separate tables holding separate facts,
which is exactly what makes them independently tunable.

That independence is not free, it is a property of the architecture.
In a system with a single fuel table, the desired mixture and the
airflow estimate are multiplied together into one number, and you
cannot correct one without disturbing the other.

## Questions before you mark it

1. Why is the transition between the two regions interpolated rather
   than stepped?
2. Your engine has no catalytic converter. Does the cruise target
   change? Should it?
3. Having gone richer at full load, which other lab needs redoing, and
   in which direction do you expect the answer to move?
