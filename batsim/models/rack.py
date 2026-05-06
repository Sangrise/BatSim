"""Battery rack — series chain of ``BatteryPackModel`` instances.

A rack is the next composition step above a pack:
    rack  = n_packs_series × pack
    pack  = n_series × n_parallel cells
The rack acts as a single ``BatteryModel``-shaped block (terminal_voltage /
update / soc) so it stamps into the MNA engine identically to a BATTERY
or BATPACK element.
"""
from __future__ import annotations

from typing import Any, Callable

from .pack import BatteryPackModel


class BatteryRackModel:
    name = "BatteryRack"

    def __init__(self,
                 n_packs_series: int = 1,
                 pack_factory: Callable[[], BatteryPackModel] | None = None):
        self.n_packs_series = max(1, int(n_packs_series))
        if pack_factory is None:
            pack_factory = lambda: BatteryPackModel()
        self.packs: list[BatteryPackModel] = [
            pack_factory() for _ in range(self.n_packs_series)
        ]
        self.t = 0.0
        self._I = 0.0
        self._V_packs: list[float] = [0.0] * self.n_packs_series

    # ---- BMS hook: propagate balancer config to every pack -----------
    def set_balancer(self, name: str | None, **params) -> None:
        for p in self.packs:
            p.set_balancer(name, **params)

    # ---- Future thermal hook: propagate per-cell thermal model -------
    def set_thermal_model(self, factory: Callable[[], Any] | None) -> None:
        """Install a per-cell thermal model across every pack."""
        for p in self.packs:
            p.set_thermal_model(factory)

    # ---- BatteryModel compatibility ---------------------------------
    @property
    def soc(self) -> float:
        return sum(p.soc for p in self.packs) / len(self.packs)

    @property
    def capacity_Ah(self) -> float:
        # Series-stacking packs adds voltage, not Ah.  All packs assumed
        # identical so the rack capacity equals one pack's capacity.
        return float(self.packs[0].capacity_Ah)

    @property
    def I_rack(self) -> float:
        """Latest rack terminal current (positive = discharge).

        Current is measured **once per rack** — every series-stacked
        pack and every series-stacked cell inside those packs sees the
        same current, so there's nothing to gain from per-pack/per-cell
        I probes at the rack level.
        """
        return float(self._I)

    def pack_voltages(self) -> list[float]:
        """Latest per-pack terminal V, length ``n_packs_series``."""
        return list(self._V_packs)

    def cell_voltages(self) -> list[list[list[float]]]:
        """Per-cell V across the whole rack, shape ``[pack][row][string]``."""
        return [p.cell_voltages() for p in self.packs]

    def cell_temperatures(self) -> list[list[list[float]]]:
        """Per-cell T [°C] across the whole rack, shape ``[pack][row][string]``."""
        return [p.cell_temperatures() for p in self.packs]

    def terminal_voltage(self, t: float, dt: float | None) -> float:
        vs = [p.terminal_voltage(t, dt) for p in self.packs]
        # Cache per-pack V so an external probe layer can read the
        # individual series-stacked pack voltages.
        self._V_packs = [float(v) for v in vs]
        return sum(vs)

    def update(self, I: float, dt: float, t: float) -> None:
        self.t = t
        self._I = I
        # Series chain — every pack sees the same current.
        for p in self.packs:
            p.update(I=I, dt=dt, t=t)

