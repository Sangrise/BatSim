"""n-RC model (generalised Thevenin with n parallel RC branches)."""
from __future__ import annotations

from .base import BatteryModel, default_ocv, ocv_from_table


class NRCModel(BatteryModel):
    name = "n-RC"

    def __init__(self, capacity_Ah: float = 2.5, soc0: float = 1.0,
                 R0: float = 0.03,
                 RC_pairs: list[tuple[float, float]] | None = None,
                 ocv=None, ocv_table=None):
        super().__init__(capacity_Ah, soc0)
        self.R0 = R0
        # Default 2-RC: fast + slow dynamics
        self.RC_pairs = RC_pairs or [(0.015, 1500.0), (0.025, 8000.0)]
        self._V = [0.0 for _ in self.RC_pairs]
        if ocv is not None:
            self._ocv = ocv
        elif ocv_table:
            self._ocv = ocv_from_table(ocv_table)
        else:
            self._ocv = default_ocv
        self._I = 0.0

    def terminal_voltage(self, t: float, dt: float | None) -> float:
        return self._ocv(self.soc) - self._I * self.R0 - sum(self._V)

    def update(self, I: float, dt: float, t: float) -> None:
        if dt > 0:
            for k, (R, C) in enumerate(self.RC_pairs):
                tau = R * C
                self._V[k] = (self._V[k] + dt * I / C) / (1.0 + dt / tau)
        self._I = I
        super().update(I, dt, t)
