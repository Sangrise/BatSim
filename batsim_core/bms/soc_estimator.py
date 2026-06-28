"""Simple SOC estimators."""
from __future__ import annotations


class CoulombCounter:
    def __init__(self, capacity_Ah: float, soc0: float = 1.0):
        self.capacity_Ah = capacity_Ah
        self.soc = soc0

    def update(self, I: float, dt: float) -> float:
        # I>0 means discharge -> SOC decreases
        self.soc -= I * dt / 3600.0 / self.capacity_Ah
        self.soc = max(0.0, min(1.0, self.soc))
        return self.soc
