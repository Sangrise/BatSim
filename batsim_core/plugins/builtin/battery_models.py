"""Register built-in battery models with the plugin registry."""
from __future__ import annotations

from batsim_core.plugins.registry import register_battery_model
from batsim_core.models.rint import RintModel
from batsim_core.models.thevenin import TheveninModel
from batsim_core.models.n_rc import NRCModel
from batsim_core.models.spm import SPMModel
from batsim_core.models.data_driven import DataDrivenModel


register_battery_model("Rint")(RintModel)
register_battery_model("Thevenin")(TheveninModel)
register_battery_model("n-RC")(NRCModel)
register_battery_model("SPM")(SPMModel)
register_battery_model("DataDriven")(DataDrivenModel)

