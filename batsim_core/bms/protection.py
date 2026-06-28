"""Cell-level protection logic."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProtectionLimits:
    V_over: float = 4.25
    V_under: float = 2.80
    I_over: float = 20.0
    T_over: float = 60.0
    T_under: float = -20.0


class Protector:
    def __init__(self, limits: ProtectionLimits | None = None):
        self.limits = limits or ProtectionLimits()
        self.fault: str | None = None

    def check(self, V: float, I: float, T: float = 25.0) -> bool:
        L = self.limits
        if V > L.V_over:
            self.fault = "OV"
        elif V < L.V_under:
            self.fault = "UV"
        elif abs(I) > L.I_over:
            self.fault = "OC"
        elif T > L.T_over:
            self.fault = "OT"
        elif T < L.T_under:
            self.fault = "UT"
        else:
            self.fault = None
        return self.fault is None
