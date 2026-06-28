"""Graphics item representing a circuit component with pins."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QPointF, Qt
from PyQt6.QtGui import (QPen, QBrush, QColor, QPainter, QFont, QTransform,
                         QAction, QPainterPath)
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsObject, QMenu

from batsim_core.components.catalog import CATALOG, pin_offsets


DRAG_THRESHOLD = 4  # pixels of movement that distinguish drag from click
HANDLE_SIZE = 8     # corner resize handle square (local px before scale)
MIN_SCALE = 0.5
MAX_SCALE = 4.0


def _symbol_bbox(spec: dict) -> QRectF:
    """Tight bbox over the visible symbol primitives — excludes the
    user-facing label area so hit-testing only catches the body."""
    xs: list[float] = []
    ys: list[float] = []
    for prim in spec.get("symbol", []):
        tag = prim[0]
        if tag == "line":
            xs += [prim[1], prim[3]]; ys += [prim[2], prim[4]]
        elif tag == "rect":
            xs += [prim[1], prim[1] + prim[3]]
            ys += [prim[2], prim[2] + prim[4]]
        elif tag in ("circle", "fcircle"):
            cx, cy, r = prim[1], prim[2], prim[3]
            xs += [cx - r, cx + r]; ys += [cy - r, cy + r]
        elif tag == "arc":
            x, y, w, h = prim[1:5]
            xs += [x, x + w]; ys += [y, y + h]
        elif tag == "text":
            width = max(20, len(str(prim[3])) * 8 + 8)
            xs += [prim[1] - width / 2, prim[1] + width / 2]
            ys += [prim[2] - 8, prim[2] + 4]
    if not xs:
        return QRectF(-30, -10, 60, 20)
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


class ComponentItem(QGraphicsObject):
    PIN_R = 4

    def __init__(self, cid: str, kind: str, spec: dict):
        super().__init__()
        self.cid = cid
        self.kind = kind
        self.spec = spec
        self.params: dict = dict(spec["default_params"])
        self.n_pins: int = spec["pins"]
        self._pin_offsets = pin_offsets(kind)
        self._sym_bbox = _symbol_bbox(spec)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setTransformOriginPoint(0, 0)
        self._dragging_pin = None
        self._drag_start_scene: QPointF | None = None
        # Resize handle currently being dragged ('tl'/'tr'/'bl'/'br').
        self._resize_handle: str | None = None
        self._resize_start_scale: float = 1.0
        self._resize_start_dist: float = 1.0
        # For JUNCTION components placed on top of an existing wire as a
        # tap, this stores the pin label of the original wire's endpoint.
        # Used by `to_graph` to emit a synthetic wire connecting the
        # junction to that node so the netlist remains correct without
        # actually splitting the visible wire.
        self.tap_pin: str | None = None
        # Runtime reference to the wire this junction is anchored to.
        # When set, the junction's movement is constrained to slide along
        # that wire's polyline (and never cross other components).
        self.tap_wire = None

    # --- geometry ---
    def _label_rect(self) -> QRectF:
        """Local rect reserved for the dynamic ID+value label, drawn just
        above the symbol body so it stays attached visually."""
        if self.kind in ("JUNCTION", "IPROBE"):
            return QRectF()
        sb = self._sym_bbox
        label = self.cid
        v = self._main_value()
        if v is not None:
            label = f"{self.cid}={v}"
        width = max(sb.width(), len(label) * 7 + 10, 48)
        cx = sb.center().x()
        return QRectF(cx - width / 2, sb.top() - 16, width, 14)

    def boundingRect(self) -> QRectF:  # noqa: N802
        if self.kind == "JUNCTION":
            return QRectF(-8, -8, 16, 16)
        if self.kind == "IPROBE":
            return QRectF(-16, -22, 32, 44)
        body = self._sym_bbox.adjusted(-4, -4, 4, 4)
        body = body.united(self._label_rect())
        # Reserve room for the corner resize handles when selected.
        return body.adjusted(-HANDLE_SIZE, -HANDLE_SIZE,
                             HANDLE_SIZE, HANDLE_SIZE)

    def shape(self):  # noqa: N802
        """Tight hit-test region: only the symbol body + corner handles
        when selected.  This keeps wires routed near the component
        clickable instead of being swallowed by the much-larger
        boundingRect."""
        path = QPainterPath()
        if self.kind in ("JUNCTION", "IPROBE"):
            path.addRect(self.boundingRect())
            return path
        body = self._sym_bbox.adjusted(-2, -2, 2, 2)
        path.addRect(body)
        # Pin discs so users can still grab pins outside the body.
        for x, y in self._pin_offsets:
            path.addEllipse(QPointF(x, y), self.PIN_R + 4, self.PIN_R + 4)
        # Resize handles — only hit-testable when selected.
        if self.isSelected():
            for hx, hy in self._handle_centres():
                path.addRect(hx - HANDLE_SIZE / 2, hy - HANDLE_SIZE / 2,
                             HANDLE_SIZE, HANDLE_SIZE)
        return path

    def _handle_centres(self) -> list[tuple[float, float]]:
        if self.kind in ("JUNCTION", "IPROBE"):
            return []
        body = self._sym_bbox.united(self._label_rect()).adjusted(-4, -4, 4, 4)
        return [(body.left(),  body.top()),
                (body.right(), body.top()),
                (body.left(),  body.bottom()),
                (body.right(), body.bottom())]

    def _handle_at(self, local_pt: QPointF) -> str | None:
        names = ("tl", "tr", "bl", "br")
        for name, (hx, hy) in zip(names, self._handle_centres()):
            if abs(local_pt.x() - hx) <= HANDLE_SIZE and \
               abs(local_pt.y() - hy) <= HANDLE_SIZE:
                return name
        return None

    def pin_scene_pos(self, idx: int) -> QPointF:
        x, y = self._pin_offsets[idx]
        return self.mapToScene(QPointF(x, y))

    def pin_exit_direction(self, idx: int) -> QPointF | None:
        """Outward direction at this pin in scene coordinates (length ~1).

        Returns None for centre pins (e.g., JUNCTION) where there is no
        natural outward direction — those pins behave as free points."""
        x, y = self._pin_offsets[idx]
        if x == 0 and y == 0:
            return None
        if abs(x) >= abs(y):
            local = QPointF(1.0 if x > 0 else -1.0, 0.0)
        else:
            local = QPointF(0.0, 1.0 if y > 0 else -1.0)
        # Map a small displacement through the item's transform so we get
        # the direction in scene coords (rotation + mirror aware).
        p0 = self.mapToScene(QPointF(0, 0))
        p1 = self.mapToScene(QPointF(local.x() * 10, local.y() * 10))
        return QPointF(p1.x() - p0.x(), p1.y() - p0.y())

    def connected_pin_indices(self) -> list[int]:
        scene = self.scene()
        if scene is None:
            return []
        out = []
        for w in getattr(scene, "_wires", []):
            if w.a_comp is self:
                out.append(w.a_pin)
            if w.b_comp is self:
                out.append(w.b_pin)
        return out

    def _refresh_attached_wires(self) -> None:
        for w in getattr(self.scene(), "_wires", []):
            if w.a_comp is self or w.b_comp is self:
                w.refresh()

    def rotate_keeping_wires(self, delta_deg: float) -> None:
        """Rotate the component around the centroid of its connected pins
        so wires visually stay attached without moving their endpoints."""
        pins = self.connected_pin_indices() or list(range(self.n_pins))
        before = [self.pin_scene_pos(i) for i in pins]
        cx = sum(p.x() for p in before) / len(before)
        cy = sum(p.y() for p in before) / len(before)
        self.setRotation((self.rotation() + delta_deg) % 360)
        after = [self.pin_scene_pos(i) for i in pins]
        cx2 = sum(p.x() for p in after) / len(after)
        cy2 = sum(p.y() for p in after) / len(after)
        scene = self.scene()
        new = self.pos() + QPointF(cx - cx2, cy - cy2)
        if scene is not None:
            new = scene.snap(new)
        self.setPos(new)
        self._refresh_attached_wires()
        sc = self.scene()
        if sc is not None and hasattr(sc, "graphChanged"):
            sc.graphChanged.emit()

    def mirror_keeping_wires(self) -> None:
        from PyQt6.QtGui import QTransform
        pins = self.connected_pin_indices() or list(range(self.n_pins))
        before = [self.pin_scene_pos(i) for i in pins]
        cx = sum(p.x() for p in before) / len(before)
        cy = sum(p.y() for p in before) / len(before)
        self.setTransform(self.transform() * QTransform.fromScale(-1, 1))
        after = [self.pin_scene_pos(i) for i in pins]
        cx2 = sum(p.x() for p in after) / len(after)
        cy2 = sum(p.y() for p in after) / len(after)
        scene = self.scene()
        new = self.pos() + QPointF(cx - cx2, cy - cy2)
        if scene is not None:
            new = scene.snap(new)
        self.setPos(new)
        self._refresh_attached_wires()
        if scene is not None and hasattr(scene, "graphChanged"):
            scene.graphChanged.emit()

    # --- painting ---
    def paint(self, painter: QPainter, option, widget=None):
        sel = self.isSelected()
        col = QColor("#9cd8ff") if sel else QColor("#dcdcdc")
        pen = QPen(col)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Symbol descriptive text (drawn inside the symbol primitives).
        sym_font = QFont(painter.font())
        sym_font.setPointSize(9)
        sym_font.setBold(True)
        painter.setFont(sym_font)

        for prim in self.spec["symbol"]:
            tag = prim[0]
            if tag == "line":
                painter.drawLine(int(prim[1]), int(prim[2]), int(prim[3]), int(prim[4]))
            elif tag == "rect":
                painter.drawRect(int(prim[1]), int(prim[2]), int(prim[3]), int(prim[4]))
            elif tag == "circle":
                cx, cy, r = prim[1], prim[2], prim[3]
                painter.drawEllipse(QPointF(cx, cy), r, r)
            elif tag == "fcircle":
                cx, cy, r = prim[1], prim[2], prim[3]
                painter.setBrush(QBrush(col))
                painter.drawEllipse(QPointF(cx, cy), r, r)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            elif tag == "arc":
                x, y, w, h, a, span = prim[1:]
                painter.drawArc(int(x), int(y), int(w), int(h), int(a * 16), int(span * 16))
            elif tag == "text":
                text = str(prim[3])
                fm = painter.fontMetrics()
                width = max(20, fm.horizontalAdvance(text) + 8)
                rect = QRectF(prim[1] - width / 2, prim[2] - 12,
                              width, 16)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        # Pins — IPROBE has no user-clickable pins (it clamps onto a wire
        # and is operated as a single point), so skip drawing them.
        if self.kind != "IPROBE":
            pin_pen = QPen(QColor("#ffcc66"))
            pin_pen.setWidth(1)
            painter.setPen(pin_pen)
            painter.setBrush(QBrush(QColor("#ffcc66")))
            hover_pin = getattr(self, "_hover_pin", None)
            for i, (x, y) in enumerate(self._pin_offsets):
                r = self.PIN_R + (3 if i == hover_pin else 0)
                painter.drawEllipse(QPointF(x, y), r, r)

        # ID + main parameter label, drawn just above the symbol so it
        # stays visually attached to its component (used to be far below
        # the body which made it ambiguous when components were close).
        if self.kind not in ("JUNCTION", "IPROBE"):
            painter.setPen(QPen(QColor("#cccccc")))
            label_font = QFont(painter.font())
            label_font.setPointSize(9)
            painter.setFont(label_font)
            label = self.cid
            v = self._main_value()
            if v is not None:
                label = f"{self.cid}={v}"
            lr = self._label_rect()
            painter.drawText(QRectF(lr), Qt.AlignmentFlag.AlignCenter, label)

        # Resize handles — only when selected
        if self.isSelected() and self.kind not in ("JUNCTION", "IPROBE"):
            painter.setBrush(QBrush(QColor("#ffcc66")))
            painter.setPen(QPen(QColor("#000000")))
            for hx, hy in self._handle_centres():
                painter.drawRect(QRectF(hx - HANDLE_SIZE / 2,
                                        hy - HANDLE_SIZE / 2,
                                        HANDLE_SIZE, HANDLE_SIZE))

    def _main_value(self) -> str | None:
        for k in ("R", "L", "C", "V", "I", "model"):
            if k in self.params:
                v = self.params[k]
                if isinstance(v, float):
                    return f"{v:g}"
                return str(v)
        return None

    # --- interaction: clicking near a pin starts/ends a wire ---
    def mousePressEvent(self, event):  # noqa: N802
        # Track starting position so the release handler can detect drag-moves
        # and emit graphChanged for undo tracking.
        self._press_pos = self.pos()
        if event.button() == Qt.MouseButton.LeftButton:
            # Resize handle: only available when already selected.
            if (self.isSelected()
                    and self.kind not in ("JUNCTION", "IPROBE")):
                h = self._handle_at(event.pos())
                if h is not None:
                    self._resize_handle = h
                    self._resize_start_scale = self.scale() or 1.0
                    s = event.scenePos() - self.scenePos()
                    self._resize_start_dist = max((s.x() ** 2 + s.y() ** 2)
                                                  ** 0.5, 1.0)
                    event.accept()
                    return
            if self.kind == "JUNCTION":
                # Junction is itself a node — record press but defer the
                # "start wire vs. drag" decision until release/move.
                self._drag_start_scene = event.scenePos()
                # Fall through to super() so QGraphicsItem's drag flow
                # initialises (allows dragging if user moves the mouse).
            elif self.kind == "IPROBE":
                # Current probe has no user pins; clicks just move it.
                pass
            else:
                local = event.pos()
                # Generous hit radius (PIN_R + 10) so pins are easy to grab.
                for i, (x, y) in enumerate(self._pin_offsets):
                    if (local.x() - x) ** 2 + (local.y() - y) ** 2 <= (self.PIN_R + 10) ** 2:
                        self._dragging_pin = i
                        self._drag_start_scene = event.scenePos()
                        self.scene().begin_wire(self, i)
                        event.accept()
                        return
        self._dragging_pin = None
        super().mousePressEvent(event)

    def hoverMoveEvent(self, event):  # noqa: N802
        # Highlight the pin nearest the cursor so users can see where a
        # click would grab.  Off-pin → no highlight.
        if self.kind in ("JUNCTION", "IPROBE"):
            super().hoverMoveEvent(event); return
        local = event.pos()
        best = None
        best_d2 = (self.PIN_R + 10) ** 2
        for i, (x, y) in enumerate(self._pin_offsets):
            d2 = (local.x() - x) ** 2 + (local.y() - y) ** 2
            if d2 < best_d2:
                best = i; best_d2 = d2
        if best != getattr(self, "_hover_pin", None):
            self._hover_pin = best
            self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):  # noqa: N802
        if getattr(self, "_hover_pin", None) is not None:
            self._hover_pin = None
            self.update()
        super().hoverLeaveEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._resize_handle is not None:
            s = event.scenePos() - self.scenePos()
            dist = max((s.x() ** 2 + s.y() ** 2) ** 0.5, 1.0)
            ratio = dist / self._resize_start_dist
            new = max(MIN_SCALE, min(MAX_SCALE,
                                     self._resize_start_scale * ratio))
            # Snap scale to 0.1 increments for predictability.
            new = round(new * 10.0) / 10.0
            if abs(new - self.scale()) > 1e-3:
                self.prepareGeometryChange()
                self.setScale(new)
                self._refresh_attached_wires()
                sc = self.scene()
                if sc is not None and hasattr(sc, "_refresh_crossings"):
                    sc._refresh_crossings()
            event.accept()
            return
        if self._dragging_pin is not None:
            self.scene().update_preview_to(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)
        # Live-refresh wires while the component is being dragged
        for w in getattr(self.scene(), "_wires", []):
            if w.a_comp is self or w.b_comp is self:
                w.refresh()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._resize_handle is not None:
            self._resize_handle = None
            sc = self.scene()
            if sc is not None and hasattr(sc, "graphChanged"):
                sc.graphChanged.emit()
            event.accept()
            return
        if self._dragging_pin is not None:
            scene = self.scene()
            start = self._drag_start_scene or event.scenePos()
            moved = ((event.scenePos().x() - start.x()) ** 2
                     + (event.scenePos().y() - start.y()) ** 2) > DRAG_THRESHOLD ** 2
            if scene.try_finish_wire_at(event.scenePos()):
                pass  # wire completed
            elif moved:
                # User dragged but released on empty space → cancel; no wire created
                scene.cancel_wire()
            # else: pure click on pin → leave pending so click-click flow works
            self._dragging_pin = None
            self._drag_start_scene = None
            event.accept()
            return
        # JUNCTION: a click without movement starts a new wire from this
        # node (treats junction identically to a pin).
        if (self.kind == "JUNCTION"
                and self._drag_start_scene is not None
                and event.button() == Qt.MouseButton.LeftButton):
            start = self._drag_start_scene
            moved = ((event.scenePos().x() - start.x()) ** 2
                     + (event.scenePos().y() - start.y()) ** 2) > DRAG_THRESHOLD ** 2
            self._drag_start_scene = None
            if not moved and self.scene() is not None:
                self.scene().begin_wire(self, 0)
                event.accept()
                return
        super().mouseReleaseEvent(event)
        # Snap to grid + emit graphChanged once any drag-move actually changed
        # the position so the undo manager records the move.
        sc = self.scene()
        before = getattr(self, "_press_pos", None)
        self._press_pos = None
        if sc is not None and before is not None and self.pos() != before:
            snapped = sc.snap(self.pos())
            if snapped != self.pos():
                self.setPos(snapped)
                self._refresh_attached_wires()
            if hasattr(sc, "graphChanged"):
                sc.graphChanged.emit()

    def contextMenuEvent(self, event):  # noqa: N802
        menu = QMenu()
        a_rot_cw  = menu.addAction("회전 90°  (R)")
        a_rot_ccw = menu.addAction("회전 -90°")
        a_mirror  = menu.addAction("좌우 반전 (M)")
        menu.addSeparator()
        a_del     = menu.addAction("삭제 (Del)")
        chosen = menu.exec(event.screenPos())
        if chosen is None:
            return
        scene = self.scene()
        if chosen is a_rot_cw:
            self.rotate_keeping_wires(90)
        elif chosen is a_rot_ccw:
            self.rotate_keeping_wires(-90)
        elif chosen is a_mirror:
            self.mirror_keeping_wires()
        elif chosen is a_del:
            scene.remove_component(self)

    def _project_onto_tap_wire(self, proposed: QPointF) -> QPointF:
        """Project `proposed` onto the closest point of the tapped wire's
        polyline that does not fall inside another component's bbox.
        Falls back to the current position if every candidate is blocked."""
        wire = self.tap_wire
        scene = self.scene()
        if wire is None or scene is None:
            return scene.snap(proposed) if scene else proposed
        # Build blockers (other components, not the tapped wire's endpoints).
        blockers: list[QRectF] = []
        for c in getattr(scene, "_components", []):
            if c is self or c is wire.a_comp or c is wire.b_comp:
                continue
            blockers.append(c.sceneBoundingRect().adjusted(-4, -4, 4, 4))

        def blocked(p: QPointF) -> bool:
            return any(r.contains(p) for r in blockers)

        path = wire._path
        n = path.elementCount()
        if n < 2:
            return self.pos()
        best: QPointF | None = None
        best_d2 = float("inf")
        for i in range(n - 1):
            a = path.elementAt(i); b = path.elementAt(i + 1)
            ax, ay, bx, by = a.x, a.y, b.x, b.y
            # Closest point on axis-aligned segment to proposed
            if abs(ay - by) < 0.5:  # horizontal
                x = max(min(proposed.x(), max(ax, bx)), min(ax, bx))
                cand = QPointF(round(x / 20) * 20, ay)
            elif abs(ax - bx) < 0.5:  # vertical
                y = max(min(proposed.y(), max(ay, by)), min(ay, by))
                cand = QPointF(ax, round(y / 20) * 20)
            else:
                continue
            if blocked(cand):
                continue
            d2 = (cand.x() - proposed.x()) ** 2 + (cand.y() - proposed.y()) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best = cand
        return best if best is not None else self.pos()

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            if self.kind == "JUNCTION" and self.tap_wire is not None:
                value = self._project_onto_tap_wire(value)
            else:
                value = self.scene().snap(value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            for w in getattr(scene, "_wires", []):
                if w.a_comp is self or w.b_comp is self:
                    w.refresh()
            if scene is not None and hasattr(scene, "_refresh_crossings"):
                scene._refresh_crossings()
        return super().itemChange(change, value)

