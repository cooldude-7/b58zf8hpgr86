# Tuning Application — Plan

**Status: Phase 1 built (`tuner/`), Phases 2–5 pending.** This is the plan for the tuner-facing
Windows application: the thing a tuner opens, connects to the ECU with, and
edits tables in.

## What it has to be

A native Windows desktop application that a tuner would not distinguish from
MaxxECU MTune, TunerStudio, KTuner or HP Tuners. Dense, utilitarian, keyboard
driven, grey. Those applications look the way they do because they are tools
used for hours at a time on a laptop balanced on a fender. Every design choice
below is downstream of that.

The current backend is the **simulated engine** (`tqmodel`) — the app connects
to a simulator that behaves like an ECU. Later a real transport (serial/CAN)
plugs in behind the same interface and the UI does not change. That is also how
TunerStudio works: it has a demo mode that is indistinguishable from a live ECU
from the UI's point of view.

## What it must not be

Explicit, because it is the stated concern:

| Not this | This |
|---|---|
| Web technology in a window (Electron, Tauri, a browser) | Native widget toolkit |
| Custom-drawn everything, rounded corners, shadows, gradients as decoration | Native widget style; colour only where it carries data |
| Web fonts, large type, generous padding, "cards" | System UI font at 9 pt, 2–4 px margins, splitters and docks |
| Emoji or illustrated icons | 16 px flat monochrome toolbar icons |
| Big buttons and modal overlays | Menus, toolbars, dialogs, right-click context menus |
| Mouse-only | Every table operation has a key |

## Technology

**PySide6 (Qt for Python)** with **PyQtGraph** for real-time plotting, packaged
with **PyInstaller** into a `.exe`.

Why, against the alternatives considered:

| Option | Verdict |
|---|---|
| **PySide6 / Qt** | Native-looking widgets, docking, tree views, a proper table view with custom cell painting, high-rate plotting via PyQtGraph, and it imports `tqmodel` directly — the app is literally a UI over the model already written. Packages to an exe. **Chosen.** |
| C# WinForms / WPF | The most literal match for the aesthetic (it is what HP Tuners and KTuner are built in). But a new language, Visual Studio, and the torque model would need porting or a bridge. Right answer for a company, wrong answer for this project today. |
| C++ Qt | Maximum performance, what MaxxECU-class tools plausibly use. Too big a lift for a rusty-Python developer, and unnecessary at this data rate. |
| Electron / web | Would look like a web app. Ruled out on the stated requirement. |
| Tkinter | Ships with Python but looks dated in the wrong way: weak table widgets, no docking, no fast plotting. |
| Dear ImGui | Fast and dense, but reads as a game-engine debug tool rather than tuning software. |

Qt's Windows style (`windowsvista` / `Windows`) gives the classic look with no
custom drawing. Qt is LGPL; PySide6 links dynamically, so a closed-source
product is fine if that is where this goes.

## Layout

```
+-----------------------------------------------------------------------------+
| File  Edit  ECU  View  Tools  Help                                          |
+-----------------------------------------------------------------------------+
| [Connect] [Burn] | [Open] [Save] | [Gauges] [Log] [3D]                      |
+---------------+---------------------------------------------+---------------+
| > Engine Setup| | VE Table | MBT Table | Knock Limit |      |  +-- RPM --+  |
| v Fuel        | +-----------------------------------------+ |  |  gauge  |  |
|    VE Table   | |      1000 1500 2000 2500 3000 ... 7000  | |  +---------+  |
|    Lambda Tgt | | 20psi 1.02 1.05 1.09 1.12 1.14 ...      | |  +-- MAP --+  |
|    Deadtime   | | 15psi 1.00 1.03 1.07 1.10 1.12 ...      | |  |  gauge  |  |
| v Ignition    | | 10psi 0.98 1.01[1.05]1.08 ...           | |  +---------+  |
|    MBT Table  | |  5psi ...        ^ live cursor          | |  Lambda  0.88 |
|    Knock Limit| |  0psi ...                               | |  Torque  312  |
| v Torque      | | -5psi ...                               | |  Auth    141  |
|    Base Torque| |-10psi ...                               | |  CLT      88  |
|    Friction   | +-----------------------------------------+ |  IAT      31  |
|    Pedal Map  |                                             |               |
| v Transmission+---------------------------------------------+---------------+
|    Shift Sched| Datalog  [Rec] [Stop]   RPM -- MAP -- Lambda -- Torque --   |
|    Torque Cut | ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ |
+---------------+-------------------------------------------------------------+
| * Connected: SimECU 0.1 | b48_base.tune* | Burn required | 3450 rpm  8.2psi |
+-----------------------------------------------------------------------------+
```

Left: navigation tree (dock). Centre: tabbed table editors and settings pages.
Right: gauge dock. Bottom: datalog dock. All docks movable, closable, and
remembered between sessions. Status bar carries connection state, tune file
state, burn state, and a live RPM/boost readout.

## Screens

### Table editor — the heart of it

- Axis headers: RPM across the top, load down the side, **load increasing
  upward** (TunerStudio / HP Tuners convention, and it matches the 3D surface).
- Heat-map cell colour, green → yellow → red across the table's range.
- **Live cursor**: the cell under the current operating point is outlined and
  the four cells being interpolated between are marked. This single feature is
  what makes it read as tuning software rather than a spreadsheet.
- Keyboard: arrows move; type a number to set; `+` / `-` bump by a step,
  `Shift` for a larger step; `*` and `/` scale the selection by a percentage;
  `=` sets the whole selection; `I` interpolates across a rectangular selection;
  `S` smooths; `Ctrl+C` / `Ctrl+V`. Right-click menu carries the same.
- Rectangular multi-select.
- Cells changed since the last burn get a marker.
- **3D** toggle on the tab: PyQtGraph OpenGL surface, same data, same colours.
- Axis editor dialog. Units toggle applies to axis labels (kPa / psi).

### Gauges dock

Round black-face gauges with white ticks and a red needle for RPM, boost,
lambda, coolant, intake temperature. Bar or numeric readouts for throttle,
torque, authority. Configurable set. 20 Hz update.

### Datalog dock

Multi-trace scrolling strip chart with a cursor readout, channel picker,
record/stop, save to CSV, load a CSV back for review. PyQtGraph.

### Settings pages

Grouped form layouts — label, spinbox or combobox, unit — inside group boxes.
The classic dialog look. Engine constants, injector data, trigger, units.

### Torque pages — the differentiator, in the native idiom

- **Torque structure**: requested torque, produced torque, available authority
  (Nm and %), and which requestor currently has the floor. Readouts and bar
  gauges, not a diagram — it has to look like the rest of the app.
- **Shift torque reduction**: target, ramp-in, hold, ramp-out. These are the
  exact parameters from `tools/shift/coordinator.py`. A **Test Shift** button
  fires a shift in the simulator so the cut and recovery show up on the
  datalog. A checkbox reproduces the air-chase bug live. If the coordinator
  exercise is still placeholders, Test Shift does nothing visible — a decent
  incentive.

## Theme

**Classic** is the default: panel background `#F0F0F0`, Segoe UI 9 pt, native
Windows style, sunken frames, table grid lines `#C0C0C0`, selection
`#0078D7`. Gauge faces `#101010`, needle `#E03030`.

**Dark** as a toggle later: MaxxECU / Haltech NSP territory — `#2B2B2B` panels,
`#3C3F41` chrome, same density. A palette swap in one file; nothing else changes.

High-DPI is handled by Qt's scaling, so "looks 20 years old" does not mean
"blurry on a modern laptop".

## Architecture

```
tqmodel/                 promoted from tools/tqmodel — the physics (unchanged)
tools/shift/             the coordinator exercise — stays where it is
tuner/
  app.py                 entry point
  core/
    tune.py              the tune: tables, scalars, metadata. JSON on disk.
    table.py             a table: axes, values, interpolate/smooth/scale ops
    connection.py        ECUConnection interface: connect, channels, read/write tables, burn
    sim_ecu.py           SimulatedECU: drives tqmodel in a thread, publishes channels
    datalog.py           ring buffer of channels vs time; CSV in and out
    units.py             display conversions
  ui/
    main_window.py       QMainWindow: menus, toolbar, status bar, docks, central tabs
    nav_tree.py
    table_editor.py      QTableView + heat-map delegate + key handling + live cursor
    table_3d.py          PyQtGraph GL surface
    gauges.py            gauge widgets and the gauge dock
    datalog_view.py      strip chart dock
    settings_page.py     grouped-form pages
    theme.py             palettes and stylesheet
  resources/icons/       16 px monochrome toolbar icons
packaging/
  tuner.spec             PyInstaller
pyproject.toml           makes tqmodel and tuner importable; pip install -e .
```

The one rule: **the UI only ever talks to `ECUConnection`.** `SimulatedECU` is
the first implementation. A serial or CAN implementation later is a new file,
not a change to the UI.

### The simulator

Runs in its own thread at 100 Hz internally, publishes channels at 50 Hz.

- **Virtual pedal** — a slider in the app. Drag it and the operating point moves
  across the tables, gauges swing, the log scrolls. This is what a tuner sees on
  a dyno and it is the right demo.
- **Dyno mode** — hold RPM at a setpoint, vary load with the pedal. Lets you
  walk a single row of the VE table.
- Air comes from **the tune's VE table** — so editing the table changes the
  simulated engine's behaviour. Torque from the base torque map, spark from MBT
  and knock-limit tables, boost from a target table with lag, RPM from a simple
  load model. Lambda from the target table plus noise.
- The shift coordinator from the exercise is wired in behind Test Shift.

Channels published: rpm, map, boost, tps, lambda, clt, iat, spark, mbt, torque,
torque_requested, authority, ve_live, shift_phase.

### Tune file

JSON. Human-readable and diffs cleanly in git — a tune history is worth having.
Metadata, versioned schema, every table with its axes and values, every scalar.
The binary format the ECU eventually wants is the ECU's concern, produced from
this on burn.

## Phases — each one is runnable and shippable as an exe

**Phase 1 — Looks right, does nothing.**
Main window, menus, toolbar, status bar, nav tree, empty tab area, docks with
placeholder content, classic theme, PyInstaller build.
*Exit:* a screenshot next to MTune and TunerStudio passes the sniff test. An
`.exe` you can double-click.

**Phase 2 — Table editor.**
Heat-map grid, axes, all keyboard operations, multi-select, dirty markers, 3D
toggle. Tune JSON load and save. VE, MBT, knock limit, base torque, lambda
target tables populated from the current model defaults.
*Exit:* edit the VE table, save, reopen, values persist; 3D view matches.

**Phase 3 — Live.**
SimulatedECU, virtual pedal, dyno mode, gauges moving, live cursor on the
tables, datalog scrolling and recording, status bar connected.
*Exit:* drag the pedal, watch the cursor walk across the VE table.

**Phase 4 — Torque and shift.**
Torque structure page, shift reduction settings, Test Shift wired to the
coordinator, air-chase toggle.
*Exit:* press Test Shift and see the cut and clean recovery on the datalog.

**Phase 5 — Finish.**
Icons, About dialog, units toggle, dark theme, connection-loss handling,
keyboard reference, installer.

**Later, out of scope now:** real transport (serial / CAN), the ECU protocol,
burn to hardware, VE autotune from a datalog inside the app (the maths already
exists in `tqmodel.ve`).

## Risks, honestly

- **Qt has a learning curve.** The plan is that it gets built for you and you
  read and modify it, rather than you writing it from scratch. Every file stays
  small enough to read in one sitting.
- **OpenGL for the 3D view** needs a working driver; it falls back to the 2D
  table if not.
- **Python at 50 Hz** is fine for gauges and logs. Table repaint must be limited
  to the cursor cells, not the whole grid, or it will stutter.
- **Scope creep.** The temptation is to build a real ECU protocol before the
  UI is right. Phases 1–4 need no hardware and prove the product.

## Decisions needed before Phase 1

1. **PySide6** as recommended, or C# WinForms for the most literal look at the
   cost of a language switch?
2. **Classic grey** as the default theme, dark as a later toggle?
3. **A name.** The window title and the exe need one.
4. **Promote `tqmodel` to the repo root** with a `pyproject.toml`? Recommended;
   it is a small move and the exercise in `tools/shift/` is untouched.
