"""Circuit graph -> netlist representation consumed by the MNA engine.

A netlist is a small dataclass describing nodes and elements.
Each element references nodes by name (strings). Node "0" / "GND" is ground.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Element:
    kind: str                # "R", "L", "C", "V", "I", "BATTERY", "SWITCH", "DIODE", ...
    name: str
    nodes: list[str]         # ordered terminal nodes
    params: dict[str, Any] = field(default_factory=dict)
    model: Any | None = None  # optional dynamic model object (e.g., BatteryModel)


@dataclass
class Netlist:
    elements: list[Element] = field(default_factory=list)

    @property
    def nodes(self) -> list[str]:
        seen: list[str] = []
        for e in self.elements:
            for n in e.nodes:
                if n not in seen:
                    seen.append(n)
        # Ensure ground first
        for g in ("0", "GND"):
            if g in seen:
                seen.remove(g)
                seen.insert(0, g)
                break
        return seen

    def add(self, el: Element) -> None:
        self.elements.append(el)


def from_graph(graph: dict) -> Netlist:
    """Convert a UI circuit graph (JSON dict) to a Netlist.

    Pins connected through wires get unified to the same node id.
    PROBE / JUNCTION elements are dropped (passive — only affect topology).

    If no GND component is present anywhere in the graph, an automatic
    ground is added by tying the *negative* (pin-1) terminal of the first
    load-style element (PCONST / ICONST / IPATTERN / I) — or the negative
    pin of the first BATTERY as a last resort — to node ``"0"``.  This
    keeps a floating battery + load circuit solvable without forcing the
    user to drop a GND symbol.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if rb in ("0", "GND"):
                ra, rb = rb, ra
            parent[rb] = ra

    pins: list[str] = []
    for c in graph.get("components", []):
        for i, _ in enumerate(c.get("pins", [])):
            label = f"{c['id']}.{i}"
            parent[label] = label
            pins.append(label)
            if c.get("pins")[i]:
                node = c["pins"][i]
                parent.setdefault(node, node)
                union(label, node)

    for w in graph.get("wires", []):
        parent.setdefault(w["a"], w["a"])
        parent.setdefault(w["b"], w["b"])
        union(w["a"], w["b"])

    # --- BUS / GRID / PCS components always anchor their reference pins
    #     to node 0.  These are the explicit "system reference" elements;
    #     several may coexist (all share node 0).
    for c in graph.get("components", []):
        kind = c["kind"]
        if kind == "BUS" and len(c.get("pins", [])) >= 2:
            anchors = [f"{c['id']}.1"]
        elif kind == "GRID" and len(c.get("pins", [])) >= 2:
            anchors = [f"{c['id']}.1"]   # neutral
        elif kind == "PCS" and len(c.get("pins", [])) >= 4:
            anchors = [f"{c['id']}.1",   # AC-
                       f"{c['id']}.3"]   # DC-
        else:
            continue
        for a in anchors:
            parent.setdefault("0", "0")
            parent.setdefault(a, a)
            union(a, "0")

    # --- Auto-ground when no explicit GND or anchor component is present ---
    has_anchor = any(c["kind"] in ("GND", "BUS", "GRID", "PCS")
                     for c in graph.get("components", []))
    if not has_anchor:
        # Backward-compatibility fallback for legacy load components.
        priority = (("PCONST", "ICONST", "IPATTERN", "I"), ("BATTERY",))
        anchor_pin: str | None = None
        for kind_set in priority:
            for c in graph.get("components", []):
                if c["kind"] in kind_set and len(c.get("pins", [])) >= 2:
                    anchor_pin = f"{c['id']}.1"
                    break
            if anchor_pin is not None:
                break
        if anchor_pin is not None:
            parent.setdefault("0", "0")
            parent.setdefault(anchor_pin, anchor_pin)
            union(anchor_pin, "0")

    nl = Netlist()
    for c in graph.get("components", []):
        if c["kind"] in ("PROBE", "JUNCTION"):
            continue  # passive node markers
        nodes = [find(f"{c['id']}.{i}") for i in range(len(c.get("pins", [])))]
        model_obj = c.get("model")
        if (model_obj is None and c["kind"] == "BATTERY"
                and c.get("params", {}).get("model")):
            try:
                from batsim.plugins.registry import make_battery
                p = dict(c["params"])
                model_name = p.pop("model", None)
                cell = p.pop("cell", None)
                model_obj = make_battery(model_name=model_name, cell=cell, **p)
            except Exception:
                model_obj = None
        nl.add(Element(kind=c["kind"], name=c["id"], nodes=nodes,
                       params=c.get("params", {}), model=model_obj))
    return nl


def probe_map(graph: dict) -> dict:
    """Return mapping for measurement aliases.

    {
      "voltages": {probe_id: node_label, ...},   # from PROBE components
      "currents": {iprobe_id: iprobe_id, ...},   # IPROBE shows up as a vsource
    }
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if rb in ("0", "GND"):
                ra, rb = rb, ra
            parent[rb] = ra

    for c in graph.get("components", []):
        for i, _ in enumerate(c.get("pins", [])):
            label = f"{c['id']}.{i}"
            parent[label] = label
            if c.get("pins")[i]:
                node = c["pins"][i]
                parent.setdefault(node, node)
                union(label, node)
    for w in graph.get("wires", []):
        parent.setdefault(w["a"], w["a"])
        parent.setdefault(w["b"], w["b"])
        union(w["a"], w["b"])

    # BUS / GRID / PCS components always anchor reference pins to node 0.
    for c in graph.get("components", []):
        kind = c["kind"]
        if kind == "BUS" and len(c.get("pins", [])) >= 2:
            anchors = [f"{c['id']}.1"]
        elif kind == "GRID" and len(c.get("pins", [])) >= 2:
            anchors = [f"{c['id']}.1"]
        elif kind == "PCS" and len(c.get("pins", [])) >= 4:
            anchors = [f"{c['id']}.1", f"{c['id']}.3"]
        else:
            continue
        for a in anchors:
            parent.setdefault("0", "0")
            parent.setdefault(a, a)
            union(a, "0")

    has_anchor = any(c["kind"] in ("GND", "BUS", "GRID", "PCS")
                     for c in graph.get("components", []))
    if not has_anchor:
        priority = (("PCONST", "ICONST", "IPATTERN", "I"), ("BATTERY",))
        anchor_pin: str | None = None
        for kind_set in priority:
            for c in graph.get("components", []):
                if c["kind"] in kind_set and len(c.get("pins", [])) >= 2:
                    anchor_pin = f"{c['id']}.1"
                    break
            if anchor_pin is not None:
                break
        if anchor_pin is not None:
            parent.setdefault("0", "0")
            parent.setdefault(anchor_pin, anchor_pin)
            union(anchor_pin, "0")

    voltages: dict[str, str] = {}
    currents: dict[str, str] = {}
    for c in graph.get("components", []):
        if c["kind"] == "PROBE":
            voltages[c["id"]] = find(f"{c['id']}.0")
        elif c["kind"] == "IPROBE":
            currents[c["id"]] = c["id"]
    return {"voltages": voltages, "currents": currents}
