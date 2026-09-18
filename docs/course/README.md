# TQ-101 — Engine Calibration and Torque-Based Engine Management

Fifteen sessions and six graded labs, built around this repository. The
lectures are here; the labs are marked inside the application, on the
Course page in the navigator.

## What this course is

A calibration course that happens to teach engine management, rather
than the other way round. By the end you should be able to take an
uncalibrated engine and a torque-structured ECU and produce a map that
works, and more importantly be able to say why each number in it is
what it is.

The simulator you practise on runs on its own volumetric efficiency,
spark and knock surfaces. Your tables are not those surfaces, and the
engine does not consult them to decide how to behave. Every correction
you make is therefore a real correction, found the way you would find
it on a dyno. That is the difference between this and a demonstration.

## The four surfaces, and which to open when

This course is delivered four ways. They are one thing; use them in
this order and they behave like one.

| | What it is | When |
|---|---|---|
| [**Calibration Bench**](https://claude.ai/artifact/LnNL2zyGuDTLqQrn2sx3Vr) | The front door. Tells you which sitting you are on and the one thing to do next, and holds the interactive instruments. | Open this first, every time. |
| These lectures | The reading. One or two per sitting, named on the bench. | Before the lab. |
| The app's **Course** page | The marker. Grades your tune against the engine. | After the lab. |
| [The slide deck](https://claude.ai/artifact/WnugAPv7dAtp4rK2GLWa1w) | The lecture, for presenting. | Only if you are explaining this to somebody. |

## Before you start

```
python -m tuner.app --sim 0
```

Open **TQ-101 Course** in the navigator and press **Load the course
tune**. That replaces the shipped base map with one that is wrong in
the specific ways the labs ask you to fix. Then press **Mark
everything** to see where you stand. All six should fail.

Then open the bench and let it tell you where to begin. Six sittings,
one lab each, and the sittings map to the lectures like this:

| Sitting | Read | Lab |
|---|---|---|
| 1 | L05, L08 | Lab 1, volumetric efficiency |
| 2 | L02, L09 | Lab 2, peak torque timing |
| 3 | L03, L10 | Lab 3, the knock limit |
| 4 | L04, L11 | Lab 4, mixture strategy |
| 5 | L12, L13 | Lab 5, the shift coordinator |
| 6 | L14 | Lab 6, direct injection |

L01, L06, L07 and L15 are the conceptual sessions. Read them whenever;
they land better once you have a couple of labs behind you.

**One lab per sitting, and stop when it passes.** Finishing one thing
beats half-finishing three, and a session with a small defined end is
much easier to start.

## Syllabus

### Part I — Combustion, and where torque comes from

| | |
|---|---|
| [L01](L01-what-makes-torque.md) | What actually makes torque |
| [L02](L02-spark-timing.md) | Spark timing and maximum brake torque |
| [L03](L03-knock.md) | Knock |
| [L04](L04-mixture.md) | Mixture |

### Part II — The control problem

| | |
|---|---|
| [L05](L05-estimating-airflow.md) | Estimating airflow |
| [L06](L06-torque-structure.md) | The torque structure |
| [L07](L07-two-paths.md) | Two paths to torque |

### Part III — Calibration

| | Lab |
|---|---|
| [L08](L08-lab-ve.md) | Lab 1: volumetric efficiency |
| [L09](L09-lab-mbt.md) | Lab 2: peak torque timing |
| [L10](L10-lab-knock.md) | Lab 3: the knock limit |
| [L11](L11-lab-mixture.md) | Lab 4: mixture strategy |

### Part IV — Integration

| | |
|---|---|
| [L12](L12-transmission.md) | Coordinating with a transmission |
| [L13](L13-lab-shift.md) | Lab 5: the shift coordinator |
| [L14](L14-direct-injection.md) | Lab 6: direct injection |
| [L15](L15-real-engine.md) | Taking it to a real engine |

## How the labs are marked

Against the plant, not against a worked answer. The marker samples a
grid of operating points, compares your tables to what the engine
actually does there, and tells you which points are wrong and in which
direction. It does not tell you the answer.

Lab 3 is marked from both sides. Commanding more advance than the
engine will take fails outright. So does burying everything in retard
to be safe, because that is not a calibration, it is an apology.

## A note on order

Part III must be done in order. A spark sweep performed on a wrong
volumetric efficiency table is measuring your fuelling error, and a
knock limit found at the wrong mixture is not the knock limit. The
course enforces nothing, but the marker will tell you when you have
fooled yourself.
