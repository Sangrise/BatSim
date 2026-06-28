"""Pure-function orthogonal wire routing.

Given two pins (with their outward exit directions) returns a list of points
forming a Manhattan-style wire that:

  * always exits each pin in its outward direction (a stub of length STUB),
  * tries a 3-segment Z-route between the stub ends,
  * falls back to a 5-segment U-route around any component bounding boxes,
  * accepts an optional user override for the bend coordinate.

This module is pure (no Qt widgets) so both `WireItem` and the schematic
scene preview can share it without circular imports.
"""
from __future__ import annotations

from typing import Iterable
import heapq

from PyQt6.QtCore import QPointF, QRectF


STUB = 20
GRID = 20


# --- helpers ----------------------------------------------------------------
def _snap_dir(d: QPointF | None) -> QPointF | None:
    if d is None:
        return None
    if abs(d.x()) >= abs(d.y()) and d.x() != 0:
        return QPointF(1.0 if d.x() > 0 else -1.0, 0.0)
    if d.y() != 0:
        return QPointF(0.0, 1.0 if d.y() > 0 else -1.0)
    return None


def _seg_in_rect(p1: QPointF, p2: QPointF, r: QRectF) -> bool:
    """True if axis-aligned segment p1-p2 cuts through the *interior* of r."""
    x1, y1, x2, y2 = p1.x(), p1.y(), p2.x(), p2.y()
    if y1 == y2:
        xa, xb = sorted((x1, x2))
        return (r.top() < y1 < r.bottom()
                and xb > r.left() and xa < r.right())
    if x1 == x2:
        ya, yb = sorted((y1, y2))
        return (r.left() < x1 < r.right()
                and yb > r.top() and ya < r.bottom())
    return False


def _path_hits(pts: list[QPointF], blockers: Iterable[QRectF]) -> bool:
    for r in blockers:
        for p1, p2 in zip(pts, pts[1:]):
            if _seg_in_rect(p1, p2, r):
                return True
    return False


def _try_z_x(a, a2, b, b2, mx, blockers):
    z = _dedupe([a, a2, QPointF(mx, a2.y()),
                 QPointF(mx, b2.y()), b2, b])
    return z if not _path_hits(z, blockers) else None


def _try_z_y(a, a2, b, b2, my, blockers):
    z = _dedupe([a, a2, QPointF(a2.x(), my),
                 QPointF(b2.x(), my), b2, b])
    return z if not _path_hits(z, blockers) else None


def _candidate_lanes(lo: float, hi: float,
                     blockers: list[QRectF],
                     axis: str) -> list[float]:
    """Generate candidate lane coordinates that clear every blocker.

    `axis='x'` returns x-coords (vertical lanes between blockers);
    `axis='y'` returns y-coords (horizontal lanes between blockers)."""
    base = (lo + hi) / 2
    cands = [base]
    for r in blockers:
        if axis == 'x':
            cands.append(r.left() - GRID)
            cands.append(r.right() + GRID)
        else:
            cands.append(r.top() - GRID)
            cands.append(r.bottom() + GRID)
    if blockers:
        if axis == 'x':
            cands.append(min(r.left() for r in blockers) - GRID)
            cands.append(max(r.right() for r in blockers) + GRID)
        else:
            cands.append(min(r.top() for r in blockers) - GRID)
            cands.append(max(r.bottom() for r in blockers) + GRID)
    cands.sort(key=lambda v: abs(v - base))
    seen = []
    for c in cands:
        if all(abs(c - s) > 1e-3 for s in seen):
            seen.append(c)
    return seen


def _dedupe(pts: list[QPointF]) -> list[QPointF]:
    out = [pts[0]]
    for p in pts[1:]:
        if p.x() != out[-1].x() or p.y() != out[-1].y():
            out.append(p)
    return out


def _dir_ok(start: float, lane: float, sign: float | None) -> bool:
    if sign is None:
        return True
    return lane >= start if sign > 0 else lane <= start


def _try_dogleg_x(a: QPointF, a2: QPointF, a_dir: QPointF | None,
                  b: QPointF, b2: QPointF, b_dir: QPointF | None,
                  blockers: list[QRectF]) -> tuple[list[QPointF], str, QPointF] | None:
    """Search a wider horizontal-exit route.

    Shape: pin -> a2 -> x1 -> y -> x2 -> b2 -> pin.  This avoids the
    common failure mode where the simple U-route's vertical segment at
    ``a2.x`` or ``b2.x`` passes through a nearby component.
    """
    x_lanes = _candidate_lanes(min(a2.x(), b2.x()), max(a2.x(), b2.x()),
                              blockers, 'x')
    y_lanes = _candidate_lanes(min(a2.y(), b2.y()), max(a2.y(), b2.y()),
                              blockers, 'y')
    a_sign = a_dir.x() if a_dir is not None and a_dir.x() != 0 else None
    b_sign = b_dir.x() if b_dir is not None and b_dir.x() != 0 else None
    for y in y_lanes:
        for x1 in x_lanes:
            if not _dir_ok(a2.x(), x1, a_sign):
                continue
            for x2 in x_lanes:
                if not _dir_ok(b2.x(), x2, b_sign):
                    continue
                pts = _dedupe([a, a2, QPointF(x1, a2.y()),
                               QPointF(x1, y), QPointF(x2, y),
                               QPointF(x2, b2.y()), b2, b])
                if not _path_hits(pts, blockers):
                    return pts, 'y', QPointF((x1 + x2) / 2, y)
    return None


def _try_dogleg_y(a: QPointF, a2: QPointF, a_dir: QPointF | None,
                  b: QPointF, b2: QPointF, b_dir: QPointF | None,
                  blockers: list[QRectF]) -> tuple[list[QPointF], str, QPointF] | None:
    y_lanes = _candidate_lanes(min(a2.y(), b2.y()), max(a2.y(), b2.y()),
                              blockers, 'y')
    x_lanes = _candidate_lanes(min(a2.x(), b2.x()), max(a2.x(), b2.x()),
                              blockers, 'x')
    a_sign = a_dir.y() if a_dir is not None and a_dir.y() != 0 else None
    b_sign = b_dir.y() if b_dir is not None and b_dir.y() != 0 else None
    for x in x_lanes:
        for y1 in y_lanes:
            if not _dir_ok(a2.y(), y1, a_sign):
                continue
            for y2 in y_lanes:
                if not _dir_ok(b2.y(), y2, b_sign):
                    continue
                pts = _dedupe([a, a2, QPointF(a2.x(), y1),
                               QPointF(x, y1), QPointF(x, y2),
                               QPointF(b2.x(), y2), b2, b])
                if not _path_hits(pts, blockers):
                    return pts, 'x', QPointF(x, (y1 + y2) / 2)
    return None


def _try_grid_route(a: QPointF, a2: QPointF, b: QPointF, b2: QPointF,
                    blockers: list[QRectF]) -> tuple[list[QPointF], str, QPointF] | None:
    xs = {a2.x(), b2.x()}
    ys = {a2.y(), b2.y()}
    for r in blockers:
        xs.update((r.left() - GRID, r.right() + GRID))
        ys.update((r.top() - GRID, r.bottom() + GRID))
    x_list = sorted(xs)
    y_list = sorted(ys)
    nodes = [(x, y) for x in x_list for y in y_list]
    start = (a2.x(), a2.y())
    goal = (b2.x(), b2.y())
    nodes_set = set(nodes)
    nodes_set.add(start)
    nodes_set.add(goal)

    def clear(p: tuple[float, float], q: tuple[float, float]) -> bool:
        return not _path_hits([QPointF(*p), QPointF(*q)], blockers)

    by_y: dict[float, list[float]] = {}
    by_x: dict[float, list[float]] = {}
    for x, y in nodes_set:
        by_y.setdefault(y, []).append(x)
        by_x.setdefault(x, []).append(y)
    for values in by_y.values():
        values.sort()
    for values in by_x.values():
        values.sort()

    def neighbours(node: tuple[float, float]):
        x, y = node
        xs_here = by_y[y]
        ix = xs_here.index(x)
        for j in (ix - 1, ix + 1):
            if 0 <= j < len(xs_here):
                nxt = (xs_here[j], y)
                if clear(node, nxt):
                    yield nxt
        ys_here = by_x[x]
        iy = ys_here.index(y)
        for j in (iy - 1, iy + 1):
            if 0 <= j < len(ys_here):
                nxt = (x, ys_here[j])
                if clear(node, nxt):
                    yield nxt

    pq: list[tuple[float, tuple[float, float]]] = [(0.0, start)]
    dist = {start: 0.0}
    prev: dict[tuple[float, float], tuple[float, float]] = {}
    while pq:
        _, node = heapq.heappop(pq)
        if node == goal:
            break
        for nxt in neighbours(node):
            cost = dist[node] + abs(nxt[0] - node[0]) + abs(nxt[1] - node[1])
            if cost < dist.get(nxt, float("inf")):
                dist[nxt] = cost
                prev[nxt] = node
                heuristic = abs(goal[0] - nxt[0]) + abs(goal[1] - nxt[1])
                heapq.heappush(pq, (cost + heuristic, nxt))
    if goal not in dist:
        return None
    rev = [goal]
    while rev[-1] != start:
        rev.append(prev[rev[-1]])
    rev.reverse()
    mid = [QPointF(x, y) for x, y in rev]
    pts = _dedupe([a] + mid + [b])
    if _path_hits(pts, blockers):
        return None
    # Use the middle segment as a stable handle hint.
    if len(mid) >= 2:
        p1 = mid[len(mid) // 2 - 1]
        p2 = mid[len(mid) // 2]
        axis = 'x' if p1.x() == p2.x() else 'y'
        handle = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
    else:
        axis = 'x'
        handle = QPointF((a2.x() + b2.x()) / 2, (a2.y() + b2.y()) / 2)
    return pts, axis, handle


def _safe_y(a2: QPointF, b2: QPointF,
            blockers: list[QRectF]) -> float:
    """Pick a Y for the U-route detour that clears all overlapping blockers."""
    x_lo, x_hi = sorted((a2.x(), b2.x()))
    bs = [r for r in blockers if r.right() > x_lo and r.left() < x_hi]
    base = (a2.y() + b2.y()) / 2
    if not bs:
        return base
    above = min(r.top() for r in bs) - GRID
    below = max(r.bottom() for r in bs) + GRID
    return above if abs(above - base) < abs(below - base) else below


def _safe_x(a2: QPointF, b2: QPointF,
            blockers: list[QRectF]) -> float:
    y_lo, y_hi = sorted((a2.y(), b2.y()))
    bs = [r for r in blockers if r.bottom() > y_lo and r.top() < y_hi]
    base = (a2.x() + b2.x()) / 2
    if not bs:
        return base
    right = max(r.right() for r in bs) + GRID
    left = min(r.left() for r in bs) - GRID
    return right if abs(right - base) < abs(left - base) else left


def _constrained_mid(natural: float,
                     constraints: list[tuple[str, float]]) -> float | None:
    lo = max((v for op, v in constraints if op == '>='), default=None)
    hi = min((v for op, v in constraints if op == '<='), default=None)
    if lo is not None and hi is not None and lo > hi:
        return None
    if lo is not None and natural < lo:
        return lo
    if hi is not None and natural > hi:
        return hi
    return natural


# --- public API -------------------------------------------------------------
def orthogonal_route(a: QPointF, a_dir: QPointF | None,
                     b: QPointF, b_dir: QPointF | None,
                     mid_x: float | None = None,
                     mid_y: float | None = None,
                     blockers: list[QRectF] | None = None
                     ) -> tuple[list[QPointF], str, QPointF]:
    """Compute the polyline (point list), bend axis ('x' or 'y') and a
    suggested handle position for an orthogonal wire from pin a to pin b."""
    a_dir = _snap_dir(a_dir)
    b_dir = _snap_dir(b_dir)
    blockers = list(blockers or [])

    a2 = QPointF(a.x() + (a_dir.x() * STUB if a_dir else 0),
                 a.y() + (a_dir.y() * STUB if a_dir else 0))
    b2 = QPointF(b.x() + (b_dir.x() * STUB if b_dir else 0),
                 b.y() + (b_dir.y() * STUB if b_dir else 0))

    a_horiz = a_dir is not None and abs(a_dir.x()) > 0
    b_horiz = b_dir is not None and abs(b_dir.x()) > 0
    # Decide bend axis from a's pin orientation; if a is free (no dir),
    # follow b instead; if both free, fall back to x-bend.
    if a_dir is None:
        bend_x = b_horiz or b_dir is None
    else:
        bend_x = a_horiz

    if bend_x:
        if mid_x is not None:
            mx = mid_x
            z = _try_z_x(a, a2, b, b2, mx, blockers)
            if z is not None:
                return z, 'x', QPointF(mx, (a2.y() + b2.y()) / 2)
            # User override collides — fall through to auto search.
        # Z-route attempt at natural midpoint
        if abs(a2.y() - b2.y()) > 0.5:
            cstr = []
            if a_dir is not None and a_dir.x() != 0:
                cstr.append(('>=' if a_dir.x() > 0 else '<=', a2.x()))
            if b_dir is not None and b_dir.x() != 0:
                cstr.append(('>=' if b_dir.x() > 0 else '<=', b2.x()))
            mx_nat = _constrained_mid((a2.x() + b2.x()) / 2, cstr)
            if mx_nat is not None:
                z = _try_z_x(a, a2, b, b2, mx_nat, blockers)
                if z is not None:
                    return z, 'x', QPointF(mx_nat, (a2.y() + b2.y()) / 2)
            # Try alternative vertical lanes that clear blockers.
            for cand in _candidate_lanes(min(a2.x(), b2.x()),
                                         max(a2.x(), b2.x()),
                                         blockers, 'x'):
                z = _try_z_x(a, a2, b, b2, cand, blockers)
                if z is not None:
                    return z, 'x', QPointF(cand, (a2.y() + b2.y()) / 2)
        # Direct H line if same y and clear
        if abs(a2.y() - b2.y()) <= 0.5:
            line = _dedupe([a, a2, b2, b])
            if not _path_hits(line, blockers):
                return line, 'x', QPointF((a2.x() + b2.x()) / 2, a2.y())
        # U-route detour — search horizontal lanes that clear all blockers.
        for cand in _candidate_lanes(min(a2.y(), b2.y()),
                                     max(a2.y(), b2.y()),
                                     blockers, 'y'):
            u = _dedupe([a, a2, QPointF(a2.x(), cand),
                         QPointF(b2.x(), cand), b2, b])
            if not _path_hits(u, blockers):
                return u, 'y', QPointF((a2.x() + b2.x()) / 2, cand)
        dogleg = _try_dogleg_x(a, a2, a_dir, b, b2, b_dir, blockers)
        if dogleg is not None:
            return dogleg
        grid = _try_grid_route(a, a2, b, b2, blockers)
        if grid is not None:
            return grid
        # Last resort: original heuristic (no validation).
        y = _safe_y(a2, b2, blockers)
        u = _dedupe([a, a2, QPointF(a2.x(), y),
                     QPointF(b2.x(), y), b2, b])
        return u, 'y', QPointF((a2.x() + b2.x()) / 2, y)

    # bend_y
    if mid_y is not None:
        my = mid_y
        z = _try_z_y(a, a2, b, b2, my, blockers)
        if z is not None:
            return z, 'y', QPointF((a2.x() + b2.x()) / 2, my)
        # fall through
    if abs(a2.x() - b2.x()) > 0.5:
        cstr = []
        if a_dir is not None and a_dir.y() != 0:
            cstr.append(('>=' if a_dir.y() > 0 else '<=', a2.y()))
        if b_dir is not None and b_dir.y() != 0:
            cstr.append(('>=' if b_dir.y() > 0 else '<=', b2.y()))
        my_nat = _constrained_mid((a2.y() + b2.y()) / 2, cstr)
        if my_nat is not None:
            z = _try_z_y(a, a2, b, b2, my_nat, blockers)
            if z is not None:
                return z, 'y', QPointF((a2.x() + b2.x()) / 2, my_nat)
        for cand in _candidate_lanes(min(a2.y(), b2.y()),
                                     max(a2.y(), b2.y()),
                                     blockers, 'y'):
            z = _try_z_y(a, a2, b, b2, cand, blockers)
            if z is not None:
                return z, 'y', QPointF((a2.x() + b2.x()) / 2, cand)
    if abs(a2.x() - b2.x()) <= 0.5:
        line = _dedupe([a, a2, b2, b])
        if not _path_hits(line, blockers):
            return line, 'y', QPointF(a2.x(), (a2.y() + b2.y()) / 2)
    for cand in _candidate_lanes(min(a2.x(), b2.x()),
                                 max(a2.x(), b2.x()),
                                 blockers, 'x'):
        u = _dedupe([a, a2, QPointF(cand, a2.y()),
                     QPointF(cand, b2.y()), b2, b])
        if not _path_hits(u, blockers):
            return u, 'x', QPointF(cand, (a2.y() + b2.y()) / 2)
    dogleg = _try_dogleg_y(a, a2, a_dir, b, b2, b_dir, blockers)
    if dogleg is not None:
        return dogleg
    grid = _try_grid_route(a, a2, b, b2, blockers)
    if grid is not None:
        return grid
    x = _safe_x(a2, b2, blockers)
    u = _dedupe([a, a2, QPointF(x, a2.y()),
                 QPointF(x, b2.y()), b2, b])
    return u, 'x', QPointF(x, (a2.y() + b2.y()) / 2)
