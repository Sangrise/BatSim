"""Tests for PROBE / IPROBE measurement points."""
from batsim.engine.netlist import from_graph, probe_map
from batsim.engine.mna import MNASystem
import numpy as np


def _graph_v_r_iprobe_probe():
    """V(5V) -- IPROBE -- R(1k) -- GND, with PROBE on the V/IPROBE node."""
    return {
        "components": [
            {"id": "V1", "kind": "V", "params": {"V": 5.0},
             "pins": [None, None]},
            {"id": "IP1", "kind": "IPROBE", "params": {},
             "pins": [None, None]},
            {"id": "R1", "kind": "R", "params": {"R": 1000.0},
             "pins": [None, None]},
            {"id": "G1", "kind": "GND", "params": {},
             "pins": ["0"]},
            {"id": "P1", "kind": "PROBE", "params": {},
             "pins": [None]},
        ],
        "wires": [
            {"a": "V1.0", "b": "IP1.0"},
            {"a": "IP1.1", "b": "R1.0"},
            {"a": "R1.1", "b": "G1.0"},
            {"a": "V1.1", "b": "G1.0"},
            {"a": "P1.0", "b": "IP1.1"},
        ],
    }


def test_probe_does_not_appear_in_netlist():
    g = _graph_v_r_iprobe_probe()
    nl = from_graph(g)
    kinds = [e.kind for e in nl.elements]
    assert "PROBE" not in kinds
    assert "IPROBE" in kinds  # IPROBE stays


def test_probe_map_resolves_node_and_current():
    g = _graph_v_r_iprobe_probe()
    pm = probe_map(g)
    assert "P1" in pm["voltages"]
    assert "IP1" in pm["currents"]
    # The probe node and the IPROBE.1 node must be the same merged label
    nl = from_graph(g)
    ip_elem = next(e for e in nl.elements if e.name == "IP1")
    assert pm["voltages"]["P1"] == ip_elem.nodes[1]


def test_iprobe_measures_through_current():
    g = _graph_v_r_iprobe_probe()
    nl = from_graph(g)
    sys = MNASystem(nl)
    A, b = sys.build(x_prev=None, dt=None)
    x = np.linalg.solve(A, b)
    # 5V across 1k -> 5 mA through IPROBE
    i = sys.vs_current(x, "IP1")
    assert abs(abs(i) - 0.005) < 1e-9


def test_waveform_view_aliases_probes():
    import sys
    import pytest
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from batsim.ui.waveform_view import WaveformView
    w = WaveformView()
    fake_result = {
        "t": [0.0, 1.0, 2.0],
        "V": {"n1": [5.0, 5.0, 5.0]},
        "I": {"V1": [-0.005, -0.005, -0.005],
              "IP1": [0.005, 0.005, 0.005]},
    }
    aliases = {"voltages": {"P1": "n1"}, "currents": {"IP1": "IP1"}}
    w.show_results(fake_result, aliases=aliases)
    assert "V(P1)" in w._available
    assert "I(IP1)" in w._available
    # First simulation auto-splits into V panel + I panel
    assert len(w._panels) == 2
    v_axis = w._panels[0].axis_state()
    i_axis = w._panels[1].axis_state()
    assert v_axis.get("V(P1)") == 1  # AXIS_LEFT
    assert i_axis.get("I(IP1)") == 1
    # User can still add an extra panel for ad-hoc views
    panel3 = w.add_panel()
    assert len(w._panels) == 3
    panel3.set_available_signals(w._available,
                                 default_axis={"V(n1)": 1},
                                 keep_existing=False)
    assert panel3.axis_state().get("V(n1)") == 1
    w.close()
