"""GRID (AC) + PCS (AC↔DC) + TR (AC) regression tests."""
from __future__ import annotations

import math
import numpy as np

from batsim.engine.netlist import from_graph
from batsim.engine.nonlinear import solve_transient
from batsim.engine.sources import make_sine_waveform


def _comp(cid, kind, params, pins=2):
    return {"id": cid, "kind": kind, "pins": [None] * pins, "params": params}


def test_sine_waveform_amplitude_freq():
    wf = make_sine_waveform(220.0, 60.0)
    peak = 220.0 * math.sqrt(2.0)
    # Quarter-period after t=0 should hit ~+peak
    assert abs(wf(1.0 / (4 * 60.0)) - peak) < 1e-3
    # Zero-crossings at multiples of half period
    assert abs(wf(0.0)) < 1e-9
    assert abs(wf(1.0 / (2 * 60.0))) < 1e-3


def test_grid_produces_sine():
    g = {
        "components": [
            _comp("G1", "GRID", {"V_rms": 230.0, "freq": 50.0,
                                 "phase_deg": 0.0}),
            _comp("R1", "R", {"R": 10.0}),
        ],
        "wires": [{"a": "G1.0", "b": "R1.0"}, {"a": "R1.1", "b": "G1.1"}],
        "probes": [],
    }
    nl = from_graph(g)
    # 2 cycles at 50 Hz with fine time step
    res = solve_transient(nl, t_end=0.04, dt=2e-4)
    g_node = next(e.nodes[0] for e in nl.elements if e.name == "G1")
    v_arr = np.asarray(res["V"][g_node])
    peak = 230.0 * math.sqrt(2.0)
    assert abs(v_arr.max() - peak) < 0.5
    assert abs(v_arr.min() + peak) < 0.5
    # RMS over the simulation window should match V_rms
    rms = float(np.sqrt(np.mean(v_arr ** 2)))
    assert abs(rms - 230.0) < 5.0


def test_pcs_v_dc_holds_bus():
    """PCS in V_DC mode should keep the DC bus at V_DC_set."""
    g = {
        "components": [
            _comp("G1", "GRID", {"V_rms": 220.0, "freq": 60.0}),
            _comp("PCS1", "PCS", {"mode": "V_DC", "V_DC_set": 400.0,
                                  "eta": 0.95}, pins=4),
            _comp("Rdc", "R", {"R": 100.0}),  # DC load 4 A
        ],
        "wires": [
            {"a": "G1.0", "b": "PCS1.0"},
            {"a": "G1.1", "b": "PCS1.1"},
            {"a": "PCS1.2", "b": "Rdc.0"},
            {"a": "Rdc.1", "b": "PCS1.3"},
        ],
        "probes": [],
    }
    nl = from_graph(g)
    res = solve_transient(nl, t_end=0.05, dt=5e-4)
    pcs_dc_pos = next(e.nodes[2] for e in nl.elements if e.name == "PCS1")
    v_dc = np.asarray(res["V"][pcs_dc_pos])
    # After ~5 ms the DC bus must stabilise at 400 V (within 1 %).
    assert abs(v_dc[-1] - 400.0) < 4.0


def test_full_ac_chain_grid_tr_pcs_battery():
    """Full chain: GRID(380V) → TR(2:1) → PCS(V_DC=180) → BATTERY (LFP).
    Battery should sit near OCV − I·R0 with the DC bus held by PCS."""
    g = {
        "components": [
            _comp("G1", "GRID", {"V_rms": 380.0, "freq": 60.0}),
            _comp("T1", "TR", {"n": 2.0}, pins=4),
            _comp("PCS1", "PCS", {"mode": "V_DC", "V_DC_set": 180.0,
                                  "eta": 0.97}, pins=4),
            _comp("B1", "BATTERY", {"model": "Thevenin",
                                     "capacity_Ah": 100.0, "soc0": 0.5,
                                     "R0": 0.005, "R1": 0.01, "C1": 100.0}),
            _comp("Rline", "R", {"R": 1.0}),  # 1Ω limiter so I ~ a few A
        ],
        "wires": [
            {"a": "G1.0",  "b": "T1.0"},
            {"a": "G1.1",  "b": "T1.1"},
            {"a": "T1.2",  "b": "PCS1.0"},
            {"a": "T1.3",  "b": "PCS1.1"},
            {"a": "PCS1.2", "b": "Rline.0"},
            {"a": "Rline.1", "b": "B1.0"},
            {"a": "PCS1.3", "b": "B1.1"},
        ],
        "probes": [],
    }
    nl = from_graph(g)
    res = solve_transient(nl, t_end=0.05, dt=5e-4)
    # PCS DC+ must be held at 180 V regardless of battery OCV.
    pcs_dc_pos = next(e.nodes[2] for e in nl.elements if e.name == "PCS1")
    assert abs(res["V"][pcs_dc_pos][-1] - 180.0) < 2.0
    # Battery sits near its OCV; current flows through Rline from bus to batt.
    b1_pos = next(e.nodes[0] for e in nl.elements if e.name == "B1")
    v_bat = float(res["V"][b1_pos][-1])
    assert 2.0 < v_bat < 4.5         # LFP OCV plateau range
    # Charging current ≈ (180 − OCV) / Rline must be positive (into battery).
    i_line = (180.0 - v_bat) / 1.0
    assert i_line > 100.0


def test_pcs_anchors_dc_minus_to_ground():
    g = {
        "components": [
            _comp("G1", "GRID", {"V_rms": 100.0, "freq": 60.0}),
            _comp("PCS1", "PCS", {"mode": "V_DC", "V_DC_set": 48.0}, pins=4),
            _comp("R1", "R", {"R": 24.0}),
        ],
        "wires": [
            {"a": "G1.0", "b": "PCS1.0"},
            {"a": "G1.1", "b": "PCS1.1"},
            {"a": "PCS1.2", "b": "R1.0"},
            {"a": "R1.1", "b": "PCS1.3"},
        ],
        "probes": [],
    }
    nl = from_graph(g)
    pcs_dc_neg = next(e.nodes[3] for e in nl.elements if e.name == "PCS1")
    assert pcs_dc_neg == "0"
