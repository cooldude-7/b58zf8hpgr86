# Hardware Platform

## MCU selection

The core controller needs: hardware timer channels with input capture for
crank/cam decode, enough PWM and scheduled-output channels for sequential fuel
and spark, multiple CAN-FD controllers, fast ADC, ideally a DSP path for knock,
and — for the safety concept — either lockstep cores or a genuinely independent
monitoring device.

| Candidate | Verdict |
|---|---|
| **NXP S32K344** | The realistic target. Lockstep Arm Cortex-M7, automotive safety peripherals, multiple CAN-FD, good tooling, actually purchasable in small quantities. |
| **Infineon AURIX TC3xx** | Technically superior, this is what OEMs use. Toolchain cost and complexity are punishing for a small team. |
| **ST SPC58** | Viable middle ground, PowerPC core, smaller community. |
| **STM32H7** | Not automotive-qualified, no lockstep, but enormous headroom, free tooling, and a huge community. Excellent for prototyping. |

**Suggested path:** prototype on **STM32H7**, design the production core around
**S32K344**. Write the firmware against a hardware abstraction layer from day
one so the port is a porting job, not a rewrite. Resist the temptation to skip
the abstraction "just for the prototype" — that decision is how Speeduino ended
up welded to an ATmega.

The satellite modules do not need the same class of part. The GDI module and
the PDM are comfortable on an STM32G4 or similar.

## GDI power stage

The hardest board in the system, and the reason it gets its own PCB.

**Injector drive.** Solenoid GDI injectors (Bosch HDEV5/HDEV6 and equivalents)
need a boost rail in the **60–70 V** range, a peak current around **10–12 A**
for a few hundred microseconds, then a hold current a few amps down, with the
current *shaped*, not just switched.

The part to build around is the **NXP MC33816** — a programmable dual-channel
solenoid driver with its own microcode engine, designed for exactly this
(GDI and diesel common rail). Two of them covers a four-cylinder; three covers a
six. Writing MC33816 microcode is its own small learning curve, budget for it.

**Boost converter.** Must store and deliver enough energy for multiple injection
events per cylinder per cycle across all cylinders at high RPM. Sizing this for
the worst case — high load, split injection, high RPM — rather than the typical
case is the difference between a working system and one that mysteriously leans
out at the top of third gear.

**High-pressure fuel pump.** A cam-driven single-piston pump with a solenoid
spill valve. You close the loop on rail pressure by choosing, cam-synchronously,
when to close the spill valve and therefore what fraction of the piston stroke
actually pumps. Expect this to take longer than the injector drivers did. Wrong
timing means either no pressure at all or sitting on the mechanical relief.

**Verify the target injectors before committing.** Drive parameters vary
meaningfully by manufacturer and by injector generation. Get the real parts on a
bench with a current probe before finalising the power stage.

## I/O budget (core controller, target)

Sized for a V8 with four cam phasers so the platform does not need a second
design revision to grow:

- 8 sequential injection channels (logical — routed to GID or to port drivers)
- 8 ignition channels, logic-level drive to external coils
- 4 cam position inputs, 1 crank input, VR and Hall capable, software selectable
- 8+ knock inputs or 2 wideband knock sensors with per-cylinder windowing
- 2 wideband lambda controllers on-board
- 6+ H-bridge outputs (throttle, wastegate, phaser oil control, tumble flaps)
- 16 low-side PWM outputs
- 12 analog inputs, 5 V and ratiometric
- 8 digital/frequency inputs (wheel speeds, turbine speed)
- 3 CAN-FD, 2 LIN
- USB and Ethernet for calibration and logging

Ethernet is worth including. Modern calibration and logging workflows choke on
CAN bandwidth, and being able to stream full-rate internal state during shift
development will save enormous time on the transmission work.

## Bench infrastructure

This is not optional and it is routinely underestimated. Before the platform
touches a car you want:

- **Engine simulator** — a signal generator producing crank and cam patterns for
  arbitrary trigger wheels at arbitrary RPM, so decode and scheduling can be
  validated without an engine.
- **Injector test rig** — single injector, pressure vessel, current probe,
  scope. Where the GDI power stage is actually developed.
- **HIL bench** — the full module set with simulated sensors and loads.
  Necessary for the safety monitoring work, because you have to be able to
  inject faults deliberately and repeatedly.
- **Transmission bench** — a ZF8HP with the mechatronic unit, a pressure source,
  and instrumentation. Direct clutch control cannot be developed in a car.

The transmission bench is the expensive one and the one that determines whether
direct control is a real goal or an aspiration.
