"""Series/parallel pack composition utilities (logical, not graphical)."""
from __future__ import annotations

from typing import Callable, Iterable


class CellPack:
    """Logical pack of `s` cells in series, `p` strings in parallel.

    Each cell is created via `cell_factory()` so cells stay independent.
    """
    def __init__(self, s: int, p: int, cell_factory: Callable):
        self.s = s
        self.p = p
        self.strings: list[list] = [
            [cell_factory() for _ in range(s)] for _ in range(p)
        ]

    @property
    def cells(self) -> list:
        return [c for string in self.strings for c in string]

    def terminal_voltage(self) -> float:
        # Average of strings (ideal); each string sums series voltages.
        sums = [sum(c.terminal_voltage(0.0, None) for c in s) for s in self.strings]
        return sum(sums) / len(sums)

    def update(self, I_pack: float, dt: float, t: float) -> None:
        I_string = I_pack / self.p
        for s in self.strings:
            for c in s:
                c.update(I=I_string, dt=dt, t=t)

    def soc_avg(self) -> float:
        socs = [c.soc for c in self.cells]
        return sum(socs) / len(socs)
