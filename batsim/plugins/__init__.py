"""Plugin / extension system for BatSim.

Two extension surfaces are exposed:

1. **Python plugins** — modules that register classes via decorators
   (`@register_battery_model("MyCell")`, `@register_bms_block("MyController")`).
   At startup we import every `*.py` file under:
       - `batsim/plugins/builtin/`         (shipped with BatSim)
       - any path in env var `BATSIM_PLUGIN_PATH` (";" separated)
       - `~/.batsim/plugins/`              (user)

2. **Data plugins** — JSON / YAML files that parameterise a generic
   data-driven model. The schema is documented in `data_models.py`.
   We scan:
       - `data/cells/*.json`  (and *.yaml)         -> battery cell catalog
       - `data/bms/*.json`                          -> BMS profiles
       - `data/models/*.json`                       -> arbitrary model overrides

Once discovered, entries become available in:
   - `batsim.plugins.registry.BATTERY_MODELS`
   - `batsim.plugins.registry.BMS_BLOCKS`
   - `batsim.plugins.registry.CELL_LIBRARY`
   - `batsim.plugins.registry.BMS_LIBRARY`
"""
from .registry import (
    BATTERY_MODELS,
    BMS_BLOCKS,
    CELL_LIBRARY,
    BMS_LIBRARY,
    register_battery_model,
    register_bms_block,
    list_battery_models,
    list_cells,
    list_bms_profiles,
    make_battery,
    make_bms,
)
from .loader import discover, refresh_if_changed

__all__ = [
    "BATTERY_MODELS", "BMS_BLOCKS", "CELL_LIBRARY", "BMS_LIBRARY",
    "register_battery_model", "register_bms_block",
    "list_battery_models", "list_cells", "list_bms_profiles",
    "make_battery", "make_bms", "discover", "refresh_if_changed",
]
