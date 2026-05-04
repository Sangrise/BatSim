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
    # The probe node and the IPROBE.1 node must be the same merged label.
    # PROBE is now differential — legacy 1-pin probes resolve as
    # (positive_node, "0") so old tests need to look at the +ve side.
    nl = from_graph(g)
    ip_elem = next(e for e in nl.elements if e.name == "IP1")
    info = pm["voltages"]["P1"]
    npos = info[0] if isinstance(info, tuple) else info
    assert npos == ip_elem.nodes[1]


def test_probe_map_differential_two_pin():
    """A 2-pin PROBE with both leads wired returns a (pos, neg) tuple."""
    g = {
        "components": [
            {"id": "V1", "kind": "V", "params": {"V": 7.0},
             "pins": [None, None]},
            {"id": "R1", "kind": "R", "params": {"R": 1000.0},
             "pins": [None, None]},
            {"id": "G1", "kind": "GND", "params": {}, "pins": ["0"]},
            {"id": "P1", "kind": "PROBE", "params": {},
             "pins": [None, None]},
        ],
        "wires": [
            {"a": "V1.0", "b": "R1.0"},
            {"a": "R1.1", "b": "G1.0"},
            {"a": "V1.1", "b": "G1.0"},
            {"a": "P1.0", "b": "V1.0"},
            {"a": "P1.1", "b": "R1.1"},
        ],
    }
    pm = probe_map(g)
    info = pm["voltages"]["P1"]
    assert isinstance(info, tuple) and len(info) == 2
    npos, nneg = info
    assert nneg in ("0", "G1.0", "R1.1")  # all merged with ground
    assert npos != nneg


def test_probe_map_two_pin_floating_neg_treated_as_ground():
    """Pin1 left unwired → measured against ground (single-ended)."""
    g = {
        "components": [
            {"id": "V1", "kind": "V", "params": {"V": 3.0},
             "pins": [None, None]},
            {"id": "R1", "kind": "R", "params": {"R": 1000.0},
             "pins": [None, None]},
            {"id": "G1", "kind": "GND", "params": {}, "pins": ["0"]},
            {"id": "P1", "kind": "PROBE", "params": {},
             "pins": [None, None]},
        ],
        "wires": [
            {"a": "V1.0", "b": "R1.0"},
            {"a": "R1.1", "b": "G1.0"},
            {"a": "V1.1", "b": "G1.0"},
            {"a": "P1.0", "b": "V1.0"},
        ],
    }
    pm = probe_map(g)
    info = pm["voltages"]["P1"]
    assert isinstance(info, tuple)
    assert info[1] == "0"


def test_iprobe_dropped_in_empty_space_is_refused():
    """IPROBE only makes sense on a wire — empty drop returns None."""
    import pytest
    pytest.importorskip("PyQt6")
    import sys
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication
    from batsim.ui.canvas.scene import SchematicScene
    app = QApplication.instance() or QApplication(sys.argv)
    sc = SchematicScene()
    sc.add_component("R", QPointF(-100, 0))
    ip = sc.add_component("IPROBE", QPointF(500, 500))
    assert ip is None
    assert not any(c.kind == "IPROBE" for c in sc._components)


def test_iprobe_dropped_on_wire_auto_splits():
    """Drop an IPROBE on an existing wire via add_component → wire is
    removed and replaced by two new wires sandwiching the probe."""
    import pytest
    pytest.importorskip("PyQt6")
    import sys
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication
    from batsim.ui.canvas.scene import SchematicScene

    app = QApplication.instance() or QApplication(sys.argv)
    sc = SchematicScene()
    r1 = sc.add_component("R", QPointF(-100, 0))
    r2 = sc.add_component("R", QPointF(100, 0))
    sc.begin_wire(r1, 1)
    assert sc.try_finish_wire_at(r2.pin_scene_pos(0))
    assert len(sc._wires) == 1
    # Drop IPROBE on the wire midpoint
    ip = sc.add_component("IPROBE", QPointF(0, 0))
    assert ip is not None and ip.kind == "IPROBE"
    assert len(sc._wires) == 2
    # Both new wires should reference IPROBE on one side and an R on the other
    sides = []
    for w in sc._wires:
        if w.a_comp is ip or w.b_comp is ip:
            other = w.b_comp if w.a_comp is ip else w.a_comp
            sides.append(other)
    assert {r1, r2} == set(sides)


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
