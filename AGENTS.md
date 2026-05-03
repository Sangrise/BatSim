# AGENTS.md — BatSim Project Guide

> **Always read this file at the start of a new session.**
> It captures the current concept, architecture, feature inventory, and
> the working conventions a coding agent must follow to avoid breaking
> things or wasting time rediscovering them.

**Repository**: https://github.com/Sangrise/BatSim (private, `main` branch).
Use the standard `git add` / `git commit` / `git push` flow; commit
messages must end with the
`Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`
trailer.

---

## 1. Concept

BatSim is a desktop **schematic editor + numerical simulator** focused
on battery & BMS systems.

* **PSpice / Simulink-style UI** — drag-and-drop components, draw
  wires, double-click to set parameters.
* **Python solver** — modified-nodal-analysis (MNA), Newton iteration
  for non-linear devices and battery models.
* **Pluggable battery / BMS** — Rint, Thevenin, n-RC, SPM, DataDriven
  built-in; new chemistries via Python plug-ins; new cells via JSON
  data files only.
* **CLI parity** — every action available headless for sweeps and
  batch optimisation.
* **HTML manual** with screenshots, opens via F1, EN / KO with system
  language auto-detect.

---

## 2. Repository layout

```
BatSim/
├─ batsim/                       # Python package (solver + UI + plugins)
│  ├─ __init__.py, __main__.py, app.py
│  ├─ engine/                    # MNA, netlist, non-linear DC/transient
│  ├─ models/                    # Rint, Thevenin, n_rc, spm, data_driven
│  ├─ bms/                       # protection, balancer, controller, EKF
│  ├─ soc/                       # SOC algorithm registry + builtins
│  ├─ plugins/                   # plug-in registry + loader + builtin/
│  ├─ components/catalog.py      # symbol & pin geometry catalog
│  ├─ ui/
│  │  ├─ main_window.py          # MainWindow, SchematicView, edit menu
│  │  ├─ palette.py              # left dock — drag source for components
│  │  ├─ inspector.py            # right dock — parameter form
│  │  ├─ waveform_view.py        # bottom dock — multi-panel plots
│  │  ├─ simulation_dialog.py
│  │  ├─ help_dialog.py          # F1 manual viewer (HTML)
│  │  └─ canvas/
│  │     ├─ scene.py             # SchematicScene — components, wires,
│  │     │                       # tap junctions, preview, serialization
│  │     ├─ component_item.py    # ComponentItem — drag, rotate, mirror,
│  │     │                       # JUNCTION = pin (unified click model),
│  │     │                       # tap_wire projection
│  │     ├─ wire_item.py         # WireItem — orthogonal route, multi-
│  │     │                       # bend handles, manual-mode + auto-elbow
│  │     ├─ wire_routing.py      # pure-function orthogonal_route()
│  │     └─ crossings.py         # dot/hop overlay for wire intersections
│  ├─ cli/                       # `batsim` command — list/run/sweep/
│  │                             # cell-test/soc-eval
│  └─ io/project.py              # save/load .batsim JSON
├─ tests/                        # pytest — 47 tests, all green
├─ data/cells/*.json             # built-in cell presets
├─ examples/                     # external_soc_example.py, sweep config
├─ resources/help/
│  ├─ manual_en.html, manual_ko.html
│  └─ img/*.png                  # screenshots used by the manuals
├─ scripts/make_manual_screens.py# regenerate manual screenshots
├─ docs/EXTENDING.md             # short extension cheat-sheet
├─ plan.md                       # phase-by-phase development plan
└─ AGENTS.md                     # this file
```

---

## 3. Architecture (single diagram)

```
                                ┌──────────────────────────┐
                                │      ui.main_window      │
                                │  MainWindow              │
                                │  ├─ SchematicView        │
                                │  ├─ PaletteWidget (dock) │
                                │  ├─ InspectorWidget      │
                                │  ├─ WaveformView (dock)  │
                                │  └─ HelpDialog (F1)      │
                                └──────────────┬───────────┘
                                               │ uses
                                               ▼
        ┌───────────────────────────────────────────────────────────┐
        │                   ui.canvas.scene.SchematicScene          │
        │  add/remove component+wire ▸ try_finish_wire_at ▸         │
        │  tap junction placement ▸ orphan cleanup ▸ to/load_graph  │
        └─────┬───────────────────────────────────┬─────────────────┘
              │ contains                          │ contains
              ▼                                   ▼
   ui.canvas.component_item.ComponentItem  ui.canvas.wire_item.WireItem
        ▪ pin geometry, rotate/mirror keep wires
        ▪ JUNCTION = pin (clicked = begin_wire,
          dragged = slide along tap_wire only)
        ▪ uses ui.canvas.wire_routing.orthogonal_route() for paths

                │                                  ▲
                │ to_graph dict (JSON-serialisable) │
                ▼                                  │
        engine.netlist.from_graph ──► engine.mna ──► engine.nonlinear
                                       (build A, b)   (DC / transient,
                                                       Newton iter)
                ▲                                            │
                │ models[*]                                  │ result {t, x[]}
                │                                            ▼
       plugins.registry.make_battery       ui.waveform_view.WaveformView
        ▪ resolves model+cell                ▪ multi-panel plots
        ▪ loads JSON from data/cells/        ▪ probe alias map
        ▪ discovers plug-ins from
          batsim/plugins/builtin and
          ~/.batsim/plugins (+BATSIM_PLUGIN_PATH)

       cli.__init__ : argparse subcommands ── shares engine + plugins
       soc.__init__ : SOC algorithm registry  + auto-import script files
```

Key invariants enforced in code (don't break these):

* `JUNCTION` items must always sit on their `tap_wire`. If the wire is
  deleted or the tap-pin component disappears, `_cleanup_orphan_junctions`
  removes the junction.
* `ComponentItem.itemChange` for a JUNCTION with `tap_wire` set bypasses
  the normal grid snap and calls `_project_onto_tap_wire` so the node
  can only slide along the host wire.
* Wires never cross either endpoint component's body — both `a_comp`
  and `b_comp` are added as (slightly shrunk) blockers in `_blockers`
  so the router uses a U-detour around them.
* Every internal segment of a wire is slidable (`_slidable_segments`
  returns `range(0, n-1)`). `_slide_segment` auto-inserts an L-elbow
  when the slid segment is collinear with its neighbour or touches a
  pin, so the pin endpoint stays anchored.
* `to_graph` emits a synthetic wire `{a:"<jct>.0", b:"<tap_pin>",
  synthetic:true}` for every JUNCTION; `load_graph` skips synthetic
  wires and re-resolves `tap_wire` references at the end.

---

## 4. Feature inventory (current version)

### Editor
* Drag from palette → place component (snapped to 20 px grid).
* Drag-or-click wiring with **bright solid green preview** when over a
  valid target (pin or wire), faint dashed otherwise.
* No-op release in empty space (no floating wires).
* T-junction tap: drop wire on wire → JUNCTION created, original wire
  not split.
* Multi-bend handles on every internal segment (horizontal & vertical).
* Mouse rotate/mirror via right-click context menu; <kbd>R</kbd> /
  <kbd>M</kbd> shortcuts; pin-anchored translation keeps wires
  attached.
* Wire crossings: green dot if same node, hop arc if not.
* **Copy/Paste** (Ctrl+C / Ctrl+V) — components plus internal wires.
  Cross-instance via `BATSIM:<json>` clipboard text.  Pasted items
  remain selected so the user can drag the group immediately.
* **Undo / Redo** (Ctrl+Z / Ctrl+Y, also Ctrl+Shift+Z) — snapshot-based
  stack (max 200 steps) wired into `MainWindow._on_graph_changed_for_undo`.
  Tracks every emission of `scene.graphChanged` (add, delete, paste,
  rotate, mirror, drag-move).  Cached `_wf` waveforms and battery
  `model` instances are stripped before comparing snapshots so volatile
  state never produces phantom undo entries.
* **Outline panel** (`batsim/ui/outline.py`) — right-side dock listing
  every component and wire; selection is bidirectional with the canvas.
* **Blocks** — Ctrl+G saves selection to `~/.batsim/blocks/<name>.json`,
  Edit→Insert block menu lists them.

### Charge / discharge sources
* **ICONST** — constant current (linear, single `I` parameter).
* **PCONST** — constant power (nonlinear, Newton-stamped in
  `nonlinear.py:_stamp_pconst`, `_has_nonlinear` updated).
* **IPATTERN** — time-varying current sourced from a CSV.
  Waveform built once via `engine/sources.py:make_csv_waveform` and
  cached on `params['_wf']`.  Inspector shows a "…" file picker when
  the param key is `csv`.

### Simulation
* **DC operating point** — single-snapshot bias point at t=0
  (capacitors open, inductors shorted, AC sources held at DC value).
  Output: dict of node voltages.  Use as a sanity check before transient.
* **Transient** — time-domain integration 0→`t_end` with step `dt`.
  Required for any dynamic behaviour (caps, inductors, AC sources,
  battery SOC, PCS profiles, BMS state machines).
* `ui/simulation_dialog.py` shows inline help for both modes and an
  **"Auto from PCS cycle"** button that sets `t_end` =
  Σ(`max_time` / `time` over `cycle_steps`) × `cycle_repeat`, taking the
  max across all PCS components.  PCS cycles describe *what* to do;
  `t_end` decides *how long* to run — they're independent.
  `cycle_repeat=0` (infinite) requires manual `t_end`.
* Voltage probes (`PROBE` → V(P1)) and current probes
  (`IPROBE` → I(IP1)).
* If no probe placed, all node voltages and V-source currents exposed.

### Battery / BMS
* Built-in models: Rint, Thevenin, n-RC, SPM, DataDriven.
* **Chemistry-aware OCV** — `chemistry` parameter on Rint/Thevenin/n-RC
  selects an OCV table from `OCV_TABLES` in `batsim/models/base.py`
  (NCM, NCA, LCO, LFP, LTO, Generic). LFP shows the characteristic
  ~3.30 V plateau, LTO sits in 1.5–2.85 V, etc.  Inspector renders the
  parameter as a dropdown.
* Cell presets discovered from `data/cells/*.json` and
  `~/.batsim/data/cells/*.json`.  63 Ah NCM/LFP presets ship in-tree.
* Plug-in models from `batsim/plugins/builtin/` and
  `~/.batsim/plugins/` (override via `BATSIM_PLUGIN_PATH`).
* BMS package: protection, balancer, EKF SOC, controller, pack.

### Floating circuits & auto-ground
* `from_graph()` automatically inserts a node-0 anchor when no `GND`
  symbol is present.  Preference order:
  1. **`BUS` pin-1 is *always* unioned to node 0**, regardless of how
     many GND/BUS symbols the user placed.  This is the modern way to
     anchor a sheet — the BUS represents an explicit grid tie or test
     load that physically owns its reference.
  2. If neither GND nor BUS is present, the legacy fallback kicks in:
     negative pin of the first PCONST / ICONST / IPATTERN / I, then
     of the first BATTERY.
* Result: the user can wire `BATTERY ↔ BUS(Grid)` (or `BUS(PLoad)`,
  `BUS(ILoad)`) directly without ever placing a GND symbol.

### BUS — unified grid / load component
* Single 2-terminal symbol with a `mode` parameter:
  | mode    | Meaning                               | Stamp         |
  |---------|---------------------------------------|---------------|
  | `Grid`  | Stiff voltage source `V` (= grid tie) | linear V src  |
  | `PLoad` | Constant-power sink `P` [W]           | nonlinear     |
  | `ILoad` | Constant-current sink `I` [A]         | linear I src  |
* Pin 0 = "+", pin 1 = "−" (anchored to node 0).
* For PLoad we re-use `_stamp_pconst` so the same Newton damping kicks
  in below 0.5 V.
* Replaces the typical `GND + V/PCONST/ICONST` placement workflow with
  one drag-and-drop.

### TR — ideal turns-ratio coupler (AC- or DC-capable)
* 4-pin component (`p+`, `p−`, `s+`, `s−`).
  Constraint: `V(p+) − V(p−) = n · (V(s+) − V(s−))`,
  power balance fixes `I_s = −n · I_p`.
* **Not a physical AC transformer** — the engine has no magnetising or
  leakage inductance.  Use as an instantaneous voltage-scale coupler
  on either AC or DC side.  Each side still needs its own GND / BUS /
  GRID reference (otherwise the secondary mesh is singular).

### AC chain — GRID, TR, PCS

The simulator is time-domain (transient), so any sinusoidal source is
"AC" automatically.  Three components form the canonical AC→DC path:

```
GRID(AC) ── TR(optional) ── PCS(AC↔DC) ── BATTERY / BUS / R...
```

**GRID** — 2-pin sinusoidal source with `V_rms`, `freq` [Hz],
`phase_deg` and `bias`.  Internally builds a `make_sine_waveform`
peak = `V_rms·√2`, ω = `2π·freq`.  Pin 1 (neutral) is auto-grounded.

**PCS** — 4-pin power conversion system (AC↔DC).
| pin | role |
|-----|------|
| 0   | AC + |
| 1   | AC − (auto-anchored to 0) |
| 2   | DC + |
| 3   | DC − (auto-anchored to 0) |

`mode` parameter (9 modes — controller in `engine/pcs_control.py`):

| mode    | description | key params |
|---------|-------------|------------|
| `V_DC`  | Stiff DC voltage source | `V_DC_set` |
| `I_DC`  | Stiff DC current injector | `I_DC_set` |
| `P_DC`  | Constant DC power | `P_DC_set` |
| `CC`    | Constant current (profile) | `I_set` |
| `CV`    | Constant voltage (profile) | `V_set` |
| `CP`    | Constant power (profile) | `P_set` |
| `CCCV`  | CC until `V≥V_max`, then CV; terminate when `|I|≤I_term` | `I_set, V_max, I_term` |
| `CPCV`  | CP until `V≥V_max`, then CV; terminate when `|I|≤I_term` | `P_set, V_max, I_term` |
| `CYCLE` | Step list executed in order | `cycle_steps` (JSON), `cycle_repeat` |

**Sign convention** — `+` = charging (PCS sources current INTO DC+),
`−` = discharging.  Applies to `I_set / I_DC_set / P_set / P_DC_set`.

**`cycle_steps` JSON** — list of dicts; each step has a `mode` (any
single-mode name above) plus that mode's params and an optional
terminator (`max_time`, `V_max`, `V_min`, `I_term`).  Example:

```json
[{"mode":"CC","I":10,"V_max":3.6,"max_time":600},
 {"mode":"REST","time":300},
 {"mode":"CP","P":-50,"V_min":2.5,"max_time":900}]
```

`cycle_repeat=N` repeats the whole list N times (0 = forever).
The controller updates each PCS's `_active_mode / _active_V_DC /
_active_I_DC / _active_P_DC` fields once per timestep before the MNA
stamp; the stamps themselves never read user setpoints directly.

`eta` is bidirectional (single value v1).
**No galvanic isolation** — AC− and DC− share node 0.  For galvanic
modelling, place a TR on the AC side; the v1 PCS still couples node
0, so use TR for voltage scaling rather than isolation.

**Auto-ground (extended)** — `from_graph()` now anchors to node 0:
1. Every `BUS.pin1`,
2. Every `GRID.pin1` (neutral),
3. Every `PCS.pin1` (AC−) and `PCS.pin3` (DC−),
4. (legacy fallback) negative of first PCONST / ICONST / IPATTERN / I,
5. then first BATTERY.

**dt guidance** — for ≥20 samples per AC cycle use `dt ≤ 1/(20·f)`:
50 Hz → 1 ms; 60 Hz → 0.83 ms.

### Waveform viewer
* Vertical splitter of `_PlotPanel` rows; each row owns a primary
  ViewBox plus a secondary right-axis ViewBox (linked X).
* Per-signal axis assignment: click a row in the side list to cycle
  **Off → Left → Right → Off** (`AXIS_OFF`/`LEFT`/`RIGHT`).
* First simulation auto-splits the default panel into a **Voltage
  panel** (V signals on Left) and a **Current panel** (I signals on
  Left).  After that, panel layout/selections are preserved across runs
  and the user can `+ Add plot` or `Split V / I` from the toolbar.
* Right-axis traces are drawn dashed and tagged "(R)" in the legend.

### CLI (`batsim`)
* `ui` — launch GUI.
* `list-models | list-cells | list-bms | list-soc`.
* `run <project.batsim> [--dc | --t-end --dt --csv]`.
* `cell-test --cell --r-load --t-end [--csv]`.
* `sweep <config.json> [--csv --maximise]`.
* `soc-eval --script --algorithm ... --cell --current --t-end [--csv]`.

### Help
* HTML manual EN / KO under `resources/help/`.
* F1 opens; system language auto-detect, language toggle in-page.
* Screenshots embedded from `resources/help/img/` (regenerate with
  `python scripts/make_manual_screens.py`).

---

## 5. Working guide for agents

### 5.1 Environment
* Windows, Python 3.14, PyQt6.
* Run UI: `pythonw -m batsim ui` (use `pythonw` so no console window
  appears; `python` is fine for debugging stdout).
* Stop the UI without using name-based kills:
  ```powershell
  $p = Get-Process pythonw -ErrorAction SilentlyContinue
  if ($p) { $p | ForEach-Object { Stop-Process -Id $_.Id -Force } }
  ```
* Restart: `Start-Process pythonw -ArgumentList "-m","batsim","ui"`.
* Tests: `python -m pytest` from repo root. **Must stay 47/47 green.**

### 5.2 Tool-use rules
* Use the built-in `view`, `edit`, `create`, `grep`, `glob` tools in
  preference to PowerShell `Get-Content` / `Select-String` / `dir`.
* Make multiple independent file reads in parallel (single response).
* For long-running commands (tests, builds), prefer `initial_wait>=60`.
* Never use name-based `Stop-Process`; always `-Id <PID>`.

### 5.3 Code conventions
* No comment headers / docstrings on trivial methods. Comment only
  what needs clarification.
* All UI text the user sees can be Korean or English; keep status-bar
  hints short.
* Never break the JUNCTION-on-wire invariant. When you change wire
  add/remove or component delete, run the existing
  `_cleanup_orphan_junctions` (or call it explicitly).
* The router (`orthogonal_route`) is pure — no Qt widgets. Keep it
  that way so it can be unit-tested without `QApplication`.
* Routing strategy: try Z-route at the natural midpoint → fall back
  through every blocker-derived candidate lane → finally U-route over
  candidate lanes. **Every** path (including user-overridden mid)
  is validated against all blockers; if the user-supplied bend
  collides, the auto search takes over.
* When you change the router or wire item, regenerate manual
  screenshots: `python scripts/make_manual_screens.py`
  (uses `QT_QPA_PLATFORM=offscreen`, no display required).

### 5.4 Plan & checkpoint hygiene
* `plan.md` (repo root) tracks high-level phases — update when you
  finish a phase.
* Session-state checkpoints live under
  `~/.copilot/session-state/<id>/checkpoints/`. Read those at the
  start of a session to understand recent decisions; write a new
  checkpoint at the end summarising the work, files changed, open
  questions.

### 5.5 Common pitfalls
* `_handle_pos()` exists only for backwards compatibility with old
  tests; new code should call `_handle_positions()` and pick the
  segment it cares about explicitly.
* `tap_pin` (string `"R1.1"`) is for serialisation;
  `tap_wire` (object reference) is the runtime link. Re-resolve
  `tap_wire` from `tap_pin` after every `load_graph`.
* `pin_at` snaps to the nearest pin within `PIN_HIT_RADIUS`; tests
  that drop a wire end "on a wire" should use a coordinate clearly
  beyond that radius from any pin.
* `Inspector` shows model dropdowns by reading the plug-in registry,
  not by hard-coded lists. Adding a model in `~/.batsim/plugins/` is
  enough — restart only required for cells in `data/cells/`.

### 5.6 Where to look first when something breaks
| Symptom                                 | Look at                                |
|------------------------------------------|----------------------------------------|
| Wire crosses a component                | `WireItem._blockers`,                  |
|                                          | `wire_routing.orthogonal_route`        |
| JUNCTION drifts off wire / floats       | `ComponentItem._project_onto_tap_wire`,|
|                                          | `scene._cleanup_orphan_junctions`      |
| Bend handle missing                     | `WireItem._slidable_segments`          |
| Slide doesn't keep pin anchored         | `WireItem._slide_segment` elbow logic  |
| `pin_at` swallows a tap                 | `scene.try_finish_wire_at` first       |
|                                          | branch — adjust `PIN_HIT_RADIUS`       |
| Model not visible in inspector          | `plugins.registry.make_battery`,       |
|                                          | `plugins.loader` discovery paths       |
| Manual missing image                    | regenerate via                         |
|                                          | `scripts/make_manual_screens.py`       |

---

## 6. Roadmap notes (open work)
* CLI smoke tests cover the main subcommands; consider adding a
  `--profile` JSON for time-varying current sources.
* Block insertion currently keeps original IDs only on first paste;
  collisions on second paste use new auto-IDs.
* SPM model is simplified — no diffusion; document the limitation in
  the manual.
* Crossings overlay assumes axis-aligned segments; if a future feature
  introduces curved wires, `crossings._seg_cross` needs revisiting.

---

*Last updated together with the current manual revision. Bump this
file whenever architecture or invariants change.*
