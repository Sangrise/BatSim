"""Data-driven battery model.

Loads parameters (OCV-SOC table, R0, RC pairs, capacity, ...) from a
plain dict so a brand-new cell can be added by dropping a JSON file
into `data/cells/` — no Python required.

Schema (JSON):
    {
      "name": "LGM50T",
      "model": "DataDriven",
      "params": {
        "capacity_Ah": 5.0,
        "soc0": 1.0,
        "R0": 0.022,
        "RC_pairs": [[0.012, 1200], [0.018, 7000]],
        "ocv_table": [[0.0, 2.85], [0.1, 3.30], [0.5, 3.66],
                      [0.9, 4.05], [1.0, 4.18]]
      }
    }
"""
from __future__ import annotations

from .base import BatteryModel


class DataDrivenModel(BatteryModel):
    name = "DataDriven"

    def __init__(self, capacity_Ah: float = 2.5, soc0: float = 1.0,
                 R0: float = 0.03,
                 RC_pairs: list[tuple[float, float]] | None = None,
                 ocv_table: list[tuple[float, float]] | None = None):
        super().__init__(capacity_Ah, soc0)
        self.R0 = R0
        self.RC_pairs = list(RC_pairs) if RC_pairs else []
        self._V = [0.0 for _ in self.RC_pairs]
        # Sort OCV table by SOC
        table = sorted(ocv_table or [(0.0, 3.0), (1.0, 4.2)], key=lambda p: p[0])
        self._socs = [p[0] for p in table]
        self._ocvs = [p[1] for p in table]
        self._I = 0.0

    def ocv(self, soc: float) -> float:
        s = max(self._socs[0], min(self._socs[-1], soc))
        # Linear interpolation
        for i in range(len(self._socs) - 1):
            if self._socs[i] <= s <= self._socs[i + 1]:
                x0, x1 = self._socs[i], self._socs[i + 1]
                y0, y1 = self._ocvs[i], self._ocvs[i + 1]
                if x1 == x0:
                    return y0
                return y0 + (y1 - y0) * (s - x0) / (x1 - x0)
        return self._ocvs[-1]

    def terminal_voltage(self, t: float, dt: float | None) -> float:
        return self.ocv(self.soc) - self._I * self.R0 - sum(self._V)

    def update(self, I: float, dt: float, t: float) -> None:
        if dt > 0:
            for k, (R, C) in enumerate(self.RC_pairs):
                tau = R * C
                self._V[k] = (self._V[k] + dt * I / C) / (1.0 + dt / tau)
        self._I = I
        super().update(I, dt, t)
