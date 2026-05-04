"""Thevenin (1-RC) model:

    V_t = OCV(SOC) - I*R0 - V_rc
    dV_rc/dt = I/C1 - V_rc/(R1*C1)
"""
from __future__ import annotations

from .base import BatteryModel, default_ocv, ocv_from_table


class TheveninModel(BatteryModel):
    name = "Thevenin (1-RC)"

    def __init__(self, capacity_Ah: float = 2.5, soc0: float = 1.0,
                 R0: float = 0.03, R1: float = 0.02, C1: float = 2000.0,
                 ocv=None, ocv_table=None):
        super().__init__(capacity_Ah, soc0)
        self.R0 = R0
        self.R1 = R1
        self.C1 = C1
        if ocv is not None:
            self._ocv = ocv
        elif ocv_table:
            self._ocv = ocv_from_table(ocv_table)
        else:
            self._ocv = default_ocv
        self._I = 0.0
        self._V_rc = 0.0

    def terminal_voltage(self, t: float, dt: float | None) -> float:
        return self._ocv(self.soc) - self._I * self.R0 - self._V_rc

    def update(self, I: float, dt: float, t: float) -> None:
        if dt > 0:
            tau = self.R1 * self.C1
            # Backward Euler on V_rc
            self._V_rc = (self._V_rc + dt * I / self.C1) / (1.0 + dt / tau)
        self._I = I
        super().update(I, dt, t)
