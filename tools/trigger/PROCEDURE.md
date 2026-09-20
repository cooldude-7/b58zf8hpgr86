# Getting the numbers this tool cannot derive

Two numbers are not in the crank and cam signals, and no amount of
processing will put them there:

1. **`gap_to_tdc_deg`** — the angle from the crank wheel's gap to
   cylinder 1 compression TDC. This is a statement about where the
   pistons are. The crank sensor cannot see pistons.
2. **Which of the two crank revolutions is compression**, and therefore
   where each cam pattern sits in the 720° cycle. The crank repeats every
   360°, so it cannot tell you.

Both need one more measurement. Here is the cheapest way to get each that
actually works.

## Which revolution is compression — capture a fourth channel

By far the easiest. While the engine runs on the **factory DME**, put a
fourth probe on the **cylinder 1 ignition coil trigger** (the low-current
signal from the DME, not the coil primary) or on the **cylinder 1
injector**. Either fires once per 720°, so it resolves the ambiguity
outright and the tool can place the cam patterns for you.

Do this on the same capture as the crank and cam channels. It costs one
more probe and no extra work.

## `gap_to_tdc_deg` — find TDC mechanically

The signal cannot give you this, so measure the engine.

**With a piston stop (accurate, engine not running):**

1. Remove the cylinder 1 spark plug. Fit a degree wheel to the crank
   snout and a pointer to the block.
2. Turn the engine **by hand, in its normal direction of rotation**,
   until cylinder 1 is somewhere on its way up.
3. Fit a piston stop into the plug hole.
4. Turn gently forward until the piston touches the stop. Record the
   degree wheel reading.
5. Turn gently **backwards** until it touches again. Record that reading.
6. True TDC is exactly halfway between the two readings. The stop is
   deliberately not at TDC; that is what makes the method work.

**Why the tool does not do this arithmetic for you:** at the moment of
contact the crank is stopped, and a stopped crank produces no signal
between teeth. The best the sensor can do is tell you which tooth you
are between — on a 60-tooth wheel, ±3°. Worse, the capture has no
direction information, so it cannot even see that step 5 turned the
engine the other way; it would integrate the reversal as more forward
rotation and silently produce a confident wrong answer.

Read the degree wheel with your eyes, average the two numbers, and type
the result in. Expect about ±1°, which is a degree wheel and a pointer,
not a signal-processing limit.

**With a timing light (quick, engine running, less accurate):** mark TDC
on the crank pulley, run the engine on the factory DME, log commanded
spark advance over CAN, and strobe the mark. Where it appears tells you
the offset. This is easier and gives roughly ±2–3°, limited by how well
you trust the DME's reported advance.

## What "good enough" means

Spark scatter of ±1° is not detectable on a dyno. ±5° is, and on a
knock-limited engine at full load it is the difference between a safe
tune and a hole in a piston. Get it to ±1–2° and move on; there is
nothing to gain past that and a lot to lose short of it.

## What this tool will not do

It will not tell you the VANOS travel limits. Those come from BMW's own
timing diagram (intake parks retarded with 70 crank degrees of advance,
exhaust parks advanced with 60 of retard) or from a bench sweep of the
phaser against its stops. It will not tell you the injector or pump
characteristics. And it will not tell you that a capture is *right* —
only that it is self-consistent. A capture taken with a marginal trigger
level is self-consistent and wrong.
