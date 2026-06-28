"""BUS (Grid/Load) and TR (transformer) component regression tests."""
from __future__ import annotations

from batsim_core.engine.netlist import from_graph
from batsim_core.engine.nonlinear import solve_transient


def _comp(cid, kind, params, pins=2):
    return {"id": cid, "kind": kind, "pins": [None] * pins,
            "params": params}


def test_bus_grid_drives_battery():
    """Grid bus at 50 V through a small cable resistance should pin the
    battery side near 50 V (battery R0 limits inrush)."""
    g = {
        "components": [
            _comp("G1", "BUS", {"mode": "Grid", "V": 50.0}),
            _comp("Rc", "R", {"R": 0.5}),  # cable
            _comp("B1", "BATTERY", {"model": "Thevenin",
                                     "capacity_Ah": 100.0, "soc0": 0.2,
                                     "R0": 0.05, "R1": 0.01, "C1": 100.0}),
        ],
        "wires": [
            {"a": "G1.0", "b": "Rc.0"},
            {"a": "Rc.1", "b": "B1.0"},
            {"a": "G1.1", "b": "B1.1"},
        ],
        "probes": [],
    }
    nl = from_graph(g)
    res = solve_transient(nl, t_end=0.5, dt=0.05)
    # The grid pin0 must sit at exactly 50 V (it is the stiff Vsource)
    grid_pin = None
    for e in nl.elements:
        if e.name == "G1":
            grid_pin = e.nodes[0]
    assert abs(res["V"][grid_pin][-1] - 50.0) < 1e-6


def test_bus_pload_consumes_power():
    """1 kW PLoad on a 100 V BUS should draw ~10 A through the bus."""
    g = {
        "components": [
            _comp("G1", "BUS", {"mode": "Grid", "V": 100.0}),
            _comp("L1", "BUS", {"mode": "PLoad", "P": 1000.0}),
        ],
        "wires": [{"a": "G1.0", "b": "L1.0"}, {"a": "G1.1", "b": "L1.1"}],
        "probes": [],
    }
    nl = from_graph(g)
    res = solve_transient(nl, t_end=0.1, dt=0.01)
    # Grid bus current ≈ -10 A (delivers 10 A).  Convention: vs current is
    # positive when flowing pin0 -> ground -> pin1 inside the source.
    I_g = res["I"]["G1"][-1]
    assert abs(abs(I_g) - 10.0) < 0.5


def test_bus_iload_constant_current():
    g = {
        "components": [
            _comp("G1", "BUS", {"mode": "Grid", "V": 12.0}),
            _comp("L1", "BUS", {"mode": "ILoad", "I": 2.5}),
            _comp("R1", "R", {"R": 0.1}),
        ],
        "wires": [
            {"a": "G1.0", "b": "R1.0"},
            {"a": "R1.1", "b": "L1.0"},
            {"a": "L1.1", "b": "G1.1"},
        ],
        "probes": [],
    }
    nl = from_graph(g)
    res = solve_transient(nl, t_end=0.05, dt=0.005)
    # Grid current magnitude must equal the imposed 2.5 A
    assert abs(abs(res["I"]["G1"][-1]) - 2.5) < 0.05


def test_tr_voltage_step_down():
    """A 100 V Grid → 10:1 transformer → load. Secondary needs its own
    ground reference; we use an explicit GND on T1.3 (centre-tap)."""
    g = {
        "components": [
            _comp("G1", "BUS", {"mode": "Grid", "V": 100.0}),
            _comp("T1", "TR", {"n": 10.0}, pins=4),
            _comp("R1", "R", {"R": 1.0}),
            {"id": "Gs", "kind": "GND", "params": {}, "pins": ["0"]},
        ],
        "wires": [
            {"a": "G1.0", "b": "T1.0"},
            {"a": "G1.1", "b": "T1.1"},
            {"a": "T1.2", "b": "R1.0"},
            {"a": "T1.3", "b": "R1.1"},
            {"a": "T1.3", "b": "Gs.0"},
        ],
        "probes": [],
    }
    nl = from_graph(g)
    res = solve_transient(nl, t_end=0.05, dt=0.005)
    r_nodes = next(e.nodes for e in nl.elements if e.name == "R1")
    v0 = res["V"].get(r_nodes[0], [0])[-1] if r_nodes[0] != "0" else 0.0
    v1 = res["V"].get(r_nodes[1], [0])[-1] if r_nodes[1] != "0" else 0.0
    assert abs(abs(v0 - v1) - 10.0) < 0.3


def test_bus_anchor_priority_over_battery():
    """When both BUS and BATTERY are present, BUS must be the GND anchor."""
    g = {
        "components": [
            _comp("B1", "BATTERY", {"model": "Thevenin",
                                     "capacity_Ah": 10.0, "soc0": 0.5,
                                     "R0": 0.01, "R1": 0.01, "C1": 100.0}),
            _comp("G1", "BUS", {"mode": "Grid", "V": 12.0}),
        ],
        "wires": [{"a": "B1.0", "b": "G1.0"}, {"a": "B1.1", "b": "G1.1"}],
        "probes": [],
    }
    nl = from_graph(g)
    # G1.1 must be merged into "0"
    g1_neg = None
    for e in nl.elements:
        if e.name == "G1":
            g1_neg = e.nodes[1]
    assert g1_neg == "0"

