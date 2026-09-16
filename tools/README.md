# Analysis toolkit

Offline Python implementation of the torque model, for validating against
logged data before any of it reaches firmware.

Not a MATLAB replacement in general — just the parts this project needs.
numpy/scipy/matplotlib do everything on the validation list, and this code
doubles as the **golden reference** for testing the eventual C implementation:
push the same vectors through both and diff the results.

## Install & run

**Linux / macOS**

```bash
pip install numpy matplotlib pandas
python3 tools/demo.py out
```

**Windows** — use `python` (or the `py` launcher), not `python3`. On Windows
`python3` is a Microsoft Store stub that will not run this.

```cmd
pip install numpy matplotlib pandas
python tools\demo.py out
```

Plots are written with the Agg backend, so no display is needed on any
platform.

The demo generates a synthetic log, deliberately injects a **7% injector flow
error**, and shows the residual plots finding it. Expected output:

```
VE error vs truth       +7.00 %  (injected: +7.00 %)
torque mean error       +14.7 Nm
```

## Three ways to work with it

| | Command | Good for |
|---|---|---|
| **Cells in VS Code** | open `tools/explore.py`, click **Run Cell** | Change a value, re-run one cell, plot updates beside your code. The main workflow. |
| **Sliders** | `python tools\playground.py` | Dragging parameters and watching curves move in real time |
| **Batch** | `python tools\demo.py out` | Regenerating the full plot set to files |

`tools/explore.py` is a plain `.py` file with `# %%` markers — VS Code's Python
extension turns each block into a runnable cell with inline plots, and it still
diffs properly in git, unlike an `.ipynb`.

Press **F5** in VS Code to run either entry point; both are in
`.vscode/launch.json`.

## Modules

| Module | Purpose |
|---|---|
| `model.py` | Forward and inverse torque model, plus `authority()` |
| `ve.py` | Back-calculate VE from logged pulse width and lambda (VE autotune) |
| `dynamics.py` | Manifold filling ODE — the transient correction the steady-state VE equation lacks |
| `plots.py` | The validation plots that earn their keep |
| `units.py` | kPa absolute ↔ boost psi, Nm ↔ lb-ft |
| `synth.py` | Synthetic log generator, so this runs before Phase 0 exists |
| `explore.py` | Cell-based exploration for VS Code |
| `playground.py` | Interactive sliders |

## Units

The model works in **kPa absolute** throughout — the ideal gas law does not
accept gauge pressure. Boost in psi is a *display* unit: plots take
`boost_axis=True` (default) for psi, `False` for kPa absolute. Convert at the
plot, never in the model.

Also fixed: spark in **degrees BTDC, positive = advanced**; air mass in **grams
per cylinder per cycle**; torque in **Nm**; **lambda**, not AFR.

## Plots

- `table_heatmap` — the coloured tuning-table view, values annotated, grey for
  cells the logs never visited
- `ve_surface_3d` — 3D surface, for the physical plausibility audit
- `torque_validation` — model vs reference, overlay and 1:1 scatter
- `residual_grid` — **the important one.** Residual against each input; a
  *slope* names the broken term
- `coverage` — where the logs actually went, and where you would be
  extrapolating

## Replacing the synthetic data

`synth.py` exists only because Phase 0 has not happened. Swap it for real DME
logs and nothing downstream changes — the demo's structure is the real
workflow.

Note that the synthetic knock limit is a hand-written guess, so any conclusion
drawn from it about where authority is scarce is an artifact of that guess, not
a property of the engine. Real distributions come from real logs.

The drive cycle uses independent smoothed random walks for RPM and load
deliberately. Correlated inputs make a fault in one term bleed into another
term's residual panel, which defeats the point of plotting residuals per
input -- with sine-driven cycles an RPM-dependent fault showed a spurious
slope against air mass.
