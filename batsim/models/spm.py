"""Single Particle Model (simplified, isothermal).

Each electrode is represented by a single spherical particle. We track the
volume-averaged Li concentration (mapped to stoichiometry x∈[0,1]) and use
electrode OCPs to compute the cell terminal voltage:

    V_t(t) = U_p(x_p) - U_n(x_n) - I*R0

where x_p, x_n update via Coulomb-like balance scaled by capacity.
This is a deliberately compact implementation — sufficient as a pedagogical
"electrochemistry" option in the model registry. For research-grade P2D,
plug in PyBaMM via a separate adapter.
"""
from __future__ import annotations

from .base import BatteryModel


def _Up(x: float) -> float:
    x = max(0.05, min(0.95, x))
    return 4.30 - 1.40 * x + 0.20 * (1 - x) ** 2


def _Un(x: float) -> float:
    x = max(0.05, min(0.95, x))
    return 0.10 + 0.30 * (1 - x) ** 3


class SPMModel(BatteryModel):
    name = "SPM"

    def __init__(self, capacity_Ah: float = 2.5, soc0: float = 1.0,
                 R0: float = 0.025,
                 x_p_full: float = 0.30, x_p_empty: float = 0.95,
                 x_n_full: float = 0.85, x_n_empty: float = 0.05):
        super().__init__(capacity_Ah, soc0)
        self.R0 = R0
        self.x_p_full, self.x_p_empty = x_p_full, x_p_empty
        self.x_n_full, self.x_n_empty = x_n_full, x_n_empty
        self._I = 0.0
        self._set_from_soc(soc0)

    def _set_from_soc(self, soc: float):
        s = max(0.0, min(1.0, soc))
        self.x_p = self.x_p_empty + (self.x_p_full - self.x_p_empty) * s
        self.x_n = self.x_n_empty + (self.x_n_full - self.x_n_empty) * s

    def terminal_voltage(self, t: float, dt: float | None) -> float:
        return _Up(self.x_p) - _Un(self.x_n) - self._I * self.R0

    def update(self, I: float, dt: float, t: float) -> None:
        self._I = I
        super().update(I, dt, t)
        self._set_from_soc(self.soc)
