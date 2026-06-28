"""Charge / discharge controllers."""
from __future__ import annotations


class CCCVController:
    """Constant-Current / Constant-Voltage charging controller.

    Returns the *commanded* current (positive = discharge, negative = charge),
    given the cell's terminal voltage.
    """
    def __init__(self, I_charge: float = 1.0, V_cv: float = 4.20,
                 I_taper: float = 0.05, mode: str = "charge"):
        self.I_charge = I_charge        # A (magnitude)
        self.V_cv = V_cv                # CV target voltage
        self.I_taper = I_taper          # current cutoff
        self.mode = mode                # "charge" | "discharge" | "rest"

    def command(self, V_t: float) -> float:
        if self.mode == "discharge":
            return self.I_charge
        if self.mode == "rest":
            return 0.0
        # charge
        if V_t < self.V_cv - 1e-3:
            return -self.I_charge       # CC region
        # CV region: simple proportional taper
        I = -self.I_charge * max(0.0, (self.V_cv - V_t) / 0.05)
        if abs(I) < self.I_taper:
            return 0.0
        return I
