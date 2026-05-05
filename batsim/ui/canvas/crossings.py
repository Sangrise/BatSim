"""Wire-crossing visual indicators.

A single overlay graphics item that, after every graph change, scans all
wires for axis-aligned segment intersections and renders either:

  * a filled dot at the crossing — wires belong to the same electrical
    node (i.e., they are connected through pins/junctions/wires), or
  * a small "hop" arc on one wire — wires merely visually cross but are
    on different nodes (no electrical connection).

The overlay sits at a high zValue so dots/hops appear on top of wires
but below components.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QPointF, Qt
from PyQt6.QtGui import QPen, QBrush, QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QGraphicsItem


HOP_RADIUS = 6
DOT_RADIUS = 4


def _segments(wire) -> list[tuple[QPointF, QPointF]]:
    pts = [wire._path.elementAt(i) for i in range(wire._path.elementCount())]
    out = []
    for q1, q2 in zip(pts, pts[1:]):
        out.append((QPointF(q1.x, q1.y), QPointF(q2.x, q2.y)))
    return out


def _seg_cross(s1: tuple[QPointF, QPointF],
               s2: tuple[QPointF, QPointF]) -> QPointF | None:
    """Strict interior intersection of two axis-aligned segments."""
    a, b = s1
    c, d = s2
    horiz1 = abs(a.y() - b.y()) < 0.5
    vert1  = abs(a.x() - b.x()) < 0.5
    horiz2 = abs(c.y() - d.y()) < 0.5
    vert2  = abs(c.x() - d.x()) < 0.5
    if horiz1 and vert2:
        y = a.y(); x = c.x()
        x_lo, x_hi = sorted((a.x(), b.x()))
        y_lo, y_hi = sorted((c.y(), d.y()))
        if x_lo < x < x_hi and y_lo < y < y_hi:
            return QPointF(x, y)
    if vert1 and horiz2:
        x = a.x(); y = c.y()
        y_lo, y_hi = sorted((a.y(), b.y()))
        x_lo, x_hi = sorted((c.x(), d.x()))
        if y_lo < y < y_hi and x_lo < x < x_hi:
            return QPointF(x, y)
    return None


def _seg_overlap(s1: tuple[QPointF, QPointF],
                 s2: tuple[QPointF, QPointF]
                 ) -> tuple[QPointF, QPointF, str] | None:
    """If two axis-aligned segments are collinear and overlap (more than
    a single point), return the overlap endpoints and axis ('h'/'v').
    Used to flag two non-connected wires that visually share a stretch
    of pixels — they would otherwise look like a single continuous line.
    """
    a, b = s1
    c, d = s2
    horiz1 = abs(a.y() - b.y()) < 0.5
    horiz2 = abs(c.y() - d.y()) < 0.5
    vert1  = abs(a.x() - b.x()) < 0.5
    vert2  = abs(c.x() - d.x()) < 0.5
    if horiz1 and horiz2 and abs(a.y() - c.y()) < 0.5:
        x_lo = max(min(a.x(), b.x()), min(c.x(), d.x()))
        x_hi = min(max(a.x(), b.x()), max(c.x(), d.x()))
        if x_hi - x_lo > 1.5:
            y = a.y()
            return QPointF(x_lo, y), QPointF(x_hi, y), 'h'
    if vert1 and vert2 and abs(a.x() - c.x()) < 0.5:
        y_lo = max(min(a.y(), b.y()), min(c.y(), d.y()))
        y_hi = min(max(a.y(), b.y()), max(c.y(), d.y()))
        if y_hi - y_lo > 1.5:
            x = a.x()
            return QPointF(x, y_lo), QPointF(x, y_hi), 'v'
    return None


def _node_groups(scene) -> dict[tuple[int, int], int]:
    """Union-find on (id(wire), endpoint_index) → group id."""
    parent: dict[tuple, tuple] = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Build keyed by pin label
    for w in scene._wires:
        ka = (w.a_comp.cid, w.a_pin)
        kb = (w.b_comp.cid, w.b_pin)
        parent.setdefault(ka, ka); parent.setdefault(kb, kb)
        union(ka, kb)
    # Tap junctions union with their tap_pin
    for c in scene._components:
        if c.kind == "JUNCTION" and getattr(c, "tap_pin", None):
            kj = (c.cid, 0)
            try:
                tid, tp = c.tap_pin.split(".")
                kt = (tid, int(tp))
            except (ValueError, AttributeError):
                continue
            parent.setdefault(kj, kj); parent.setdefault(kt, kt)
            union(kj, kt)
    # Map wire → group root
    out: dict[int, tuple] = {}
    for w in scene._wires:
        out[id(w)] = find((w.a_comp.cid, w.a_pin))
    return out


class CrossingsOverlay(QGraphicsItem):
    def __init__(self, schematic_scene):
        super().__init__()
        self._scene = schematic_scene
        self._dots: list[QPointF] = []
        self._hops: list[tuple[QPointF, str]] = []  # (point, axis 'h'|'v')
        # Parallel-overlap "shift" markers — for two unconnected wires
        # that share a stretch along the same axis we mask the original
        # span and re-draw it offset by a few px so it reads as separate.
        self._shifts: list[tuple[QPointF, QPointF, str]] = []
        self._bbox = QRectF()
        self.setZValue(5)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def recompute(self) -> None:
        self.prepareGeometryChange()
        wires = list(self._scene._wires)
        groups = _node_groups(self._scene)
        # also: seen connected positions to avoid duplicating dots
        dots: set[tuple[int, int]] = set()
        hops: list[tuple[QPointF, str]] = []
        shifts: list[tuple[QPointF, QPointF, str]] = []
        bbox = QRectF()
        for i, w1 in enumerate(wires):
            segs1 = _segments(w1)
            g1 = groups.get(id(w1))
            for j in range(i + 1, len(wires)):
                w2 = wires[j]
                segs2 = _segments(w2)
                g2 = groups.get(id(w2))
                for s1 in segs1:
                    for s2 in segs2:
                        p = _seg_cross(s1, s2)
                        if p is not None:
                            key = (int(round(p.x())), int(round(p.y())))
                            if g1 == g2:
                                dots.add(key)
                            else:
                                axis = 'h' if abs(s2[0].y() - s2[1].y()) < 0.5 else 'v'
                                hops.append((p, axis))
                            bbox = bbox.united(QRectF(p.x() - 12, p.y() - 12,
                                                      24, 24))
                            continue
                        ov = _seg_overlap(s1, s2)
                        if ov is None:
                            continue
                        if g1 == g2:
                            # Same node and overlapping — already visually
                            # one line; nothing to draw.
                            continue
                        a, b, axis = ov
                        shifts.append((a, b, axis))
                        bbox = bbox.united(QRectF(a.x() - 8, a.y() - 8,
                                                  (b.x() - a.x()) + 16,
                                                  (b.y() - a.y()) + 16))
        self._dots = [QPointF(x, y) for (x, y) in dots]
        self._hops = hops
        self._shifts = shifts
        self._bbox = bbox

    # --- Qt overrides ---
    def boundingRect(self) -> QRectF:  # noqa: N802
        if self._bbox.isNull():
            return QRectF()
        return self._bbox

    def paint(self, painter: QPainter, option, widget=None):
        # Parallel-overlap shifts — mask the shared span then re-draw the
        # second wire offset by 6 px so the user sees two separate lines
        # instead of a single visually-merged line.
        if self._shifts:
            offset = 6.0
            for a, b, axis in self._shifts:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#181818")))  # scene bg
                if axis == 'h':
                    painter.drawRect(QRectF(a.x() - 1, a.y() - 2,
                                            (b.x() - a.x()) + 2, 4))
                else:
                    painter.drawRect(QRectF(a.x() - 2, a.y() - 1,
                                            4, (b.y() - a.y()) + 2))
                pen = QPen(QColor("#88ff88"))
                pen.setWidth(2)
                painter.setPen(pen)
                if axis == 'h':
                    y = a.y() + offset
                    painter.drawLine(int(a.x()), int(a.y()), int(a.x()), int(y))
                    painter.drawLine(int(a.x()), int(y), int(b.x()), int(y))
                    painter.drawLine(int(b.x()), int(y), int(b.x()), int(b.y()))
                else:
                    x = a.x() + offset
                    painter.drawLine(int(a.x()), int(a.y()), int(x), int(a.y()))
                    painter.drawLine(int(x), int(a.y()), int(x), int(b.y()))
                    painter.drawLine(int(x), int(b.y()), int(b.x()), int(b.y()))
        # Dots — same node intersections
        if self._dots:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#88ff88")))
            for p in self._dots:
                painter.drawEllipse(p, DOT_RADIUS, DOT_RADIUS)
        # Hops — different nodes, draw an arc that "jumps over"
        if self._hops:
            # Mask the underlying *hopping* wire with two background-color
            # rectangles, one on each side of the crossed wire.  Leaving a
            # 3 px gap centred on the crossing means the perpendicular
            # (crossed) wire stays continuous and only the hopping wire is
            # erased to make room for the arc.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#1e1e1e")))  # scene bg
            GAP = 3.0  # half-width of the protected band for the crossed wire
            STRIP = 3.0  # width of the strip that erases the hopping wire
            for p, axis in self._hops:
                if axis == 'h':
                    # Hopping wire is horizontal -> erase left/right of (p.x())
                    painter.drawRect(QRectF(p.x() - HOP_RADIUS - 1,
                                            p.y() - STRIP / 2,
                                            (HOP_RADIUS + 1) - GAP,
                                            STRIP))
                    painter.drawRect(QRectF(p.x() + GAP,
                                            p.y() - STRIP / 2,
                                            (HOP_RADIUS + 1) - GAP,
                                            STRIP))
                else:
                    # Hopping wire is vertical -> erase above/below p.y()
                    painter.drawRect(QRectF(p.x() - STRIP / 2,
                                            p.y() - HOP_RADIUS - 1,
                                            STRIP,
                                            (HOP_RADIUS + 1) - GAP))
                    painter.drawRect(QRectF(p.x() - STRIP / 2,
                                            p.y() + GAP,
                                            STRIP,
                                            (HOP_RADIUS + 1) - GAP))
            # Then draw the arc on top.
            pen = QPen(QColor("#88ff88"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for p, axis in self._hops:
                rect = QRectF(p.x() - HOP_RADIUS, p.y() - HOP_RADIUS,
                              HOP_RADIUS * 2, HOP_RADIUS * 2)
                if axis == 'h':
                    painter.drawArc(rect, 0, 180 * 16)  # arch upward
                else:
                    painter.drawArc(rect, 90 * 16, 180 * 16)  # arch leftward
