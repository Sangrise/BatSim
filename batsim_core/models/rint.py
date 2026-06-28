"""Rint model: V_t = OCV(SOC) - I * R0."""
from __future__ import annotations

from .base import BatteryModel, default_ocv, ocv_from_table


class RintModel(BatteryModel):
    name = "Rint"

    def __init__(self, capacity_Ah: float = 2.5, soc0: float = 1.0,
                 R0: float = 0.05, ocv=None, ocv_table=None):
        super().__init__(capacity_Ah, soc0)
        self.R0 = R0
        if ocv is not None:
            self._ocv = ocv
        elif ocv_table:
            self._ocv = ocv_from_table(ocv_table)
        else:
            self._ocv = default_ocv
        self._I = 0.0

    def terminal_voltage(self, t: float, dt: float | None) -> float:
        return self._ocv(self.soc) - self._I * self.R0

    def update(self, I: float, dt: float, t: float) -> None:
        self._I = I
        super().update(I, dt, t)
