"""Schematic editing scene with grid snap and component/wire management."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QPen, QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsPathItem

from batsim_core.components.catalog import CATALOG, pin_offsets
from .component_item import ComponentItem
from .wire_item import WireItem
from .wire_routing import orthogonal_route
from .crossings import CrossingsOverlay


GRID = 20
PIN_HIT_RADIUS = 18  # scene-units tolerance when matching cursor to a pin


class SchematicScene(QGraphicsScene):
    selectionStateChanged = pyqtSignal(object)  # emits ComponentItem or None
    graphChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-2000, -2000, 4000, 4000)
        self.setBackgroundBrush(QColor("#1e1e1e"))
        self._components: list[ComponentItem] = []
        self._wires: list[WireItem] = []
        self._uid = 0
        self._pending_pin = None  # (ComponentItem, pin_index) for wire start
        self._preview_line: QGraphicsPathItem | None = None
        self.selectionChanged.connect(self._emit_selection)
        # Overlay drawing junction-dot / no-connect hop indicators
        self._crossings = CrossingsOverlay(self)
        self.addItem(self._crossings)
        self.graphChanged.connect(self._refresh_crossings)

    # --- background grid ---
    def drawBackground(self, painter: QPainter, rect: QRectF):  # noqa: N802
        super().drawBackground(painter, rect)
        left = int(rect.left()) - (int(rect.left()) % GRID)
        top = int(rect.top()) - (int(rect.top()) % GRID)
        pen = QPen(QColor("#2c2c2c"))
        pen.setWidth(0)
        painter.setPen(pen)
        x = left
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += GRID
        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += GRID

    # --- helpers ---
    def snap(self, p: QPointF) -> QPointF:
        return QPointF(round(p.x() / GRID) * GRID, round(p.y() / GRID) * GRID)

    def next_id(self, kind: str) -> str:
        self._uid += 1
        return f"{kind}{self._uid}"

    # --- API used by view/palette ---
    def add_component(self, kind: str, scene_pos: QPointF) -> ComponentItem | None:
        # IPROBE only makes sense clamped onto a wire — drop it on a wire
        # and we auto-split that wire to insert it inline.  Dropping in
        # empty space is a no-op so the user doesn't end up with an
        # unconnected probe that produces zero current.
        if kind == "IPROBE":
            wire = self._wire_at(scene_pos)
            if wire is None:
                return None
            return self._insert_iprobe_on_wire(wire, scene_pos)
        spec = CATALOG[kind]
        cid = self.next_id(kind)
        item = ComponentItem(cid, kind, spec)
        item.setPos(self.snap(scene_pos))
        self.addItem(item)
        self._components.append(item)
        self.graphChanged.emit()
        return item

    def _segment_orientation_at(self, wire: WireItem,
                                scene_pos: QPointF) -> str:
        """Return 'h' or 'v' based on the wire segment closest to scene_pos."""
        path = wire._path
        n = path.elementCount()
        best_d = float("inf")
        best = "h"
        for i in range(n - 1):
            a = path.elementAt(i); b = path.elementAt(i + 1)
            ax, ay, bx, by = a.x, a.y, b.x, b.y
            if abs(ay - by) < 0.5:
                x = max(min(scene_pos.x(), max(ax, bx)), min(ax, bx))
                d = ((x - scene_pos.x()) ** 2
                     + (ay - scene_pos.y()) ** 2) ** 0.5
                horiz = True
            elif abs(ax - bx) < 0.5:
                y = max(min(scene_pos.y(), max(ay, by)), min(ay, by))
                d = ((ax - scene_pos.x()) ** 2
                     + (y - scene_pos.y()) ** 2) ** 0.5
                horiz = False
            else:
                continue
            if d < best_d:
                best_d = d
                best = "h" if horiz else "v"
        return best

    def _insert_iprobe_on_wire(self, wire: WireItem,
                               scene_pos: QPointF) -> ComponentItem | None:
        """Place an IPROBE inline on `wire`: remove the wire and replace
        with two new wires (a → IPROBE.in, IPROBE.out → b)."""
        orient = self._segment_orientation_at(wire, scene_pos)
        rotation = 0.0 if orient == "h" else 90.0

        spec = CATALOG["IPROBE"]
        cid = self.next_id("IPROBE")
        item = ComponentItem(cid, "IPROBE", spec)
        item.setPos(self.snap(scene_pos))
        item.setRotation(rotation)
        self.addItem(item)
        self._components.append(item)

        a_comp, a_pin = wire.a_comp, wire.a_pin
        b_comp, b_pin = wire.b_comp, wire.b_pin
        a_pos = a_comp.pin_scene_pos(a_pin)
        p0 = item.pin_scene_pos(0)
        p1 = item.pin_scene_pos(1)
        if (p0 - a_pos).manhattanLength() <= (p1 - a_pos).manhattanLength():
            a_side, b_side = 0, 1
        else:
            a_side, b_side = 1, 0

        self._remove_wire_internal(wire)
        w1 = WireItem(a_comp, a_pin, item, a_side)
        self.addItem(w1)
        self._wires.append(w1)
        w2 = WireItem(item, b_side, b_comp, b_pin)
        self.addItem(w2)
        self._wires.append(w2)

        self._cleanup_orphan_junctions()
        self.graphChanged.emit()
        return item

    def remove_component(self, item: ComponentItem) -> None:
        # Remove attached wires
        for w in list(self._wires):
            if w.a_comp is item or w.b_comp is item:
                self._remove_wire_internal(w)
        # Drop any JUNCTION whose tap target was a pin on this component
        prefix = f"{item.cid}."
        for c in list(self._components):
            if c.kind == "JUNCTION" and c.tap_pin and c.tap_pin.startswith(prefix):
                self.remove_component(c)
        self.removeItem(item)
        if item in self._components:
            self._components.remove(item)
        self._cleanup_orphan_junctions()
        self.graphChanged.emit()

    def _remove_wire_internal(self, wire: WireItem) -> None:
        """Remove a wire and orphan-cascade any JUNCTION that taps it."""
        if wire in self._wires:
            self._wires.remove(wire)
        self.removeItem(wire)
        # Any JUNCTION tapping this wire is now floating → remove it
        for c in list(self._components):
            if c.kind == "JUNCTION" and getattr(c, "tap_wire", None) is wire:
                self.remove_component(c)

    def remove_wire(self, wire: WireItem) -> None:
        self._remove_wire_internal(wire)
        self._cleanup_orphan_junctions()
        self.graphChanged.emit()

    def _cleanup_orphan_junctions(self) -> None:
        """Drop JUNCTIONs whose tap_wire is missing or whose tap_pin no
        longer resolves — a node not on a wire is a floating (open) node."""
        cid_set = {c.cid for c in self._components}
        for c in list(self._components):
            if c.kind != "JUNCTION":
                continue
            tw = getattr(c, "tap_wire", None)
            ok = (tw is not None and tw in self._wires)
            if ok and c.tap_pin:
                tcid = c.tap_pin.split(".")[0]
                if tcid not in cid_set:
                    ok = False
            if not ok:
                # Cascade: remove without re-emitting graphChanged repeatedly
                for w in list(self._wires):
                    if w.a_comp is c or w.b_comp is c:
                        if w in self._wires:
                            self._wires.remove(w)
                        self.removeItem(w)
                self.removeItem(c)
                if c in self._components:
                    self._components.remove(c)

    def begin_wire(self, comp: ComponentItem, pin_index: int) -> None:
        if self._pending_pin is None:
            self._pending_pin = (comp, pin_index)
            self._show_preview_to(comp.pin_scene_pos(pin_index))
        else:
            a_comp, a_pin = self._pending_pin
            self._pending_pin = None
            self._hide_preview()
            if a_comp is comp and a_pin == pin_index:
                return
            wire = WireItem(a_comp, a_pin, comp, pin_index)
            self.addItem(wire)
            self._wires.append(wire)
            self.graphChanged.emit()

    def cancel_wire(self) -> None:
        self._pending_pin = None
        self._hide_preview()

    # --- live preview path for drag-to-wire ---
    def _preview_blockers(self, exclude: ComponentItem | None,
                          exclude_pin: int | None = None,
                          exclude_target: ComponentItem | None = None,
                          target_pin: int | None = None) -> list[QRectF]:
        """Return blocker rects matching WireItem._blockers() so the
        dashed preview routes identically to the solid wire that will
        be created on release."""
        out = []

        def endpoint_blocker(c: ComponentItem, pin: int | None) -> QRectF:
            r = c.sceneBoundingRect().adjusted(3, 3, -3, -3)
            if pin is None:
                return r
            p = c.pin_scene_pos(pin)
            d = c.pin_exit_direction(pin)
            if d is None:
                return r
            if abs(d.x()) >= abs(d.y()) and d.x() > 0:
                r.setRight(min(r.right(), p.x() - 2))
            elif abs(d.x()) >= abs(d.y()) and d.x() < 0:
                r.setLeft(max(r.left(), p.x() + 2))
            elif d.y() > 0:
                r.setBottom(min(r.bottom(), p.y() - 2))
            elif d.y() < 0:
                r.setTop(max(r.top(), p.y() + 2))
            return r

        for c in self._components:
            if c is exclude:
                out.append(endpoint_blocker(c, exclude_pin))
                continue
            if c is exclude_target:
                out.append(endpoint_blocker(c, target_pin))
                continue
            out.append(c.sceneBoundingRect().adjusted(-4, -4, 4, 4))
        return out

    def _show_preview_to(self, scene_pos: QPointF) -> None:
        if self._pending_pin is None:
            return
        a_comp, a_pin = self._pending_pin
        a = a_comp.pin_scene_pos(a_pin)
        a_dir = a_comp.pin_exit_direction(a_pin)
        # Snap free end to grid for nicer preview
        end = self.snap(scene_pos)
        # If hovering over a pin, snap exactly to it & adopt its outward dir
        hit = self.pin_at(scene_pos, exclude=a_comp, exclude_pin=a_pin)
        b_dir = None
        on_target = False
        if hit is not None:
            b_comp, b_pin = hit
            end = b_comp.pin_scene_pos(b_pin)
            b_dir = b_comp.pin_exit_direction(b_pin)
            blockers = self._preview_blockers(exclude=a_comp,
                                              exclude_pin=a_pin,
                                              exclude_target=b_comp,
                                              target_pin=b_pin)
            blockers = [r for r in blockers
                        if not r.contains(b_comp.pin_scene_pos(b_pin))]
            on_target = True
        else:
            # Hovering over a wire? Snap preview to the actual tap point
            # the click would land on, so the dashed line visibly meets
            # the wire and the user sees a connection is possible.
            wire = self._wire_at(scene_pos)
            if wire is not None and wire.a_comp is not a_comp:
                jpos = self._pick_junction_position(wire, scene_pos, a)
                if jpos is not None:
                    end = jpos
                    on_target = True
            blockers = self._preview_blockers(exclude=a_comp,
                                              exclude_pin=a_pin)
        pts, _, _ = orthogonal_route(a, a_dir, end, b_dir,
                                     mid_x=None, mid_y=None,
                                     blockers=blockers)
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        # Brighter solid pen when over a valid target so user has clear
        # visual feedback that releasing here will connect.  Off-target
        # uses an explicit RGBA so it stays clearly visible (a 6-digit
        # green + Qt's #AARRGGBB parsing of an 8-digit hex used to
        # silently produce a near-invisible orange).
        if on_target:
            color = QColor(120, 255, 120, 255)
            style = Qt.PenStyle.SolidLine
            width = 3
        else:
            color = QColor(120, 255, 120, 200)
            style = Qt.PenStyle.DashLine
            width = 2
        if self._preview_line is None:
            pen = QPen(color)
            pen.setStyle(style)
            pen.setWidth(width)
            self._preview_line = QGraphicsPathItem(path)
            self._preview_line.setPen(pen)
            self._preview_line.setZValue(10)
            self.addItem(self._preview_line)
        else:
            pen = QPen(color)
            pen.setStyle(style)
            pen.setWidth(width)
            self._preview_line.setPen(pen)
            self._preview_line.setPath(path)

    def _hide_preview(self) -> None:
        if self._preview_line is not None:
            self.removeItem(self._preview_line)
            self._preview_line = None

    def update_preview_to(self, scene_pos: QPointF) -> None:
        self._show_preview_to(scene_pos)

    def pin_at(self, scene_pos: QPointF,
               exclude: ComponentItem | None = None,
               exclude_pin: int | None = None) -> tuple[ComponentItem, int] | None:
        """Find a pin near the given scene position, if any."""
        best = None
        best_d2 = (PIN_HIT_RADIUS) ** 2
        for c in self._components:
            for i in range(c.n_pins):
                if c is exclude and i == exclude_pin:
                    continue
                p = c.pin_scene_pos(i)
                d2 = (p.x() - scene_pos.x()) ** 2 + (p.y() - scene_pos.y()) ** 2
                if d2 <= best_d2:
                    best_d2 = d2
                    best = (c, i)
        return best

    def try_finish_wire_at(self, scene_pos: QPointF) -> bool:
        """If pending and cursor is over a pin or wire, complete and return True."""
        if self._pending_pin is None:
            return False
        a_comp, a_pin = self._pending_pin
        # 1) prefer an exact pin hit
        hit = self.pin_at(scene_pos, exclude=a_comp, exclude_pin=a_pin)
        if hit is not None:
            b_comp, b_pin = hit
            self._pending_pin = None
            self._hide_preview()
            wire = WireItem(a_comp, a_pin, b_comp, b_pin)
            self.addItem(wire)
            self._wires.append(wire)
            self.graphChanged.emit()
            return True
        # 2) dropped on an existing wire → place a JUNCTION as a tap
        target_wire = self._wire_at(scene_pos)
        if target_wire is not None and target_wire.a_comp is not a_comp \
                and target_wire.b_comp is not a_comp:
            jpos = self._pick_junction_position(target_wire, scene_pos,
                                                from_pin=a_comp.pin_scene_pos(a_pin))
            if jpos is None:
                # No safe spot on the wire — refuse the connection.
                return False
            self._pending_pin = None
            self._hide_preview()
            j = self.add_component("JUNCTION", jpos)
            # Logical tap: junction's node will be unioned with the
            # target wire's a-pin in to_graph().  Original wire is left
            # intact (no split).
            j.tap_pin = f"{target_wire.a_comp.cid}.{target_wire.a_pin}"
            j.tap_wire = target_wire
            # Pin position to the snapped point (bypassing grid-snap path)
            j.setPos(jpos)
            wire = WireItem(a_comp, a_pin, j, 0)
            self.addItem(wire)
            self._wires.append(wire)
            self.graphChanged.emit()
            return True
        return False

    def _wire_at(self, scene_pos: QPointF) -> WireItem | None:
        """Find a wire whose polyline passes within a tight tolerance of
        `scene_pos`.  Tolerance is intentionally smaller than the visible
        wire selection shape so that an accidental near-miss does not
        create a phantom T-junction."""
        TOL = 6.0
        best: WireItem | None = None
        best_d = TOL
        for w in self._wires:
            d = self._distance_to_wire(w, scene_pos)
            if d <= best_d:
                best_d = d
                best = w
        return best

    @staticmethod
    def _distance_to_wire(wire: WireItem, p: QPointF) -> float:
        path = wire._path
        n = path.elementCount()
        best = float("inf")
        for i in range(n - 1):
            a = path.elementAt(i); b = path.elementAt(i + 1)
            ax, ay, bx, by = a.x, a.y, b.x, b.y
            if abs(ay - by) < 0.5:  # horizontal
                x = max(min(p.x(), max(ax, bx)), min(ax, bx))
                d = ((x - p.x()) ** 2 + (ay - p.y()) ** 2) ** 0.5
            elif abs(ax - bx) < 0.5:  # vertical
                y = max(min(p.y(), max(ay, by)), min(ay, by))
                d = ((ax - p.x()) ** 2 + (y - p.y()) ** 2) ** 0.5
            else:
                continue
            if d < best:
                best = d
        return best

    def _pick_junction_position(self, wire: WireItem, drop: QPointF,
                                from_pin: QPointF) -> QPointF | None:
        """Snap `drop` to a point ON `wire` such that:
          * the snapped point itself is not inside another component bbox,
          * the orthogonal route from `from_pin` to that point clears
            every other component bbox.
        Among all candidate points on the wire's polyline (snapped to the
        grid), prefer the one closest to `drop` whose route is clear; if
        none is clear, pick the one whose route has the fewest crossings.
        Returns None if even the snapped point is blocked everywhere."""
        from .component_item import ComponentItem
        from .wire_routing import orthogonal_route

        blockers: list[QRectF] = []
        for c in self._components:
            if c is wire.a_comp or c is wire.b_comp:
                continue
            blockers.append(c.sceneBoundingRect().adjusted(-4, -4, 4, 4))

        def blocked(p: QPointF) -> bool:
            return any(r.contains(p) for r in blockers)

        # Build candidate set: every grid-snapped point along the wire's
        # axis-aligned segments.
        path = wire._path
        n = path.elementCount()
        candidates: list[QPointF] = []
        for i in range(n - 1):
            a = path.elementAt(i); b = path.elementAt(i + 1)
            ax, ay, bx, by = a.x, a.y, b.x, b.y
            if abs(ay - by) < 0.5:
                lo = int(round(min(ax, bx) / GRID) * GRID)
                hi = int(round(max(ax, bx) / GRID) * GRID)
                v = lo
                while v <= hi:
                    candidates.append(QPointF(v, ay))
                    v += GRID
            elif abs(ax - bx) < 0.5:
                lo = int(round(min(ay, by) / GRID) * GRID)
                hi = int(round(max(ay, by) / GRID) * GRID)
                v = lo
                while v <= hi:
                    candidates.append(QPointF(ax, v))
                    v += GRID
        free = [p for p in candidates if not blocked(p)]
        if not free:
            return None

        # Get source pin's outward direction from the *originating* pin
        # so the routing simulation matches what the new wire will draw.
        src_dir = None
        for c in self._components:
            for i in range(c.n_pins):
                if (c.pin_scene_pos(i) - from_pin).manhattanLength() < 0.5:
                    src_dir = c.pin_exit_direction(i)
                    break
            if src_dir is not None:
                break

        def route_crossings(target: QPointF) -> int:
            pts, _, _ = orthogonal_route(from_pin, src_dir, target, None,
                                         mid_x=None, mid_y=None,
                                         blockers=blockers)
            count = 0
            for r in blockers:
                for p1, p2 in zip(pts, pts[1:]):
                    # Re-use _seg_in_rect from wire_routing for consistency
                    from .wire_routing import _seg_in_rect
                    if _seg_in_rect(p1, p2, r):
                        count += 1
            return count

        # Sort candidates by (distance to drop, #crossings).  The user
        # released over a specific point on the wire and expects the
        # tap node to land *there*; crossings are used only as a
        # tiebreaker when two grid points are equally close.
        scored = [((p.x() - drop.x()) ** 2 + (p.y() - drop.y()) ** 2,
                   route_crossings(p),
                   p) for p in free]
        scored.sort(key=lambda t: (t[0], t[1]))
        return scored[0][2]

    def _split_wire_with_junction(self, wire: WireItem,
                                  scene_pos: QPointF) -> ComponentItem:
        """Legacy helper kept for backwards compatibility — now equivalent
        to placing a tap junction (no actual split)."""
        j = self.add_component("JUNCTION", scene_pos)
        j.tap_pin = f"{wire.a_comp.cid}.{wire.a_pin}"
        return j

    def _emit_selection(self):
        items = self.selectedItems()
        comp = next((i for i in items if isinstance(i, ComponentItem)), None)
        self.selectionStateChanged.emit(comp)

    def _refresh_crossings(self) -> None:
        self._crossings.recompute()
        self._crossings.update()

    # --- serialization ---
    def to_graph(self) -> dict:
        components = []
        for c in self._components:
            entry = {
                "id": c.cid,
                "kind": c.kind,
                "params": dict(c.params),
                "pins": [None] * c.n_pins,
                "pos": [c.pos().x(), c.pos().y()],
                "rotation": c.rotation(),
                "tap_pin": c.tap_pin,
            }
            sc = c.scale()
            if sc and abs(sc - 1.0) > 1e-3:
                entry["scale"] = float(sc)
            components.append(entry)
        wires = [{"a": f"{w.a_comp.cid}.{w.a_pin}",
                  "b": f"{w.b_comp.cid}.{w.b_pin}"} for w in self._wires]
        # Synthetic wires for JUNCTION taps so the netlist unions correctly
        # without splitting the visible wire.
        for c in self._components:
            if c.kind == "JUNCTION" and c.tap_pin:
                wires.append({"a": f"{c.cid}.0", "b": c.tap_pin,
                              "synthetic": True})
        # GND symbol pins are tagged as node "0"
        for c, raw in zip(self._components, components):
            if c.kind == "GND":
                raw["pins"][0] = "0"
        return {"components": components, "wires": wires}

    def load_graph(self, graph: dict) -> None:
        self.clear()
        self._components.clear()
        self._wires.clear()
        # self.clear() destroyed the CrossingsOverlay along with everything
        # else; rebuild it so dot/hop/shift indicators render on the
        # freshly-loaded schematic.
        self._crossings = CrossingsOverlay(self)
        self.addItem(self._crossings)
        self._uid = 0
        id_to_comp: dict[str, ComponentItem] = {}
        for c in graph.get("components", []):
            spec = CATALOG[c["kind"]]
            item = ComponentItem(c["id"], c["kind"], spec)
            item.params = dict(c.get("params", spec["default_params"]))
            item.tap_pin = c.get("tap_pin")
            pos = c.get("pos", [0, 0])
            item.setPos(QPointF(pos[0], pos[1]))
            item.setRotation(c.get("rotation", 0))
            sc = c.get("scale")
            if sc:
                try:
                    item.setScale(float(sc))
                except Exception:
                    pass
            self.addItem(item)
            self._components.append(item)
            id_to_comp[c["id"]] = item
            try:
                self._uid = max(self._uid, int("".join(ch for ch in c["id"] if ch.isdigit()) or 0))
            except ValueError:
                pass
        for w in graph.get("wires", []):
            if w.get("synthetic"):
                continue  # rebuilt automatically from tap_pin on save
            a_id, a_pin = w["a"].split(".")
            b_id, b_pin = w["b"].split(".")
            wire = WireItem(id_to_comp[a_id], int(a_pin),
                            id_to_comp[b_id], int(b_pin))
            self.addItem(wire)
            self._wires.append(wire)
        # Resolve tap_wire references for JUNCTION components
        for c in self._components:
            if c.kind == "JUNCTION" and c.tap_pin:
                for w in self._wires:
                    aid = f"{w.a_comp.cid}.{w.a_pin}"
                    bid = f"{w.b_comp.cid}.{w.b_pin}"
                    if c.tap_pin in (aid, bid):
                        c.tap_wire = w
                        break
        self._cleanup_orphan_junctions()
        self.graphChanged.emit()

