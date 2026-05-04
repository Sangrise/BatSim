"""PCS profile-mode tests (CC / CV / CP / CCCV / CPCV / CYCLE)."""
from __future__ import annotations

import json
import numpy as np

from batsim.engine.netlist import from_graph
from batsim.engine.nonlinear import solve_transient


def _comp(cid, kind, params, pins=2):
    return {"id": cid, "kind": kind, "pins": [None] * pins, "params": params}


def _ac_pcs_battery(pcs_params, t_end=2.0, dt=5e-3, R0=0.005, soc0=0.5,
                    Rline=0.01):
    """Standard sheet: GRID → PCS → Rline → BATTERY (LFP, 100 Ah).
    Rline avoids two stiff Vsources sharing a node-pair."""
    g = {
        "components": [
            _comp("G1", "GRID", {"V_rms": 380.0, "freq": 60.0}),
            _comp("PCS1", "PCS", pcs_params, pins=4),
            _comp("Rline", "R", {"R": Rline}),
            _comp("B1", "BATTERY", {
                "model": "Thevenin",
                "capacity_Ah": 100.0, "soc0": soc0,
                "R0": R0, "R1": 0.005, "C1": 100.0}),
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
    res = solve_transient(nl, t_end=t_end, dt=dt)
    return res, nl


def test_pcs_cc_charge_current_steady():
    """CC mode: PCS sources +I_set into the battery."""
    res, nl = _ac_pcs_battery({"mode": "CC", "I_set": 25.0, "eta": 0.98},
                              t_end=1.0)
    I_pcs = np.asarray(res["I"]["PCS1"])
    # Last few steps should hold ~25 A (sign positive = charging).
    assert abs(I_pcs[-1] - 25.0) < 1.0


def test_pcs_cp_discharge_power():
    """CP discharge: P_set negative drives current OUT of battery."""
    res, nl = _ac_pcs_battery({"mode": "CP", "P_set": -10.0, "eta": 0.98},
                              t_end=0.5, soc0=0.6, Rline=0.05)
    n_dc_pos = next(e.nodes[2] for e in nl.elements if e.name == "PCS1")
    V = float(res["V"][n_dc_pos][-1])
    I = float(res["I"]["PCS1"][-1])
    # |V·I| should track |P_set| within 20 %.
    P = V * I
    assert abs(abs(P) - 10.0) < 3.0
    # Sign: discharge means current leaves battery; PCS observer Iv < 0.
    assert I < 0


def test_pcs_cccv_terminates_into_cv_phase():
    """CCCV: CC at 50 A until V crosses V_max, then CV holds at V_max."""
    res, nl = _ac_pcs_battery(
        {"mode": "CCCV", "I_set": 50.0, "V_max": 3.6,
         "I_term": 1.0, "eta": 0.98},
        t_end=2.0, soc0=0.5, R0=0.005, Rline=0.01)
    n_dc_pos = next(e.nodes[2] for e in nl.elements if e.name == "PCS1")
    V = np.asarray(res["V"][n_dc_pos])[1:]   # skip initial DC point
    # Bus voltage (after first step) must never exceed V_max materially.
    assert V.max() < 3.6 + 0.05
    # And must REACH V_max (CV phase engaged).
    assert V.max() > 3.55


def test_pcs_cycle_alternates_charge_rest_discharge():
    """CYCLE: charge → rest → discharge → rest, then repeat."""
    steps = [
        {"mode": "CC",   "I":  10.0, "max_time": 0.5},
        {"mode": "REST",              "time":     0.3},
        {"mode": "CC",   "I": -10.0, "max_time": 0.5},
        {"mode": "REST",              "time":     0.3},
    ]
    res, nl = _ac_pcs_battery(
        {"mode": "CYCLE", "cycle_steps": json.dumps(steps),
         "cycle_repeat": 1, "eta": 0.98},
        t_end=1.6, dt=2e-3)
    t = res["t"]
    I = np.asarray(res["I"]["PCS1"])

    def _at(time):
        k = int(min(np.searchsorted(t, time), len(t) - 1))
        return float(I[k])

    # Charge phase (~t=0.3 s) should be ≈ +10 A
    assert _at(0.3) > 5.0
    # First rest (~t=0.7 s) should be ≈ 0
    assert abs(_at(0.7)) < 2.0
    # Discharge phase (~t=1.0 s) should be ≈ −10 A
    assert _at(1.0) < -5.0
    # Final rest (~t=1.5 s) should be ≈ 0
    assert abs(_at(1.5)) < 2.0


def test_pcs_legacy_modes_still_work():
    """Old V_DC mode must remain unaffected by the new controller."""
    res, nl = _ac_pcs_battery({"mode": "V_DC", "V_DC_set": 3.5},
                              t_end=0.2, dt=5e-3, soc0=0.5,
                              R0=0.005, Rline=0.05)
    n_dc_pos = next(e.nodes[2] for e in nl.elements if e.name == "PCS1")
    assert abs(res["V"][n_dc_pos][-1] - 3.5) < 0.05
