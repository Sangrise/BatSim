"""Battery model abstract base class.

Convention:
    - Positive current I means *discharging* (current leaving the positive terminal).
    - SOC is in [0, 1].
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BatteryModel(ABC):
    name: str = "base"

    def __init__(self, capacity_Ah: float = 2.5, soc0: float = 1.0):
        self.capacity_Ah = capacity_Ah
        self.soc = soc0
        self.t = 0.0

    @abstractmethod
    def terminal_voltage(self, t: float, dt: float | None) -> float:
        """Return terminal voltage V_t at time t (under current internal state)."""

    def update(self, I: float, dt: float, t: float) -> None:
        """Advance the internal state by dt with current I."""
        self.t = t
        if dt > 0:
            # Coulomb counting: SOC decreases when discharging (I>0)
            dsoc = -I * dt / 3600.0 / self.capacity_Ah
            self.soc = max(0.0, min(1.0, self.soc + dsoc))


# ---------------------------------------------------------------------------
# Chemistry-specific OCV(SOC) tables.  Values are typical for fresh cells at
# 25°C; they reproduce the qualitative shapes that distinguish the chemistries
# (LFP plateau, NCM slope, etc.).  Tables are interpolated linearly.

OCV_TABLES: dict[str, list[tuple[float, float]]] = {
    "NCM": [
        (0.00, 3.00), (0.05, 3.40), (0.10, 3.50), (0.20, 3.58),
        (0.30, 3.63), (0.40, 3.68), (0.50, 3.74), (0.60, 3.81),
        (0.70, 3.89), (0.80, 3.99), (0.90, 4.10), (1.00, 4.20),
    ],
    "NCA": [
        (0.00, 3.00), (0.05, 3.42), (0.10, 3.55), (0.20, 3.62),
        (0.30, 3.66), (0.40, 3.70), (0.50, 3.76), (0.60, 3.83),
        (0.70, 3.92), (0.80, 4.02), (0.90, 4.12), (1.00, 4.20),
    ],
    "LCO": [
        (0.00, 3.00), (0.05, 3.40), (0.10, 3.55), (0.20, 3.65),
        (0.30, 3.72), (0.40, 3.78), (0.50, 3.84), (0.60, 3.90),
        (0.70, 3.97), (0.80, 4.05), (0.90, 4.13), (1.00, 4.20),
    ],
    "LFP": [
        # Strong plateau between 20–90% — the LFP signature.
        (0.00, 2.50), (0.03, 2.95), (0.05, 3.15), (0.10, 3.23),
        (0.20, 3.27), (0.30, 3.28), (0.50, 3.30), (0.70, 3.32),
        (0.85, 3.34), (0.90, 3.36), (0.95, 3.45), (1.00, 3.65),
    ],
    "LTO": [
        # ~2.5 V flat plateau, narrow window 1.5–2.8.
        (0.00, 1.50), (0.05, 2.20), (0.10, 2.32), (0.20, 2.40),
        (0.40, 2.45), (0.60, 2.50), (0.80, 2.58), (0.95, 2.70),
        (1.00, 2.85),
    ],
    "Generic": [
        (0.00, 3.00), (0.10, 3.30), (0.30, 3.55), (0.50, 3.70),
        (0.70, 3.85), (0.90, 4.05), (1.00, 4.20),
    ],
}


def chemistry_ocv(name: str):
    """Return an OCV(soc) function backed by a chemistry preset table.

    Falls back to ``default_ocv`` if the name is unknown.
    """
    table = OCV_TABLES.get(name)
    if not table:
        return default_ocv
    socs = [p[0] for p in table]
    ocvs = [p[1] for p in table]

    def ocv(soc: float, _s=socs, _v=ocvs) -> float:
        s = max(_s[0], min(_s[-1], soc))
        for i in range(len(_s) - 1):
            if _s[i] <= s <= _s[i + 1]:
                x0, x1 = _s[i], _s[i + 1]
                y0, y1 = _v[i], _v[i + 1]
                if x1 == x0:
                    return y0
                return y0 + (y1 - y0) * (s - x0) / (x1 - x0)
        return _v[-1]

    return ocv


def default_ocv(soc: float) -> float:
    """Smooth Li-ion-like OCV-SOC fallback (3.0..4.2 V)."""
    s = max(0.0, min(1.0, soc))
    return 3.0 + 1.2 * s - 0.15 * (1 - s) ** 2 + 0.10 * s * (1 - s)
