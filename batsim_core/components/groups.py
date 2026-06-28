"""Component grouping shared by GUI palette and CLI catalog output."""
from __future__ import annotations

from batsim_core.components.catalog import CATALOG


BASIC_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Fundamentals", ("R", "L", "C", "V", "I", "GND", "SWITCH")),
    ("Semiconductors", ("DIODE", "MOSFET")),
    ("Measurements", ("PROBE", "IPROBE")),
    ("Battery & Loads", ("BATTERY", "BATPACK", "ICONST", "PCONST", "BUS")),
    ("AC / Conversion", ("GRID", "TR", "PCS")),
)

ADVANCED_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Pack / BMS Systems", ("BATRACK", "BMS")),
    ("Profiles & Automation", ("IPATTERN",)),
)

HIDDEN_FROM_PALETTE = {"JUNCTION"}


def grouped_catalog(level: str = "all") -> list[dict]:
    """Return palette/catalog entries grouped for humans and automation."""
    if level == "basic":
        groups = BASIC_GROUPS
    elif level == "advanced":
        groups = ADVANCED_GROUPS
    elif level == "all":
        groups = BASIC_GROUPS + ADVANCED_GROUPS
    else:
        raise ValueError(f"unknown component level: {level}")

    out: list[dict] = []
    seen: set[str] = set()
    for title, kinds in groups:
        items = []
        for kind in kinds:
            if kind in HIDDEN_FROM_PALETTE or kind not in CATALOG:
                continue
            spec = CATALOG[kind]
            items.append({
                "kind": kind,
                "label": spec["label"],
                "pins": spec["pins"],
                "defaults": dict(spec.get("default_params", {})),
            })
            seen.add(kind)
        if items:
            out.append({"group": title, "items": items})

    if level == "all":
        uncategorized = []
        for kind, spec in CATALOG.items():
            if kind in seen or kind in HIDDEN_FROM_PALETTE:
                continue
            uncategorized.append({
                "kind": kind,
                "label": spec["label"],
                "pins": spec["pins"],
                "defaults": dict(spec.get("default_params", {})),
            })
        if uncategorized:
            out.append({"group": "Other", "items": uncategorized})
    return out


def palette_kinds(level: str = "all") -> list[str]:
    kinds: list[str] = []
    for group in grouped_catalog(level):
        for item in group["items"]:
            kinds.append(item["kind"])
    return kinds

