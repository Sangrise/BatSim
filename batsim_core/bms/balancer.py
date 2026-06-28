"""Passive (resistive) cell balancer."""
from __future__ import annotations


class PassiveBalancer:
    def __init__(self, R_bleed: float = 33.0, threshold_V: float = 0.02):
        self.R_bleed = R_bleed
        self.threshold = threshold_V

    def select(self, cell_voltages: list[float]) -> list[bool]:
        """Return on/off mask per cell. Cells above min+threshold are bled."""
        if not cell_voltages:
            return []
        v_min = min(cell_voltages)
        return [v > v_min + self.threshold for v in cell_voltages]
