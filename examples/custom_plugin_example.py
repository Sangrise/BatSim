"""Sample user plugin demonstrating the decorator-based extension API.

Place a copy of this file at ~/.batsim/plugins/ to load it automatically,
or point the BATSIM_PLUGIN_PATH env var at this folder.
"""
from batsim_core.models.base import BatteryModel
from batsim_core.plugins.registry import register_battery_model


@register_battery_model("LinearOCV")
class LinearOCVModel(BatteryModel):
    def __init__(self, capacity_Ah=2.0, soc0=1.0, a=3.0, b=1.2, R0=0.05):
        super().__init__(capacity_Ah, soc0)
        self.a = a
        self.b = b
        self.R0 = R0
        self._I = 0.0

    def terminal_voltage(self, t, dt):
        return self.a + self.b * self.soc - self._I * self.R0

    def update(self, I, dt, t):
        self._I = I
        super().update(I, dt, t)


