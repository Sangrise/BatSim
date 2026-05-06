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
* Voltage probes (`PROBE` → V(P1)). `PROBE` is differential — wire both
  pins to the two nodes you want to measure (V_pos − V_neg). Floating
  pin1 falls back to GND.
* Current probes (`IPROBE` → I(IP1)). **Single-clamp UX**: drag IPROBE
  onto an existing wire — it auto-splits the wire and clamps on. Empty-
  space drops are refused. Symbol is two concentric circles + "A"/"I"
  label, no visible pins/stubs. Internally still a 0-V source, hence
  `pins=2` in the catalog.
* If no probe placed, all node voltages and V-source currents exposed.

### Battery / BMS
* Built-in models: Rint, Thevenin, n-RC, SPM, DataDriven.
* **Series/parallel pack component (`BATPACK`)** — single 2-terminal symbol
  representing `n_series × n_parallel` independent inner cells.  Pack
  terminal V = sum over series rows of (mean parallel cell V); pack
  current is split evenly across strings.  All cells share the same
  `model` / `cell` preset and per-cell parameters (`R0`, `R1`, `C1`,
  `capacity_Ah`, `soc0`).  ``soc_init_spread`` injects a deterministic
  per-cell SOC offset so balancing has work to do without hand-edits.
* **Rack component (`BATRACK`)** — single 2-terminal symbol representing
  `n_packs_series` BATPACKs stacked in series.  Terminal V = Σ pack
  voltages; the same current flows through every pack.  Inherits all of
  BATPACK's per-cell knobs plus `n_packs_series`.  Each inner pack owns
  its own per-string balancers (one per `n_parallel` string).
* **BMS component (`BMS`)** — virtual (non-electrical, `pins=0`)
  controller that owns a *control domain* of one or more battery
  components.  Parameters:
  - `targets`: comma-separated list of battery component IDs
    (BATTERY/BATPACK/BATRACK), e.g. `"BR1,BR2"`.  Empty = controls
    nothing.
  - `balancer`: combo box.  `Inherit` (default) leaves each target's
    own balancer alone; any other algorithm (e.g. `PassiveV1`) is
    pushed into every targeted model via `model.set_balancer(...)`,
    overriding what was configured per-pack.
  - `balancer_*`: same tunables as on BATPACK (`soc_enable`, `dev_min`,
    `dev_max`, `soc_drop`, `I_bal`, `pack_pause`, `pack_resume`,
    `rest_min`, `I_rest`).
  Multiple BMSes can coexist with disjoint target sets — one BMS for
  many racks (uniform logic), or one BMS per rack (independent logic).
  BMS components are dropped from the netlist (no MNA stamp) and
  applied as a post-processing pass at the end of `from_graph`.
* **Per-cell measurement surface** (BATPACK / BATRACK):
  - Every series-stacked cell has its own `V_cell` (cached in
    `terminal_voltage`), `T_cell` (default 25 °C), and `I_cell`
    (per-string current after balancer bleed — kept for the future
    thermal model, not exposed as a probe).
  - Pack/rack expose `cell_voltages()` (2D / 3D nested lists matching
    `cells` / `packs`) and `cell_temperatures()` for read-back.
  - Rack also exposes `pack_voltages()` for series-stacked pack V.
  - Current is measured **once per pack/rack** via `I_pack` / `I_rack`
    properties — series-stacked cells/packs see identical current, so
    no per-cell I probe is needed.
  - **Thermal hook (placeholder)**: `set_thermal_model(factory)` on
    pack or rack installs a per-cell object exposing
    `update(I_cell, V_cell, dt, t) -> T_new`.  Pack `update()` calls
    it once per cell per step and writes the result to `cell.T_cell`.
    No built-in thermal model yet — slot reserved for a future feature.
* **Cell balancer** — combo box on `BATPACK.balancer`:
  - `None` — balancing disabled.
  - `PassiveV1` — series-string passive bleed.  Per-cell trigger:
    `cell SOC ≥ balancer_soc_enable` (default 0.46) AND
    `balancer_dev_min ≤ (cell SOC − min cell SOC) < balancer_dev_max`
    (defaults 0.02 and 1.0; `dev_max` excludes outlier cells whose
    deviation from the min is implausibly large).
    When triggered, the cell bleeds at `balancer_I_bal` A (default 1A)
    for the duration needed to drop `balancer_soc_drop` of SOC at that
    current (`Δt = soc_drop·Q·3600/I`).  Once a slot is started it runs
    to completion regardless of pack charge/discharge/rest.  Pack-level
    pause/resume hysteresis on average SOC: pause at
    `balancer_pack_pause` (default 0.05), resume at
    `balancer_pack_resume` (default 0.08).  Active slots are frozen
    (timer doesn't tick) while paused.
    **Continuous-rest gate**: a *new* slot only starts after the pack
    has been at rest (`|I_pack| ≤ balancer_I_rest`, default 0.05 A)
    for at least `balancer_rest_min` seconds (default 1800 = 30 min).
    The `_rest_dur` accumulator resets to 0 the moment rest is broken.
    Already-running slots are unaffected — they continue draining
    through subsequent charge/discharge until their own timer expires.
  All `balancer_*` thresholds are user-editable via the Inspector.
  New algorithms register via `@register_balancer("Name")` in
  `batsim/bms/cell_balancer.py` — the decorator also auto-publishes the
  class to the global `BMS_BLOCKS` registry under `balancer:<Name>` so
  it appears in `batsim list-bms`.
* **No built-in chemistry presets.** Real cell data must be supplied
  via a CSV folder under `data/cells/<your-cell>/` (see
  `batsim/plugins/loader.py`):
  - `meta.csv`  key/value (name, model, capacity_Ah, R0, ...)
  - `ocv.csv`   header `soc,V_oc` → params["ocv_table"]
  - `ocv_chg.csv`, `ocv_dch.csv` (optional — hysteresis)
  - `rc_pairs.csv` header `R,C` → params["RC_pairs"]
  - any other `*.csv` → preserved under `params["_extra"][<stem>]`
  Folders are auto-discovered on every CLI/UI start; the user can drop
  in new cells with no code change.
* Models accept `ocv_table` (list of `[soc, V_oc]`) directly; `chemistry`
  is no longer accepted (silently dropped on legacy graphs).
* `default_ocv` in `models/base.py` is a generic 3.0–4.2 V fallback for
  cells without an OCV table — qualitative only, NOT chemistry-accurate.
* Sole shipping cell: `data/cells/NCM-50Ah-csv/`. Add your own folders
  alongside it.
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

`mode` parameter (10 modes — controller in `engine/pcs_control.py`):

| mode           | description | key params |
|----------------|-------------|------------|
| `CYCLE`        | **Recommended cycler.** Step-list executed in order; each step has a Type (Charge/Discharge CC or CP, CV, Rest) plus optional V/I/time terminators.  Edit via the **Cycle Steps Editor** dialog (PNE-cycler-style table) launched from the Inspector's `cycle_steps` field. | `cycle_steps` (JSON), `cycle_repeat` |
| `CYCLE_SIMPLE` | Legacy 7-parameter cycler: chg_cc → rest → dis_cc → rest, repeat × `cyc_count`. | `cyc_I_chg, cyc_I_dis, cyc_V_max, cyc_V_min, cyc_t_rest, cyc_count` |
| `V_DC`  | Stiff DC voltage source | `V_DC_set` |
| `I_DC`  | Stiff DC current injector | `I_DC_set` |
| `P_DC`  | Constant DC power | `P_DC_set` |
| `CC`    | Constant current (profile) | `I_set` |
| `CV`    | Constant voltage (profile) | `V_set` |
| `CP`    | Constant power (profile) | `P_set` |
| `CCCV`  | CC until `V≥V_max`, then CV; terminate when `|I|≤I_term` | `I_set, V_max, I_term` |
| `CPCV`  | CP until `V≥V_max`, then CV; terminate when `|I|≤I_term` | `P_set, V_max, I_term` |

**Sign convention (user-facing)** — `+` = charging, `−` = discharging
for `I_set / I_DC_set / P_set / P_DC_set` and `cyc_I_chg`.

**Per-cell V termination (series packs)** — for any V threshold key
(`V_max`, `V_min`, `cyc_V_max`, `cyc_V_min`, plus the `V_max`/`V_min`
inside `cycle_steps`), append `_cell` (e.g. `V_max_cell`,
`cyc_V_min_cell`, `V_max_cell` inside a step) to express the limit
**per cell**. The controller multiplies it by `n_series` (PCS param,
default 1) to obtain the pack-level threshold. The Cycle Steps dialog
exposes this as a "Per-cell V limits (×N series)" toggle. `_cell`
keys take precedence when both are present.

**Cycle-time auto-estimate** — `_estimate_pcs_total_time`
(simulation_dialog.py) now uses an energy/power heuristic for CC and
CP steps (`t ≈ 3600 · Ah · V_nom / |P|`) capped by `max_time`, instead
of blindly summing the safety-cap `max_time` of every step. Greatly
improves the "Auto from PCS cycle" button accuracy.

**Waveform filtering with explicit probes** — when at least one PROBE
or IPROBE is present, `WaveformView.show_results()` suppresses the
default "every node voltage / every V-source current" dump and shows
only the named `V(P*)` / `I(IP*)` aliases. Drop a PROBE/IPROBE if you
want a focused view; place none for full visibility.

**Internal note** (don't break this) — `_set_active(elem, "I_DC", i=...)`
uses the *MNA stamp* sign: charging is `i = -|I_chg|` because
`_stamp_current(b, n_from=DC-, n_to=DC+, I)` injects `+I` into DC+ in
the network's KCL but the resulting battery `vs_current` (positive =
discharge by battery convention) ends up with the opposite sign. The
CYCLE_SIMPLE / CYCLE handlers already handle the flip; only touch this
if you also re-derive the stamp.

**⚠ KNOWN INVERTED CONVENTION (CYCLE / CC / CP / CCCV / CPCV)** — the
non-`_SIMPLE` modes pass `I_step` / `P_step` to `_set_active` *without*
the `-|·|` flip that CYCLE_SIMPLE applies.  Net effect at the battery:
**`+I_set / +P_set` actually DISCHARGES the battery, `−` CHARGES.**
Verified empirically (CC `+25A` for 120s on a SOC=0.5, 100Ah pack →
SOC drops to 0.4917).  The unit tests
(`test_pcs_profiles.py::test_pcs_cc_charge_current_steady`,
`test_pcs_cycle_alternates_charge_rest_discharge`) only assert that
`I_PCS` *equals* `I_set` — they are sign-blind on actual SOC change,
so the bug has been latent.  The example
`examples/grid_pcs_2bat_cycle.batsim` is authored against the actual
(inverted) convention: step 0 = `CP −50` (= charge), step 2 =
`CP +50` (= discharge).  When fixing this for real, you must
simultaneously: (a) flip the I_DC stamp at `mna.py:216` to
`_stamp_current(b, e.nodes[2], e.nodes[3], I_dc)`, (b) flip the P_DC
Norton orientation in `nonlinear.py::_stamp_pcs_dc_pmode`, (c) flip
sign of stored `I_PCS` so the existing tests still pass, **and**
(d) flip the example file's `cycle_steps` back to the natural
`+ = charge` form.  Until then: document the workaround in the UI
and in any new examples.

**PCS Newton stamp fix (commit `60f5f63`)** — `_stamp_pcs_dc_pmode`
previously used `g = −P/V²` for the source-side admittance, which
caused 3× over-injection at convergence (observer reported `I=P/V`
while actual through-current was `3·P/V`).  Fixed to `g = +P/V²`,
`Ieq = 2·I0`, and the observer row is now coupled into the DC node
voltages so `iv = Ieq − g·Vd` returns the actual through-current.
KCL now holds to machine precision.  Adaptive Newton damping
(`solve_nonlinear_step`) drops 0.7 → 0.3 once `‖Δx‖∞ > 5.0` after
iteration 2 because the corrected Norton produces an indefinite
Jacobian near voltage sign-flips.

**Why CYCLE_SIMPLE has no CV taper** — the battery V-source stamp uses
the previous step's `self._I` for `V_t = OCV − I·R0 − V_rc`. Forcing
`V_DC = V_max` while OCV is also at saturation creates a fixed point
where `I` never tapers to `I_term`, so the cycle never advances. The
simple CC↔rest cycler avoids this entirely. Re-add CV only if the
battery model exposes a stable terminal_voltage decoupled from
`self._I`.

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
* Right axis (ticks + label) is hidden whenever no signal is assigned
  to it, and reappears the moment a row is cycled to `RIGHT`.

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
* `pin_at` snaps to the nearest pin within `PIN_HIT_RADIUS = 18`; tests
  that drop a wire end "on a wire" should use a coordinate clearly
  beyond that radius from any pin.
* `IPROBE` is special: catalog `pins=2` (engine still treats it as a
  0-V source for current measurement) but `ComponentItem` suppresses
  pin dots and pin clicks, and `SchematicScene.add_component` refuses
  empty-space drops. The user must drop IPROBE *onto an existing wire*
  → `_insert_iprobe_on_wire` auto-splits and clamps it on. Don't re-
  enable pin clicks for IPROBE without a strong reason.
* `Inspector` shows model dropdowns by reading the plug-in registry,
  not by hard-coded lists. Adding a model in `~/.batsim/plugins/` is
  enough; cells under `data/cells/<name>/` are picked up by every
  `discover()` call (CLI startup + UI `refresh_if_changed`) — no
  restart required.

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
