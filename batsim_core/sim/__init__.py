"""Headless simulation helpers used by the CLI and parameter sweeps."""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

from batsim_core.engine.netlist import Netlist, Element
from batsim_core.engine.nonlinear import solve_transient
from batsim_core.plugins.registry import make_battery


def cell_under_load(cell: str | None = None,
                    model_name: str | None = None,
                    R_load_ohm: float = 1.0,
                    t_end: float = 60.0,
                    dt: float = 0.1,
                    **model_kwargs) -> dict:
    """Discharge a cell through a fixed resistive load. Returns time series
    plus the live battery model object (for SOC inspection)."""
    bat = make_battery(model_name=model_name, cell=cell, **model_kwargs)
    nl = Netlist()
    nl.add(Element("BATTERY", "B1", ["n1", "0"], {}, model=bat))
    nl.add(Element("R", "Rload", ["n1", "0"], {"R": float(R_load_ohm)}))
    res = solve_transient(nl, t_end=t_end, dt=dt)
    res["model"] = bat
    return res


def battery_profile_run(cell: str | None = None,
                        model_name: str | None = None,
                        I_profile: Callable[[float], float] | np.ndarray | None = None,
                        t_end: float = 60.0,
                        dt: float = 0.1,
                        **model_kwargs) -> dict:
    """Drive a battery cell by a prescribed current profile (positive = discharge).

    Bypasses MNA — we evaluate the cell's `terminal_voltage` and `update` directly,
    which is the standard methodology used for cell characterisation and SOC
    algorithm validation.

    Returns dict with arrays: t, I, V (terminal voltage), SOC.
    """
    bat = make_battery(model_name=model_name, cell=cell, **model_kwargs)

    if isinstance(I_profile, np.ndarray):
        prof = np.asarray(I_profile, dtype=float)
        def current_at(t):
            i = min(int(round(t / dt)), len(prof) - 1)
            return float(prof[i])
    elif callable(I_profile):
        current_at = I_profile
    elif I_profile is None:
        current_at = lambda t: 1.0
    else:
        current_at = lambda t: float(I_profile)

    n = int(round(t_end / dt)) + 1
    ts = np.linspace(0.0, (n - 1) * dt, n)
    I_arr = np.zeros(n)
    V_arr = np.zeros(n)
    SOC_arr = np.zeros(n)

    for k, t in enumerate(ts):
        I = current_at(t)
        V = bat.terminal_voltage(t, dt if k > 0 else None)
        I_arr[k] = I
        V_arr[k] = V
        SOC_arr[k] = bat.soc
        if k < n - 1:
            bat.update(I=I, dt=dt, t=t)

    return {"t": ts, "I": I_arr, "V": V_arr, "SOC": SOC_arr,
            "model": bat}


def parameter_sweep(base_kwargs: dict, grid: dict[str, list],
                    metric: Callable[[dict], float],
                    runner: Callable[..., dict] = battery_profile_run) -> list[dict]:
    """Cartesian-product sweep over `grid`. Returns list of {params, metric, result}."""
    import itertools
    keys = list(grid.keys())
    out = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        params = dict(base_kwargs)
        params.update(dict(zip(keys, combo)))
        res = runner(**params)
        out.append({"params": dict(zip(keys, combo)),
                    "metric": float(metric(res))})
    return out

