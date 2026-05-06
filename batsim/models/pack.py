"""Series/parallel battery pack as a single ``BatteryModel``-compatible block.

Pack topology: ``n_series`` rows, ``n_parallel`` strings.  Cells in the same
row share the row voltage; current splits evenly across strings.  Each cell
is an independent inner battery model so SOC drift, OCV imbalance and
balancing all behave realistically.

Public surface mirrors ``BatteryModel``:
    - ``terminal_voltage(t, dt)``  — pack terminal V (sum over series rows)
    - ``update(I, dt, t)``         — advance every cell, apply balancer bleeds
    - ``soc``                       — pack average SOC (read-only property)
"""
from __future__ import annotations

from typing import Any, Callable

from .base import BatteryModel
from ..bms.cell_balancer import make_balancer


class BatteryPackModel:
    """Logical s×p pack wrapping a grid of inner ``BatteryModel`` instances."""

    name = "BatteryPack"

    def __init__(self,
                 n_series: int = 1,
                 n_parallel: int = 1,
                 cell_factory: Callable[[], BatteryModel] | None = None,
                 soc_init_spread: float = 0.0,
                 balancer: str | None = None,
                 **balancer_params):
        self.n_series = max(1, int(n_series))
        self.n_parallel = max(1, int(n_parallel))
        if cell_factory is None:
            from .thevenin import TheveninModel
            cell_factory = lambda: TheveninModel()
        # cells[r][s] = cell on series row r, parallel string s
        self.cells: list[list[BatteryModel]] = [
            [cell_factory() for _ in range(self.n_parallel)]
            for _ in range(self.n_series)
        ]
        # ---- Per-cell measurement / future-thermal hooks ----------------
        # Every series-stacked cell needs its own V; current is measured
        # once per pack/rack so we don't decorate cells with I.  T_cell
        # is reserved for a future thermal sim — `thermal_model` is a
        # per-cell plug-in slot (None = isothermal at T_cell).
        for row in self.cells:
            for c in row:
                if not hasattr(c, "V_cell"):
                    c.V_cell = 0.0
                if not hasattr(c, "T_cell"):
                    c.T_cell = 25.0  # °C, ambient default
                if not hasattr(c, "thermal_model"):
                    c.thermal_model = None
                if not hasattr(c, "I_cell"):
                    # Stored only so a future thermal model has access
                    # to the per-cell current it dissipates; not exposed
                    # as a probe-able pack measurement.
                    c.I_cell = 0.0
        # Apply a deterministic SOC spread so balancing has work to do
        # without the user having to hand-edit per-cell SOCs.
        if soc_init_spread > 0.0:
            flat = [c for row in self.cells for c in row]
            n = len(flat)
            if n > 1:
                for i, c in enumerate(flat):
                    delta = soc_init_spread * (i / (n - 1) - 0.5)
                    c.soc = max(0.0, min(1.0, c.soc + delta))
        # One balancer instance *per parallel string* so per-cell timer
        # state (`_remaining`) doesn't collide across strings.
        self._balancer_name = balancer
        self._balancer_params = dict(balancer_params)
        self._string_balancers: list = [
            make_balancer(balancer, **balancer_params)
            for _ in range(self.n_parallel)
        ]
        self.t = 0.0
        self._I = 0.0

    # ---- BMS hook: swap balancer config across all strings at runtime ----
    def set_balancer(self, name: str | None, **params) -> None:
        """Replace the per-string balancers with new instances.

        Used by the ``BMS`` component to override whatever balancer was
        configured on the BATPACK/BATRACK at construction time.  Pass
        ``name="None"`` (or ``None``) to disable balancing.
        """
        self._balancer_name = name
        self._balancer_params = dict(params)
        self._string_balancers = [
            make_balancer(name, **params) for _ in range(self.n_parallel)
        ]

    @property
    def balancer(self):
        # Compatibility shim: returns the first string's balancer.
        return self._string_balancers[0] if self._string_balancers else None

    # ---- BatteryModel compatibility ----
    @property
    def soc(self) -> float:
        flat = [c for row in self.cells for c in row]
        return sum(c.soc for c in flat) / len(flat)

    @property
    def capacity_Ah(self) -> float:
        # Pack capacity = per-cell capacity × n_parallel (series doesn't add Ah).
        c0 = self.cells[0][0]
        return float(getattr(c0, "capacity_Ah", 0.0)) * self.n_parallel

    @property
    def I_pack(self) -> float:
        """Latest pack terminal current (positive = discharge)."""
        return float(self._I)

    def cell_voltages(self) -> list[list[float]]:
        """Latest per-cell terminal V, shape ``[n_series][n_parallel]``."""
        return [[float(getattr(c, "V_cell", 0.0)) for c in row]
                for row in self.cells]

    def cell_temperatures(self) -> list[list[float]]:
        """Latest per-cell T [°C], shape ``[n_series][n_parallel]``.

        Returned values come from each cell's ``T_cell`` attribute.  Until
        a thermal model is wired up, every cell stays at the ambient
        default (25 °C).
        """
        return [[float(getattr(c, "T_cell", 25.0)) for c in row]
                for row in self.cells]

    def set_thermal_model(self, factory: Callable[[], Any] | None) -> None:
        """Attach a per-cell thermal model (or ``None`` to remove).

        Reserved for a future feature.  ``factory()`` should return an
        object exposing ``update(I_cell, V_cell, dt, t) -> T_new``.  The
        pack will call it inside ``update`` once per cell per step.
        """
        for row in self.cells:
            for c in row:
                c.thermal_model = factory() if factory is not None else None

    def terminal_voltage(self, t: float, dt: float | None) -> float:
        v = 0.0
        for row in self.cells:
            v_cells = [c.terminal_voltage(t, dt) for c in row]
            # Cache per-cell V so the (future) probe / measurement layer
            # can read it back without re-evaluating the cell models.
            for c, vc in zip(row, v_cells):
                c.V_cell = float(vc)
            v_row = sum(v_cells) / len(v_cells)
            v += v_row
        return v

    def update(self, I: float, dt: float, t: float) -> None:
        self.t = t
        self._I = I
        # Pack convention matches BatteryModel: positive I = discharge.
        I_string = I / self.n_parallel
        # Compute bleed currents row-by-row so the balancer sees the
        # series string of cells (one cell per row, one of the strings).
        for s in range(self.n_parallel):
            string_cells = [self.cells[r][s] for r in range(self.n_series)]
            bal = self._string_balancers[s]
            if bal is None:
                bleeds = [0.0] * len(string_cells)
            else:
                # Try the new signature (with per-string current for the
                # rest detector); fall back to the old one for any custom
                # balancer that hasn't adopted the I_pack kwarg.
                try:
                    bleeds = bal.bleed_currents(string_cells, dt, t,
                                                I_pack=I_string)
                except TypeError:
                    bleeds = bal.bleed_currents(string_cells, dt, t)
            for r, cell in enumerate(string_cells):
                I_cell = I_string + (bleeds[r] if r < len(bleeds) else 0.0)
                cell.I_cell = float(I_cell)
                cell.update(I=I_cell, dt=dt, t=t)
                # Future thermal hook — isothermal until a model is set.
                tm = getattr(cell, "thermal_model", None)
                if tm is not None:
                    try:
                        cell.T_cell = float(tm.update(
                            I_cell=I_cell,
                            V_cell=getattr(cell, "V_cell", 0.0),
                            dt=dt, t=t,
                        ))
                    except Exception:
                        pass
