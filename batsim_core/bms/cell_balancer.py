"""Cell-balancing algorithm registry + built-in passive balancers.

Cell balancing is a BMS function — these algorithms are registered both
in the local balancer registry (used by the BATPACK component) and in
``BMS_BLOCKS`` (the global BMS plugin registry, used by ``batsim
list-bms``).

A balancer object owns its own state and exposes a single method::

    bleed_currents(cells, dt, t) -> list[float]

Returns the *bleed* current (Amps, ≥0) drawn from each individual cell during
the next ``dt`` seconds.  The model integrates this on top of the pack
current when updating each cell's coulomb-counter.

Each algorithm declares its own user-tunable parameters via the class
attribute ``PARAMS = {name: default}``.  The Inspector reads this to show
editable fields under a ``balancer_*`` prefix in the BATPACK component.
"""
from __future__ import annotations

from typing import Any

from ..plugins.registry import register_bms_block


_REGISTRY: dict[str, type] = {}


def register_balancer(name: str):
    """Register a cell-balancing algorithm.

    Also exposes the class through the global BMS_BLOCKS registry so
    ``batsim list-bms`` and external tooling can discover it.
    """
    def deco(cls):
        cls.name = name
        _REGISTRY[name] = cls
        # Prefix avoids colliding with future BMS controllers/estimators.
        register_bms_block(f"balancer:{name}")(cls)
        return cls
    return deco


def list_balancers() -> list[str]:
    return ["None"] + sorted(_REGISTRY.keys())


def make_balancer(name: str | None, **params) -> "CellBalancerBase | None":
    if not name or name == "None":
        return None
    cls = _REGISTRY.get(name)
    if cls is None:
        return None
    accepted = {k: params[k] for k in cls.PARAMS if k in params}
    return cls(**accepted)


class CellBalancerBase:
    PARAMS: dict[str, float] = {}

    def bleed_currents(self, cells, dt: float, t: float) -> list[float]:
        return [0.0] * len(cells)


@register_balancer("PassiveV1")
class PassiveBalancerV1(CellBalancerBase):
    """Passive bleed balancer, series-string oriented.

    Trigger (per cell, on each row across parallel strings):
      - cell SOC ≥ ``soc_enable`` (default 0.46)
      - (cell SOC − min cell SOC) ≥ ``dev_min`` (default 0.02)
      - (cell SOC − min cell SOC) <  ``dev_max`` (default 1.0)
        — cells with an extreme gap to min are excluded as outliers.

    When triggered, the cell bleeds at ``I_bal`` Amps for the time required
    to drop ``soc_drop`` of SOC at that current (Δt = soc_drop·Q·3600/I).
    Once a bleed slot is started it runs to completion regardless of pack
    charge/discharge/rest state.

    Pack-level safety:
      - Pause balancing when pack avg SOC ≤ ``pack_pause`` (default 0.05).
      - Resume balancing when pack avg SOC ≥ ``pack_resume`` (default 0.08).
    """
    PARAMS = {
        "soc_enable": 0.46,    # SOC at/above which we evaluate per-cell bleed
        "dev_min":    0.02,    # min (cell - min_cell) gap to start bleed
        "dev_max":    1.0,     # exclude cells with (cell - min_cell) ≥ this
        "soc_drop":   0.001,   # SOC delta the bleed slot tries to drain
        "I_bal":      1.0,     # bleed current per active cell (A)
        "pack_pause": 0.05,    # pack avg SOC ≤ this → pause new + active bleeds
        "pack_resume":0.08,    # pack avg SOC ≥ this → resume balancing
        "rest_min":   1800.0,  # required continuous rest [s] before NEW slots
        "I_rest":     0.05,    # |I_pack| ≤ this [A] counts as rest
    }

    def __init__(self, **kw):
        for k, default in self.PARAMS.items():
            setattr(self, k, float(kw.get(k, default)))
        self._remaining: list[float] | None = None  # seconds left per cell
        self._paused = False
        self._rest_dur = 0.0  # continuous rest time accumulator [s]

    def _ensure(self, n: int) -> None:
        if self._remaining is None or len(self._remaining) != n:
            self._remaining = [0.0] * n

    def bleed_currents(self, cells, dt: float, t: float,
                       I_pack: float | None = None) -> list[float]:
        n = len(cells)
        self._ensure(n)
        socs = [float(getattr(c, "soc", 0.0)) for c in cells]
        if not socs:
            return []
        avg = sum(socs) / n

        # Pack-level pause hysteresis. Active bleeds are also suspended
        # (they "freeze"): no current flows but the timer doesn't tick down,
        # so the bleed resumes for its remaining duration after recovery.
        if self._paused:
            if avg >= self.pack_resume:
                self._paused = False
        else:
            if avg <= self.pack_pause:
                self._paused = True

        if self._paused:
            return [0.0] * n

        # Continuous-rest tracker: balancing only *starts* once the pack
        # has been resting (|I_pack| ≤ I_rest) for at least ``rest_min``
        # seconds. If I_pack is unknown, fall back to cell[0].I_cell
        # (set by the pack on the previous step). Active slots keep
        # running regardless of whether rest is broken — the spec only
        # gates *new* bleed initiations on rest duration.
        if I_pack is None:
            I_pack = float(getattr(cells[0], "I_cell", 0.0)) * len(cells)
        if abs(I_pack) <= self.I_rest:
            self._rest_dur += dt
        else:
            self._rest_dur = 0.0
        rest_ok = self._rest_dur >= self.rest_min

        smin = min(socs)
        slot_len = max(1e-9, self.soc_drop * 3600.0 *
                       max(1e-9, float(getattr(cells[0], "capacity_Ah", 1.0))) /
                       max(1e-9, self.I_bal))

        out = [0.0] * n
        for i, c in enumerate(cells):
            if self._remaining[i] > 0.0:
                # Already in an active bleed slot: keep draining.
                out[i] = self.I_bal
                self._remaining[i] = max(0.0, self._remaining[i] - dt)
            else:
                dev = socs[i] - smin
                # Sanity exclusion: cells whose deviation from the min is
                # absurdly large (default ≥100% SOC, i.e. effectively never)
                # are dropped from the candidate set.
                if dev >= self.dev_max:
                    continue
                # Eligible to start a new slot?  Requires sustained rest.
                if (rest_ok and socs[i] >= self.soc_enable
                        and dev >= self.dev_min):
                    self._remaining[i] = slot_len
                    out[i] = self.I_bal
                    self._remaining[i] = max(0.0, self._remaining[i] - dt)
        return out

    def state(self) -> dict[str, Any]:
        return {"paused": self._paused,
                "remaining": list(self._remaining or []),
                "rest_dur": self._rest_dur}
