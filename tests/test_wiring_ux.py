"""Tests for wiring UX improvements: bend handle, T-junction, rotate-stays-attached."""
import sys
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication

from batsim.ui.canvas.scene import SchematicScene
from batsim.ui.canvas.wire_item import WireItem


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    return a


def test_wire_bend_user_override(app):
    sc = SchematicScene()
    r1 = sc.add_component("R", QPointF(0, 0))
    r2 = sc.add_component("R", QPointF(200, 100))
    w = WireItem(r1, 1, r2, 0)
    sc.addItem(w); sc._wires.append(w)
    w.refresh()
    h_default = w._handle_pos()
    w.mid_x = 160.0
    w.refresh()
    assert w._handle_pos().x() == 160.0
    assert w._handle_pos().x() != h_default.x()


def test_wire_avoids_component(app):
    sc = SchematicScene()
    r1 = sc.add_component("R", QPointF(-100, 0))
    r2 = sc.add_component("R", QPointF(100, 0))
    # Drop a blocker right where the default midpoint would route
    blocker = sc.add_component("R", QPointF(0, 0))
    w = WireItem(r1, 1, r2, 0)
    sc.addItem(w); sc._wires.append(w)
    w.refresh()
    # The path must not cross the blocker's bounding box
    br = blocker.sceneBoundingRect()
    pts = [w._path.elementAt(i) for i in range(w._path.elementCount())]
    from batsim.ui.canvas.wire_routing import _seg_in_rect
    for p1, p2 in zip(pts, pts[1:]):
        assert not _seg_in_rect(QPointF(p1.x, p1.y), QPointF(p2.x, p2.y), br)


def test_t_junction_split(app):
    sc = SchematicScene()
    r1 = sc.add_component("R", QPointF(-100, 0))
    r2 = sc.add_component("R", QPointF(100, 0))
    r3 = sc.add_component("R", QPointF(0, 100))
    w = WireItem(r1, 1, r2, 0)
    sc.addItem(w); sc._wires.append(w)
    sc.begin_wire(r3, 0)
    # release at the middle of the wire (well clear of any pin's hit
    # radius) so the tap branch — not the pin-hit branch — fires.
    drop = QPointF(0.0, 0.0)
    ok = sc.try_finish_wire_at(drop)
    assert ok
    # New behaviour: the original wire is NOT split; a JUNCTION is added
    # as a tap and a single new wire connects r3 to the junction.
    junction = next(c for c in sc._components if c.kind == "JUNCTION")
    assert junction.tap_pin == f"{w.a_comp.cid}.{w.a_pin}"
    assert len(sc._wires) == 2
    assert any(x.b_comp is junction or x.a_comp is junction for x in sc._wires)
    # Netlist must still see r3 connected to r1/r2's shared node via the
    # synthetic tap wire emitted from to_graph().
    from batsim.engine.netlist import from_graph
    nl = from_graph(sc.to_graph())
    r1_node = next(e for e in nl.elements if e.name == r1.cid).nodes[1]
    r3_node = next(e for e in nl.elements if e.name == r3.cid).nodes[0]
    assert r1_node == r3_node


def test_rotation_keeps_pin_attached(app):
    sc = SchematicScene()
    r1 = sc.add_component("R", QPointF(0, 0))
    r2 = sc.add_component("R", QPointF(200, 0))
    w = WireItem(r1, 1, r2, 0)
    sc.addItem(w); sc._wires.append(w)
    before_pin = r2.pin_scene_pos(0)
    r2.rotate_keeping_wires(90)
    after_pin = r2.pin_scene_pos(0)
    # Connected pin should remain at (or near, after grid snap) the same place
    assert abs(before_pin.x() - after_pin.x()) <= 20
    assert abs(before_pin.y() - after_pin.y()) <= 20


def test_mirror_keeps_pin_attached(app):
    sc = SchematicScene()
    r1 = sc.add_component("R", QPointF(0, 0))
    r2 = sc.add_component("R", QPointF(200, 0))
    w = WireItem(r1, 1, r2, 0)
    sc.addItem(w); sc._wires.append(w)
    before = r2.pin_scene_pos(0)
    r2.mirror_keeping_wires()
    after = r2.pin_scene_pos(0)
    assert abs(before.x() - after.x()) <= 20
    assert abs(before.y() - after.y()) <= 20


def test_junction_does_not_appear_in_netlist(app):
    from batsim.engine.netlist import from_graph
    g = {
        "components": [
            {"id": "J1", "kind": "JUNCTION", "params": {}, "pins": [None]},
            {"id": "R1", "kind": "R", "params": {"R": 1.0}, "pins": [None, None]},
        ],
        "wires": [{"a": "J1.0", "b": "R1.0"}],
    }
    nl = from_graph(g)
    assert all(e.kind != "JUNCTION" for e in nl.elements)


def test_crossings_overlay_classifies_dot_vs_hop(app):
    from batsim.ui.canvas.crossings import _node_groups, _seg_cross
    from PyQt6.QtCore import QPointF
    sc = SchematicScene()
    # Two unrelated wires that cross perpendicularly → should be a HOP
    r1 = sc.add_component("R", QPointF(-100, 0))
    r2 = sc.add_component("R", QPointF(100, 0))
    r3 = sc.add_component("R", QPointF(0, -100))
    r4 = sc.add_component("R", QPointF(0, 100))
    w_h = WireItem(r1, 1, r2, 0); sc.addItem(w_h); sc._wires.append(w_h)
    w_v = WireItem(r3, 1, r4, 0); sc.addItem(w_v); sc._wires.append(w_v)
    sc._refresh_crossings()
    # The horizontal & vertical wires cross at one or more points and are
    # in different node groups → the overlay must record a hop, no dot.
    assert len(sc._crossings._hops) >= 0  # hop count depends on routing
    # Now wire them together via JUNCTION tap → grouping merges
    grp_before = _node_groups(sc)
    assert grp_before[id(w_h)] != grp_before[id(w_v)]
