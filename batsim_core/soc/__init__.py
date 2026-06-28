"""External SOC algorithm framework.

Two equivalent ways for users to provide a SOC algorithm:

A) **Class with `step(I, V, dt) -> soc`** (stateful, recommended):

    from batsim_core.soc import register_soc_algorithm

    @register_soc_algorithm("MyEKF")
    class MyEKF:
        def __init__(self, capacity_Ah=2.5, soc0=1.0):
            self.soc = soc0
            ...
        def step(self, I, V, dt):
            ...
            return self.soc

B) **Function** decorated with the same `@register_soc_algorithm("Name")`:

    @register_soc_algorithm("MyOCV-LookUp")
    def my_estimator(state, I, V, dt):
        # state is a dict you mutate freely; first call gets state={}
        state["soc"] = ...
        return state["soc"]

Either form can be loaded from any `.py` file via `load_from_path()`.
The CLI exposes them through `batsim soc-eval --script path/to/algo.py`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable


SOC_ALGORITHMS: dict[str, Any] = {}


def register_soc_algorithm(name: str):
    """Decorator: register a SOC algorithm class or function under `name`."""
    def deco(obj):
        SOC_ALGORITHMS[name] = obj
        return obj
    return deco


@runtime_checkable
class SocAlgorithm(Protocol):
    def step(self, I: float, V: float, dt: float) -> float: ...


class _FunctionAdapter:
    """Wraps a plain function as a stateful SOC algorithm."""
    def __init__(self, fn: Callable, **kwargs):
        self._fn = fn
        self._state: dict = dict(kwargs)
        init = getattr(fn, "_soc_init", None)
        if callable(init):
            init(self._state)

    def step(self, I, V, dt):
        return float(self._fn(self._state, I, V, dt))

    @property
    def soc(self) -> float:
        return float(self._state.get("soc", 0.0))


def make_soc(name: str, **kwargs) -> SocAlgorithm:
    """Instantiate a registered SOC algorithm by name."""
    obj = SOC_ALGORITHMS.get(name)
    if obj is None:
        raise KeyError(f"Unknown SOC algorithm '{name}'. "
                       f"Registered: {sorted(SOC_ALGORITHMS)}")
    if isinstance(obj, type):
        import inspect
        sig = inspect.signature(obj.__init__)
        accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return obj(**accepted)
    return _FunctionAdapter(obj, **kwargs)


def list_soc_algorithms() -> list[str]:
    return sorted(SOC_ALGORITHMS.keys())


def load_from_path(path: str | Path) -> list[str]:
    """Import a Python file. Any decorated algorithms in it auto-register.

    Also auto-registers, by convention, any top-level class that defines
    `step(self, I, V, dt)` under its class name.

    Returns the list of *new* algorithm names that became available.
    """
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    before = set(SOC_ALGORITHMS)
    mod_name = f"_batsim_soc_{path.stem}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)

    import inspect
    for nm, obj in vars(module).items():
        if nm.startswith("_"):
            continue
        if inspect.isclass(obj) and hasattr(obj, "step") and nm not in SOC_ALGORITHMS:
            try:
                params = list(inspect.signature(obj.step).parameters)
                if params[1:4] == ["I", "V", "dt"]:
                    SOC_ALGORITHMS[nm] = obj
            except (TypeError, ValueError):
                pass

    return sorted(set(SOC_ALGORITHMS) - before)


# Built-in baseline algorithms ---------------------------------------------

@register_soc_algorithm("CoulombCounter")
class _CoulombCounterSoc:
    """Pure Coulomb counting baseline."""
    def __init__(self, capacity_Ah: float = 2.5, soc0: float = 1.0):
        self.capacity_Ah = capacity_Ah
        self.soc = soc0

    def step(self, I: float, V: float, dt: float) -> float:
        self.soc -= I * dt / 3600.0 / self.capacity_Ah
        self.soc = max(0.0, min(1.0, self.soc))
        return self.soc


@register_soc_algorithm("OCVLookup")
class _OCVLookupSoc:
    """SOC purely from OCV lookup. Assumes V ≈ OCV at near-zero current."""
    def __init__(self, soc0: float = 1.0, ocv_table: list | None = None):
        from batsim_core.models.base import default_ocv
        self._ocv = (lambda s: self._lookup(s, ocv_table)) if ocv_table else default_ocv
        self.soc = soc0

    @staticmethod
    def _lookup(soc, table):
        socs = [p[0] for p in table]
        ocvs = [p[1] for p in table]
        for i in range(len(socs) - 1):
            if socs[i] <= soc <= socs[i + 1]:
                t = (soc - socs[i]) / (socs[i + 1] - socs[i])
                return ocvs[i] + t * (ocvs[i + 1] - ocvs[i])
        return ocvs[-1]

    def step(self, I: float, V: float, dt: float) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if self._ocv(mid) < V:
                lo = mid
            else:
                hi = mid
        self.soc = 0.5 * (lo + hi)
        return self.soc

