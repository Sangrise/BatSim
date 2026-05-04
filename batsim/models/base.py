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
# OCV(SOC) helpers.  The simulator no longer ships chemistry presets — the
# user is expected to supply real cell data via a CSV folder under
# ``data/cells/<your-cell>/`` (see ``batsim.plugins.loader``).  ``default_ocv``
# remains as a safety net so a battery without an ``ocv_table`` still
# simulates instead of crashing.


def default_ocv(soc: float) -> float:
    """Generic Li-ion OCV-SOC fallback (3.0..4.2 V).

    Used only when no ``ocv_table`` is supplied — the result is a smooth
    qualitative curve, NOT a chemistry-accurate one.  For meaningful
    simulations attach a cell folder with real ``ocv.csv`` data.
    """
    s = max(0.0, min(1.0, soc))
    return 3.0 + 1.2 * s - 0.15 * (1 - s) ** 2 + 0.10 * s * (1 - s)


def ocv_from_table(table) -> "callable":
    """Build a piecewise-linear OCV(soc) function from a list of [soc, V]
    rows.  Returns ``default_ocv`` if the table is empty / unusable."""
    rows = sorted(((float(s), float(v)) for s, v in (table or [])),
                  key=lambda p: p[0])
    if len(rows) < 2:
        return default_ocv
    socs = [p[0] for p in rows]
    ocvs = [p[1] for p in rows]

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
