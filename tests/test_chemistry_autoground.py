"""Chemistry-specific OCV + auto-grounding regression tests."""
from __future__ import annotations

from batsim.models.thevenin import TheveninModel
from batsim.models.base import OCV_TABLES
from batsim.engine.netlist import from_graph
from batsim.engine.nonlinear import solve_transient as simulate


def test_chemistry_lfp_plateau_vs_ncm():
    lfp = TheveninModel(chemistry="LFP", soc0=0.5)
    ncm = TheveninModel(chemistry="NCM", soc0=0.5)
    v_lfp = lfp.terminal_voltage(0.0, None)
    v_ncm = ncm.terminal_voltage(0.0, None)
    # LFP plateau ≈ 3.30 V at mid-SOC, NCM ramp ≈ 3.7-3.8 V → clear gap
    assert 3.20 <= v_lfp <= 3.40
    assert v_ncm > v_lfp + 0.25


def test_all_chemistries_present():
    for k in ("NCM", "LFP", "LCO", "NCA", "LTO", "Generic"):
        assert k in OCV_TABLES


def test_auto_ground_battery_pconst_no_gnd():
    """A battery + constant-power load with no explicit GND should still
    produce a solvable network (auto-grounding)."""
    graph = {
        "components": [
            {"id": "B1", "kind": "BATTERY", "pins": [None, None],
             "params": {"chemistry": "LFP", "model": "Thevenin",
                        "capacity_Ah": 10.0, "soc0": 0.8,
                        "R0": 0.01, "R1": 0.005, "C1": 1000.0}},
            {"id": "P1", "kind": "PCONST", "pins": [None, None],
             "params": {"P": 5.0}},
        ],
        "wires": [
            {"a": "B1.1", "b": "P1.1"},
            {"a": "B1.0", "b": "P1.0"},
        ],
        "probes": [],
    }
    nl = from_graph(graph)
    assert "0" in nl.nodes  # GND was auto-created
    res = simulate(nl, t_end=1.0, dt=0.1)
    assert len(res["t"]) > 5
    # Terminal voltage on the battery should sit near LFP plateau
    # (capacity is large vs 1 s discharge)
    bus_voltages = [v[-1] for n, v in res["V"].items() if n != "0"]
    assert any(3.0 < v < 3.6 for v in bus_voltages)
