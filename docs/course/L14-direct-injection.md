# L14 — Lab 6: Direct injection

**Pass mark:** rail pressure appropriate to load, injection inside the
intake event, pilot pulse where mixing time is short.

## What changes when the injector moves

Port injection sprays into the intake port, upstream of the valve, into
moving air at roughly atmospheric pressure. There is time for the fuel
to evaporate and mix before it is trapped.

Direct injection sprays into the cylinder itself. That changes four
things, and all four are why this lab exists.

**Pressure.** The injector is spraying into a cylinder that is itself
under pressure, and at high load that is a lot of pressure. Flow
through a nozzle goes as the square root of the pressure drop across
it, so what matters is rail pressure minus cylinder pressure, not rail
pressure alone. An ECU that uses the gauge reading runs lean exactly
when leanness is most dangerous. Look at `tq_pulse_width_us` in
`fw/src/fuel.c`.

**Time.** The injection has to happen during a window of the cycle, not
whenever is convenient. That window shrinks with engine speed. Measure
injector duty against the whole cycle and a direct injector appears
about three times larger than it is.

**Mixing.** There is far less time to evaporate and distribute the
fuel, which is why injection timing is a calibration variable rather
than a constant, and why splitting the charge into more than one pulse
helps at high load.

**The pump.** Rail pressure of 200 bar does not come from an electric
pump in a tank. It comes from a mechanical pump driven off a camshaft,
delivering in discrete strokes, controlled by a valve that closes part
way through each stroke. Later closing means less fuel delivered. That
makes pump control an angle-domain problem needing crank phase,
exactly like spark.

## What the course tune gets wrong

**Flat rail pressure at 8000 kPa.** As though the pump had one setting.
At light load that is wasteful and atomises a tiny pulse badly. At high
load it is nowhere near enough: the injector has little time and a lot
of cylinder pressure to fight.

**Injection at 250 degrees BTDC everywhere.** Too late. You are
spraying at a closing intake valve, with no time to mix.

**No pilot pulse anywhere.** At high load and speed there is not enough
time for a single injection to distribute properly.

## Procedure

1. Open **Rail Pressure Target** under Direct Injection. Make it rise
   with load. Low load wants something modest, high load wants most of
   what the pump can give.
2. Open **Injection Timing**. Put it inside the intake event, which for
   this engine means the low 300s of degrees BTDC, advancing somewhat
   with engine speed because the window is shorter in real time.
3. Open **Pilot Fraction**. Set a pilot of around 0.3 in the high load,
   high speed corner and zero elsewhere. A pilot pulse where there is
   plenty of mixing time is just two chances to get the metering wrong.

## Watch the pump run out

Set the engine to full load in dyno mode and watch **Rail press.**
against **Rail target**, and **Pump duty**.

Then open Engine Setup, the Injector and Pump page, and cut **Pump
capacity** to six grams per second. Run the same point.

The rail collapses, pump duty pins at 100 percent, and the pulse width
climbs to compensate. That is a real failure and it is invisible unless
the rail is modelled: the injectors outrun the pump, every pulse
delivers less than the ECU planned, and the engine leans out at full
load. Knowing what it looks like in a log is worth having.

## Mark it

Course page, **Mark this lab**.
