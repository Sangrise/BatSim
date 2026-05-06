"""Wire connecting two component pins with editable orthogonal routing.

The path is auto-routed via `orthogonal_route` until the user drags any
of its bend handles, at which point the wire switches to MANUAL mode and
remembers the polyline.  In manual mode every internal segment exposes
its own draggable handle that slides perpendicular to the segment.  When
sliding would make an adjacent segment non-orthogonal (because both are
on the same axis), an elbow vertex is automatically inserted to preserve
axis-alignment.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QPointF, Qt
from PyQt6.QtGui import (QPen, QColor, QPainter, QPainterPath,
                         QPainterPathStroker, QBrush)
from PyQt6.QtWidgets import QGraphicsItem

from .wire_routing import orthogonal_route, GRID


HANDLE_SIZE = 8
EPS = 0.5


def _is_horizontal(p1: QPointF, p2: QPointF) -> bool:
    return abs(p1.y() - p2.y()) < EPS


def _is_vertical(p1: QPointF, p2: QPointF) -> bool:
    return abs(p1.x() - p2.x()) < EPS


class WireItem(QGraphicsItem):
    def __init__(self, a_comp, a_pin: int, b_comp, b_pin: int):
        super().__init__()
        self.a_comp = a_comp
        self.a_pin = a_pin
        self.b_comp = b_comp
        self.b_pin = b_pin
        # Manual polyline: when None, we re-route automatically every
        # refresh.  Otherwise this stores the explicit list of vertices
        # (with pts[0] = pin_a, pts[-1] = pin_b) that the user has been
        # editing.
        self._manual_pts: list[QPointF] | None = None
        self._pts: list[QPointF] = []
        self._dragging_seg: int | None = None
        self._path = QPainterPath()
        self.setZValue(-1)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self.refresh()

    # ----------------------------------------------------------------
    # Routing
    # ----------------------------------------------------------------
    def _blockers(self) -> list[QRectF]:
        from .component_item import ComponentItem
        scene = self.scene()
        if scene is None:
            return []
        out = []
        for it in scene.items():
            if not isinstance(it, ComponentItem):
                continue
            if it is self.a_comp or it is self.b_comp:
                # Endpoints: include their bbox slightly shrunk so the
                # approach stub (which ends *on* the pin at the boundary)
                # stays outside, but a long detour segment crossing the
                # body interior is still rejected.
                out.append(it.sceneBoundingRect().adjusted(3, 3, -3, -3))
                continue
            out.append(it.sceneBoundingRect().adjusted(-4, -4, 4, 4))
        return out

    def refresh(self):
        self.prepareGeometryChange()
        a = self.a_comp.pin_scene_pos(self.a_pin)
        b = self.b_comp.pin_scene_pos(self.b_pin)
        if self._manual_pts is None:
            a_dir = self.a_comp.pin_exit_direction(self.a_pin)
            b_dir = self.b_comp.pin_exit_direction(self.b_pin)
            pts, _, _ = orthogonal_route(a, a_dir, b, b_dir,
                                         mid_x=None, mid_y=None,
                                         blockers=self._blockers())
            self._pts = list(pts)
        else:
            # Pin endpoints may have moved (component dragged).  Update
            # the first/last vertex and re-orthogonalize the segments
            # that touch them.
            pts = list(self._manual_pts)
            pts[0] = a
            pts[-1] = b
            self._adjust_pin_segment(pts, 0, +1)
            self._adjust_pin_segment(pts, len(pts) - 1, -1)
            self._pts = pts
            self._manual_pts = list(pts)
        self._path = self._build_path(self._pts)

    @staticmethod
    def _adjust_pin_segment(pts: list[QPointF], pin_idx: int,
                            step: int) -> None:
        """Realign pts[pin_idx ± step] so the edge from the pin remains
        axis-aligned after the pin moved."""
        nbr = pin_idx + step
        if nbr < 0 or nbr >= len(pts):
            return
        p_pin = pts[pin_idx]
        p_nbr = pts[nbr]
        if _is_horizontal(p_pin, p_nbr) or _is_vertical(p_pin, p_nbr):
            return
        # Decide axis from the segment beyond nbr (if present), keeping
        # alternation; otherwise pick whichever displacement is larger.
        beyond = nbr + step
        if 0 <= beyond < len(pts):
            if _is_horizontal(pts[nbr], pts[beyond]):
                # outer is horizontal → make this segment vertical
                pts[nbr] = QPointF(p_pin.x(), p_nbr.y())
                return
            if _is_vertical(pts[nbr], pts[beyond]):
                pts[nbr] = QPointF(p_nbr.x(), p_pin.y())
                return
        # Fallback
        if abs(p_nbr.x() - p_pin.x()) >= abs(p_nbr.y() - p_pin.y()):
            pts[nbr] = QPointF(p_nbr.x(), p_pin.y())
        else:
            pts[nbr] = QPointF(p_pin.x(), p_nbr.y())

    @staticmethod
    def _build_path(pts: list[QPointF]) -> QPainterPath:
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        return path

    # ----------------------------------------------------------------
    # Slidable segments / handles
    # ----------------------------------------------------------------
    def _slidable_segments(self) -> list[int]:
        """Indices of every segment.  First/last touch a pin, but we
        still allow sliding by auto-inserting elbows that keep the pin
        endpoint anchored."""
        n = len(self._pts)
        if n < 2:
            return []
        return list(range(0, n - 1))

    def _handle_positions(self) -> list[tuple[int, QPointF]]:
        out = []
        for i in self._slidable_segments():
            p1, p2 = self._pts[i], self._pts[i + 1]
            # Skip degenerate (zero-length) segments
            if abs(p1.x() - p2.x()) < EPS and abs(p1.y() - p2.y()) < EPS:
                continue
            out.append((i, QPointF((p1.x() + p2.x()) / 2,
                                    (p1.y() + p2.y()) / 2)))
        return out

    def _handle_pos(self) -> QPointF:
        """Backwards-compat: representative handle position used by tests.
        Prefers a vertical bend (so `mid_x` overrides are reflected)."""
        for i, h in self._handle_positions():
            if _is_vertical(self._pts[i], self._pts[i + 1]):
                return h
        for i, h in self._handle_positions():
            if _is_horizontal(self._pts[i], self._pts[i + 1]):
                return h
        return QPointF()

    # ----------------------------------------------------------------
    # Sliding
    # ----------------------------------------------------------------
    def _slide_segment(self, i: int, scene_pos: QPointF) -> None:
        if self._manual_pts is None:
            self._manual_pts = list(self._pts)
        pts = self._manual_pts
        if i + 1 >= len(pts):
            return
        p1, p2 = pts[i], pts[i + 1]
        horizontal = _is_horizontal(p1, p2)
        vertical = _is_vertical(p1, p2)
        if not (horizontal or vertical):
            return

        # Decide whether we must insert an elbow on the "before" side:
        # - no previous vertex (segment touches pin), or
        # - previous segment lies on the same axis as the slid segment
        need_before = (i == 0)
        if not need_before:
            prev = pts[i - 1]
            if horizontal and _is_horizontal(prev, p1):
                need_before = True
            elif vertical and _is_vertical(prev, p1):
                need_before = True
        # Same on the "after" side
        need_after = (i + 2 >= len(pts))
        if not need_after:
            nxt = pts[i + 2]
            if horizontal and _is_horizontal(p2, nxt):
                need_after = True
            elif vertical and _is_vertical(p2, nxt):
                need_after = True

        if need_before:
            pts.insert(i, QPointF(p1.x(), p1.y()))
            i += 1  # the slid segment shifted right by one
        if need_after:
            pts.insert(i + 2, QPointF(pts[i + 1].x(), pts[i + 1].y()))

        if horizontal:
            new_y = round(scene_pos.y() / GRID) * GRID
            pts[i] = QPointF(pts[i].x(), new_y)
            pts[i + 1] = QPointF(pts[i + 1].x(), new_y)
        else:  # vertical
            new_x = round(scene_pos.x() / GRID) * GRID
            pts[i] = QPointF(new_x, pts[i].y())
            pts[i + 1] = QPointF(new_x, pts[i + 1].y())

        self._dragging_seg = i
        self._pts = list(pts)
        self.prepareGeometryChange()
        self._path = self._build_path(self._pts)
        self.update()

    # ----------------------------------------------------------------
    # Qt overrides
    # ----------------------------------------------------------------
    def boundingRect(self) -> QRectF:  # noqa: N802
        return self._path.boundingRect().adjusted(-HANDLE_SIZE, -HANDLE_SIZE,
                                                  HANDLE_SIZE, HANDLE_SIZE)

    def shape(self):  # noqa: N802
        stroker = QPainterPathStroker()
        stroker.setWidth(10)
        sh = stroker.createStroke(self._path)
        for _, h in self._handle_positions():
            sh.addRect(h.x() - HANDLE_SIZE, h.y() - HANDLE_SIZE,
                       HANDLE_SIZE * 2, HANDLE_SIZE * 2)
        return sh

    def paint(self, painter: QPainter, option, widget=None):
        if self.isSelected():
            pen = QPen(QColor("#ffffff"))
            pen.setWidth(3)
        else:
            pen = QPen(QColor("#88ff88"))
            pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPath(self._path)
        if self.isSelected():
            painter.setBrush(QBrush(QColor("#ffcc66")))
            painter.setPen(QPen(QColor("#000000")))
            for _, h in self._handle_positions():
                painter.drawRect(QRectF(h.x() - HANDLE_SIZE / 2,
                                        h.y() - HANDLE_SIZE / 2,
                                        HANDLE_SIZE, HANDLE_SIZE))

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            for idx, h in self._handle_positions():
                d2 = ((event.scenePos().x() - h.x()) ** 2
                      + (event.scenePos().y() - h.y()) ** 2)
                if d2 < (HANDLE_SIZE * 1.5) ** 2:
                    self._dragging_seg = idx
                    self.setSelected(True)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._dragging_seg is not None:
            self._slide_segment(self._dragging_seg, event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._dragging_seg is not None:
            self._dragging_seg = None
            scene = self.scene()
            if scene is not None and hasattr(scene, "_refresh_crossings"):
                scene._refresh_crossings()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # Backwards-compat shims (kept because older code/tests may still
    # reference the single-handle API)
    @property
    def mid_x(self) -> float | None:
        return None

    @mid_x.setter
    def mid_x(self, value):
        if value is None:
            return
        # Find the first vertical slidable segment and pin it to value
        for i in self._slidable_segments():
            if _is_vertical(self._pts[i], self._pts[i + 1]):
                if self._manual_pts is None:
                    self._manual_pts = list(self._pts)
                self._manual_pts[i] = QPointF(value, self._manual_pts[i].y())
                self._manual_pts[i + 1] = QPointF(value, self._manual_pts[i + 1].y())
                self.refresh()
                return

    @property
    def mid_y(self) -> float | None:
        return None

    @mid_y.setter
    def mid_y(self, value):
        if value is None:
            return
        for i in self._slidable_segments():
            if _is_horizontal(self._pts[i], self._pts[i + 1]):
                if self._manual_pts is None:
                    self._manual_pts = list(self._pts)
                self._manual_pts[i] = QPointF(self._manual_pts[i].x(), value)
                self._manual_pts[i + 1] = QPointF(self._manual_pts[i + 1].x(), value)
                self.refresh()
                return
