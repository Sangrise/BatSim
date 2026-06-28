# BatSim

PSpice-style schematic editor + Python battery & BMS simulation engine.
Pure Python (PyQt6 + NumPy/SciPy).

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .            # exposes the `batsim` console script
```

## GUI

```powershell
batsim ui
# or:
python -m batsim_core ui
```

Drag components from the searchable left palette → click pin then pin to wire → `Ctrl+R` to simulate.
The palette has **Basic / Advanced / All** tabs; Basic is sized for electrical-engineering coursework and includes circuit, semiconductor, measurement, battery, grid, transformer, and PCS parts.

## CLI — everything is scriptable

```powershell
batsim list-models                # registered battery models
batsim list-cells                 # data files in data/cells/
batsim list-soc                   # SOC algorithms
batsim catalog --level basic --json
batsim route-check                # schematic wire-overlap smoke check
batsim inspect myproj.batsim --json
batsim validate myproj.batsim --dc --json

batsim run myproj.batsim --t-end 60 --dt 0.01 --csv out.csv
batsim run myproj.batsim --dc
batsim run myproj.batsim --t-end 60 --dt 0.01 --json

batsim cell-test --cell INR18650-25R --r-load 1.0 --t-end 3600 --csv discharge.csv

batsim sweep examples/sweep_example.json --csv sweep.csv

batsim blocks list --json
batsim blocks import my_pack_block.json --name "My pack"
batsim blocks export "My pack" out/my_pack_block.json

batsim soc-eval --script examples/external_soc_example.py \
                --algorithm CoulombCounter SimpleEKF SmoothedCC OCVLookup \
                --cell INR18650-25R --current 1.0 --t-end 1800 --csv soc.csv
```

## Extending — three ways, no source edits needed

| Method | Where to put it | Use for |
|---|---|---|
| **JSON cell** | `data/cells/*.json` | new cell with OCV table + RC params |
| **Python plugin** | `~/.batsim/plugins/*.py` (or `BATSIM_PLUGIN_PATH=…`) | new battery model / BMS block |
| **External SOC script** | any `.py` file → `batsim soc-eval --script path/to/algo.py` | drop-in SOC algorithms |

See `docs/EXTENDING.md` and `examples/`.

## Architecture

```
batsim_core/
  ui/        PyQt6 schematic editor (canvas, palette, inspector, waveforms)
  components/ R/L/C/V/I/SWITCH/DIODE/MOSFET/BATTERY/GND symbols
  engine/    MNA + Newton-Raphson MNA (DC + Backward-Euler transient)
  models/    BatteryModel ABC + Rint/Thevenin/n-RC/SPM/DataDriven
  bms/       SOC (CC/EKF), Protection, PassiveBalancer, CCCV, Pack
  plugins/   Decorator registry + auto-discovery (Python & data)
  soc/       External SOC algorithm framework (load_from_path)
  sim/       Headless helpers: cell_under_load, battery_profile_run, sweep
  cli/       argparse-driven `batsim` console script
  io/        Project save/load
data/
  cells/     JSON cell library (OCV + RC + capacity)
  bms/       JSON BMS profiles
docs/
  EXTENDING.md
examples/
  custom_plugin_example.py
  external_soc_example.py
  sweep_example.json
```

Roadmap: `plan.md`.


