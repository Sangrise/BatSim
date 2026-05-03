"""Global registries for plugin-discoverable models and BMS blocks."""
from __future__ import annotations

from typing import Any, Callable, TypeVar

# kind -> class
BATTERY_MODELS: dict[str, type] = {}
BMS_BLOCKS: dict[str, type] = {}

# data-driven catalogs: name -> dict (parameters)
CELL_LIBRARY: dict[str, dict] = {}
BMS_LIBRARY: dict[str, dict] = {}

T = TypeVar("T", bound=type)


def register_battery_model(name: str) -> Callable[[T], T]:
    """Class decorator: register a battery model under `name`.

    Example::

        @register_battery_model("MyChem")
        class MyChemModel(BatteryModel):
            ...
    """
    def deco(cls: T) -> T:
        BATTERY_MODELS[name] = cls
        cls.name = name
        return cls
    return deco


def register_bms_block(name: str) -> Callable[[T], T]:
    """Class decorator: register a BMS block (estimator/controller/etc.)."""
    def deco(cls: T) -> T:
        BMS_BLOCKS[name] = cls
        cls.name = name
        return cls
    return deco


def list_battery_models() -> list[str]:
    return sorted(BATTERY_MODELS.keys())


def list_cells() -> list[str]:
    return sorted(CELL_LIBRARY.keys())


def list_bms_profiles() -> list[str]:
    return sorted(BMS_LIBRARY.keys())


def make_battery(model_name: str | None = None,
                 cell: str | None = None,
                 **overrides) -> Any:
    """Build a battery model instance.

    - If `cell` references a CELL_LIBRARY entry, that JSON's parameters are
      used as defaults; `model_name` falls back to the cell's "model" field.
    - `overrides` win over cell defaults.
    """
    params: dict[str, Any] = {}
    if cell and cell in CELL_LIBRARY:
        params.update(CELL_LIBRARY[cell].get("params", {}))
        model_name = model_name or CELL_LIBRARY[cell].get("model")
    params.update(overrides)
    if model_name is None:
        model_name = "Thevenin"
    cls = BATTERY_MODELS.get(model_name)
    if cls is None:
        raise KeyError(f"Unknown battery model '{model_name}'. "
                       f"Available: {list_battery_models()}")
    # Filter kwargs the class actually accepts
    import inspect
    sig = inspect.signature(cls.__init__)
    accepted = {k: v for k, v in params.items() if k in sig.parameters}
    return cls(**accepted)


def make_bms(block_name: str, profile: str | None = None, **overrides) -> Any:
    params: dict[str, Any] = {}
    if profile and profile in BMS_LIBRARY:
        params.update(BMS_LIBRARY[profile].get("params", {}))
    params.update(overrides)
    cls = BMS_BLOCKS.get(block_name)
    if cls is None:
        raise KeyError(f"Unknown BMS block '{block_name}'. "
                       f"Available: {sorted(BMS_BLOCKS.keys())}")
    import inspect
    sig = inspect.signature(cls.__init__)
    accepted = {k: v for k, v in params.items() if k in sig.parameters}
    return cls(**accepted)
