# Extending BatSim

BatSim is built around a plugin registry. There are **two ways** to add new
battery models or BMS blocks — pick whichever is appropriate for your need.

## Option 1 — Data-only (no Python)

Drop a JSON (or YAML, if PyYAML is installed) file into one of:

- `data/cells/`  — battery cell parameters
- `data/bms/`    — BMS profile parameters

You can also use a per-user folder: `~/.batsim/data/cells/` etc.

A cell file uses this schema:

```json
{
  "name": "MyCell-2Ah",
  "model": "DataDriven",
  "params": {
    "capacity_Ah": 2.0,
    "soc0": 1.0,
    "R0": 0.025,
    "RC_pairs": [[0.012, 1500], [0.020, 8000]],
    "ocv_table": [[0.0, 2.9], [0.5, 3.7], [1.0, 4.18]]
  }
}
```

Restart batsim_core. The new cell appears in the Inspector → "cell (preset)"
dropdown when a `BATTERY` component is selected. Selecting it copies the
parameters into the component.

## Option 2 — Python plugin (custom equations)

Create a `.py` file under `~/.batsim/plugins/`, or set the
`BATSIM_PLUGIN_PATH` env var to a folder containing your modules:

```python
# my_chem.py
from batsim_core.models.base import BatteryModel
from batsim_core.plugins.registry import register_battery_model

@register_battery_model("MyChem")
class MyChemModel(BatteryModel):
    def __init__(self, capacity_Ah=2.0, soc0=1.0, alpha=0.5):
        super().__init__(capacity_Ah, soc0)
        self.alpha = alpha

    def terminal_voltage(self, t, dt):
        return 3.0 + self.alpha * self.soc
```

The same decorator pattern works for BMS blocks:

```python
from batsim_core.plugins.registry import register_bms_block

@register_bms_block("MyController")
class MyController:
    def __init__(self, target_soc=0.8):
        self.target_soc = target_soc
    def command(self, soc):
        return -1.0 if soc < self.target_soc else 0.0
```

Restart BatSim — `MyChem` will appear in the Inspector model dropdown.

## Switching existing models

Every model registered in the plugin registry is selectable per-component
from the Inspector → `model` dropdown. There is no need to edit code or
the schematic; settings are stored in the `.batsim` project file as
`{"model": "Rint", ...}`.


