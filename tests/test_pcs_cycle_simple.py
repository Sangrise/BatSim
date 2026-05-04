"""CYCLE_SIMPLE PCS controller regression test."""
from __future__ import annotations

import numpy as np

from batsim.engine.netlist import from_graph
from batsim.engine.nonlinear import solve_transient


def _comp(cid, kind, params, pins=2):
    return {"id": cid, "kind": kind, "pins": [None] * pins, "params": params}


def test_cycle_simple_runs_charge_rest_discharge_rest():
    """One full cycle: charge (negative I_DC at PCS) → rest → discharge (positive)."""
    g = {
        "components": [
            _comp("G1", "GRID", {"V_rms": 380.0, "freq": 60.0}),
            _comp("PCS1", "PCS", {
                "mode": "CYCLE_SIMPLE",
                "cyc_I_chg": 20.0,
                "cyc_I_dis": 20.0,
                "cyc_V_max": 3.65,
                "cyc_V_min": 3.10,
                "cyc_t_rest": 0.05,
                "cyc_count": 1,
                "eta": 0.98,
            }, pins=4),
            _comp("Rline", "R", {"R": 0.01}),
            _comp("B1", "BATTERY", {
                "model": "Thevenin",
                "capacity_Ah": 2.0, "soc0": 0.5,
                "R0": 0.01, "R1": 0.005, "C1": 50.0,
            }),
        ],
        "wires": [
            {"a": "G1.0", "b": "PCS1.0"},
            {"a": "G1.1", "b": "PCS1.1"},
            {"a": "PCS1.2", "b": "Rline.0"},
            {"a": "Rline.1", "b": "B1.0"},
            {"a": "PCS1.3", "b": "B1.1"},
        ],
        "probes": [],
    }
    nl = from_graph(g)
    res = solve_transient(nl, t_end=2.0, dt=2e-3)
    I = np.asarray(res["I"]["PCS1"])
    # Charge phase: PCS sources current OUT of DC+ → vs_current is negative
    assert I.min() < -10.0, f"expected charge current < -10A, got {I.min()}"
    # Discharge phase: positive
    assert I.max() > 5.0, f"expected discharge > 5A, got {I.max()}"
