"""Drawing canvas with grid, snapping, selection, node editing, Bézier paths, undo and a preview mode. Units are microns."""

from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QAbstractSpinBox,
    QLineEdit,
    QMenu,
    QStyle,
    QStyleOptionGraphicsItem,
)

from shapely.ops import unary_union

from laserscan.booleans import subtract
from laserscan.planning import Segment, format_path, parse_contours, parse_shape, region_polygons

ACCENT = QColor("#f5b800")
INK = QColor("#0b0b0b")
RED = QColor("#c0392b")
NODE = QColor("#1f6feb")
FILL = QColor(245, 184, 0, 70)
NODE_TYPES = ("sharp", "free", "smooth", "symmetric")
GHOST_PX = 16
CLOSED = ("rect", "circle", "polygon")
CURVED = ("polyline", "polygon")
TOOLS = ("select", "pen")
MODES = ("design", "preview", "monitor")
MIN_NODES = {"polyline": 2, "polygon": 3}
KAPPA = 0.5522847498
PICK_PX = 8
GRID_PX = 12
ZOOM_RANGE = (1e-4, 200.0)
SCENE_LIMIT = 5e5


def _pen(color: QColor, width: float = 0, style=Qt.SolidLine) -> QPen:
    pen = QPen(color, width, style)
    pen.setCosmetic(True)
    return pen


def _path(arrays) -> QPainterPath:
    path = QPainterPath()
    for points in arrays:
        path.addPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in points]))
    return path


def _plain(option: QStyleOptionGraphicsItem) -> QStyleOptionGraphicsItem:
    """Return ``option`` without the selected flag, so Qt does not draw its dashed selection box."""
    option = QStyleOptionGraphicsItem(option)
    option.state = option.state & ~QStyle.State_Selected
    return option


def _dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _bezier(p: list[QPointF], t: float) -> QPointF:
    u = 1 - t
    return p[0] * (u**3) + p[1] * (3 * u * u * t) + p[2] * (3 * u * t * t) + p[3] * (t**3)


def _split(p: list[QPointF], t: float) -> tuple[list[QPointF], list[QPointF]]:
    """De Casteljau split of a cubic into the control points of its left and right halves."""

    def mix(a: QPointF, b: QPointF) -> QPointF:
        return a + (b - a) * t

    a, b, c = mix(p[0], p[1]), mix(p[1], p[2]), mix(p[2], p[3])
    d, e = mix(a, b), mix(b, c)
    m = mix(d, e)
    return [p[0], a, d, m], [m, e, c, p[3]]


def _scene_path(item: ShapeItem) -> QPainterPath:
    path = item.mapToScene(item.path())
    path.setFillRule(Qt.WindingFill)
    return path


def _nest(outlines: list) -> list[list]:
    """Group outlines into ``[outer, hole, hole, ...]`` by even-odd nesting; each outline is ``(points, hin, hout)``."""
    paths = [Contour(*o).path(True) for o in outlines]
    area = [p.boundingRect().width() * p.boundingRect().height() for p in paths]
    inside = [[j for j in range(len(paths)) if j != i and paths[j].contains(paths[i])] for i in range(len(paths))]
    groups = {i: [outlines[i]] for i, parents in enumerate(inside) if len(parents) % 2 == 0}
    for i, parents in enumerate(inside):
        if len(parents) % 2 == 1:
            owner = min((j for j in parents if len(inside[j]) == len(parents) - 1), key=lambda j: area[j])
            groups[owner].append(outlines[i])
    return list(groups.values())


class Contour:
    """One outline of a shape: anchors with Bézier handles and node types."""

    def __init__(self, points, hin=None, hout=None, types=None) -> None:
        self.points = [QPointF(p) for p in points]
        self.hin = [None if q is None else QPointF(q) for q in hin or []]
        self.hout = [None if q is None else QPointF(q) for q in hout or []]
        self.types = list(types or [])

    def fit(self) -> None:
        """Pad or trim the handle and type lists to the number of points."""
        n = len(self.points)
        for handles in (self.hin, self.hout):
            del handles[n:]
            handles.extend([None] * (n - len(handles)))
        del self.types[n:]
        self.types.extend(["free"] * (n - len(self.types)))

    def derive_types(self) -> None:
        """Classify every node from its handles: symmetric, smooth (aligned), free or sharp (no handles)."""
        self.fit()
        for i, p in enumerate(self.points):
            a, b = self.hin[i], self.hout[i]
            if a is None and b is None:
                self.types[i] = "sharp"
            elif a is None or b is None:
                self.types[i] = "free"
            else:
                u, v = a - p, b - p
                lu, lv = math.hypot(u.x(), u.y()), math.hypot(v.x(), v.y())
                aligned = lu > 0 and lv > 0 and abs(u.x() * v.y() - u.y() * v.x()) <= 1e-3 * lu * lv
                aligned = aligned and u.x() * v.x() + u.y() * v.y() < 0
                self.types[i] = ("symmetric" if abs(lu - lv) <= 1e-3 * max(lu, lv) else "smooth") if aligned else "free"

    def path(self, closed: bool) -> QPainterPath:
        """The outline as a Qt path."""
        path, p, n = QPainterPath(), self.points, len(self.points)
        path.moveTo(p[0])
        for i in range(n if closed else n - 1):
            j = (i + 1) % n
            a, b = self.hout[i], self.hin[j]
            if a is not None or b is not None:
                path.cubicTo(a if a is not None else p[i], b if b is not None else p[j], p[j])
            elif j != 0:
                path.lineTo(p[j])
        if closed:
            path.closeSubpath()
        return path

    def copy(self) -> Contour:
        return Contour(self.points, self.hin, self.hout, self.types)


def _contour_attr(name: str) -> property:
    """A ShapeItem attribute that reads and writes the active contour, so node code works on one outline."""
    return property(
        lambda self: getattr(self.contours[self.active], name),
        lambda self, value: setattr(self.contours[self.active], name, value),
    )


class Handle(QGraphicsRectItem):
    """Node of the shape being edited; drag to move, click or rubber-band to select."""

    def __init__(self, shape: ShapeItem, index: int) -> None:
        super().__init__(-4, -4, 8, 8, shape)
        self.shape_item, self.index, self.syncing = shape, index, False
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIgnoresTransformations
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setBrush(Qt.white)
        self.setPen(QPen(NODE, 1.5))
        self.setZValue(2)

    def paint(self, painter, option, widget=None) -> None:
        super().paint(painter, _plain(option), widget)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.setBrush(NODE if value else Qt.white)
        elif not self.syncing:
            canvas = self.shape_item.canvas
            if change == QGraphicsItem.ItemPositionChange and len(canvas.scene_.selectedItems()) <= 1:
                origin = self.shape_item.pos()
                return canvas.snap(value + origin, {self.shape_item}) - origin
            if change == QGraphicsItem.ItemPositionHasChanged:
                self.shape_item.move_node(self.index, QPointF(value))
        return super().itemChange(change, value)


class Control(QGraphicsEllipseItem):
    """Bézier handle of a selected node. ``side`` is ``in`` or ``out``.

    It takes no mouse events itself: :class:`Canvas` drags it, so Qt neither
    moves the selected nodes along with it nor changes the selection.
    """

    def __init__(self, shape: ShapeItem, index: int, side: str) -> None:
        super().__init__(-4.5, -4.5, 9, 9, shape)
        self.shape_item, self.index, self.side, self.paired = shape, index, side, False
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setPen(QPen(NODE, 1.5))
        self.setZValue(3)
        self.set_ghost(True)

    def set_ghost(self, ghost: bool) -> None:
        """A ghost marks a retracted handle: drag it away from the node to pull out a curve."""
        self.setBrush(Qt.white if ghost else NODE)

    def begin(self, alt: bool) -> None:
        """Start a drag. Smooth and symmetric nodes move both handles together; Alt frees the node."""
        shape = self.shape_item
        if alt and shape.types[self.index] in ("smooth", "symmetric"):
            shape.types[self.index] = "free"
        self.paired = shape.types[self.index] in ("smooth", "symmetric")


class ShapeItem(QGraphicsPathItem):
    """An editable shape defined by its vertices.

    Attributes:
        kind: One of ``rect``, ``circle`` (two opposite bounding-box corners),
            ``line``, ``polyline`` or ``polygon``.
        points: Vertices in microns.
        hin: Incoming Bézier handle of each vertex (polyline / polygon only), or ``None``.
        hout: Outgoing Bézier handle of each vertex, or ``None``.
        op: ``add`` or ``subtract``; only closed shapes use it.
    """

    def __init__(
        self,
        kind: str,
        points: list[QPointF],
        canvas: Canvas,
        op: str = "add",
        hin: list[QPointF | None] | None = None,
        hout: list[QPointF | None] | None = None,
    ) -> None:
        super().__init__()
        self.kind, self.canvas = kind, canvas
        self.contours = [Contour(points, hin, hout)]
        self.active = 0
        self.handles: list[Handle] = []
        self.controls: dict[tuple[int, str], Control] = {}
        self.guides = QGraphicsPathItem(self)
        self.guides.setPen(_pen(NODE))
        self.guides.setZValue(1.5)
        self.guides.setAcceptedMouseButtons(Qt.NoButton)
        self.baking = False
        self.setFlags(
            QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(1)
        self.op = "add"
        self.set_op(op)
        self.update_path()

    points = _contour_attr("points")
    hin = _contour_attr("hin")
    hout = _contour_attr("hout")
    types = _contour_attr("types")

    def all_points(self) -> list[QPointF]:
        """Anchors of every contour."""
        return [p for c in self.contours for p in c.points]

    def set_active(self, index: int) -> None:
        """Choose which contour (outline or hole) the node editing acts on."""
        if index != self.active and 0 <= index < len(self.contours):
            self.active = index
            self.clear_handles()

    def contour_at(self, point: QPointF, tolerance: float) -> int | None:
        """Index of the contour whose outline is within ``tolerance`` of ``point``, ignoring the active one."""
        stroker = QPainterPathStroker()
        stroker.setWidth(2 * tolerance)
        hits = [
            k
            for k, c in enumerate(self.contours)
            if stroker.createStroke(c.path(k > 0 or self.kind == "polygon")).contains(point)
        ]
        return None if not hits or self.active in hits else hits[0]

    def set_op(self, op: str) -> None:
        """Set ``add`` or ``subtract`` and restyle; open shapes always stay ``add``.

        The filled area comes from the canvas region, not from the shape: a
        subtracting shape only shows its dashed outline.
        """
        self.op = op if self.kind in CLOSED else "add"
        subtract = self.op == "subtract"
        self.setPen(_pen(RED if subtract else INK, 0, Qt.DashLine if subtract else Qt.SolidLine))
        self.setBrush(Qt.NoBrush)

    def set_interactive(self, on: bool) -> None:
        """Allow or forbid selecting and moving the whole shape (off while another shape is edited)."""
        self.setFlag(QGraphicsItem.ItemIsSelectable, on)
        self.setFlag(QGraphicsItem.ItemIsMovable, on)

    def _fit(self) -> None:
        for contour in self.contours:
            contour.fit()

    def derive_types(self) -> None:
        """Classify the nodes of every contour from their handles."""
        for contour in self.contours:
            contour.derive_types()

    def update_path(self) -> None:
        """Rebuild the outline from ``points`` and the Bézier handles."""
        self.prepareGeometryChange()
        self._fit()
        path = QPainterPath()
        p = self.points
        if self.kind == "rect":
            path.addRect(QRectF(p[0], p[1]).normalized())
        elif self.kind == "circle":
            path.addEllipse(QRectF(p[0], p[1]).normalized())
        else:
            for k, contour in enumerate(self.contours):
                path.addPath(contour.path(k > 0 or self.kind == "polygon"))
        self.setPath(path)
        if not self.baking and self in self.canvas._shapes:
            self.canvas.update_region()

    # -- nodes ---------------------------------------------------------------

    def _discard(self, item: QGraphicsItem) -> None:
        """Remove a child item without letting its selection change re-enter the canvas."""
        if item.scene() is not None:
            before, self.canvas._quiet = self.canvas._quiet, True
            try:
                item.scene().removeItem(item)
            finally:
                self.canvas._quiet = before

    def place_handles(self) -> None:
        """Create, move or remove the node handles; they exist only while this shape is being edited."""
        count = len(self.points) if self.canvas.editing is self else 0
        while len(self.handles) > count:
            self._discard(self.handles.pop())
        while len(self.handles) < count:
            self.handles.append(Handle(self, len(self.handles)))
        for handle, point in zip(self.handles, self.points):
            handle.syncing = True
            handle.setPos(point)
            handle.syncing = False
        self.place_controls()

    def clear_handles(self) -> None:
        """Remove every node handle (indices changed) and rebuild them."""
        while self.handles:
            self._discard(self.handles.pop())
        self.place_handles()

    def selected_nodes(self) -> list[int]:
        """Indices of the selected nodes."""
        return [h.index for h in self.handles if h.isSelected()]

    def place_controls(self) -> None:
        """Show both Bézier handles of the selected nodes, with guide lines.

        A missing handle is drawn as a hollow ghost a few pixels from the node, toward its neighbour.
        """
        self._fit()
        wanted: dict[tuple[int, str], tuple[QPointF, bool]] = {}
        if self.canvas.editing is self and self.kind in CURVED:
            n, closed = len(self.points), self.kind == "polygon"
            for i in self.selected_nodes():
                for side, handles, j, exists in (
                    ("in", self.hin, i - 1, closed or i > 0),
                    ("out", self.hout, i + 1, closed or i < n - 1),
                ):
                    if not exists:
                        continue
                    if handles[i] is not None:
                        wanted[(i, side)] = (handles[i], False)
                        continue
                    toward = self.points[j % n] - self.points[i]
                    norm = math.hypot(toward.x(), toward.y()) or 1.0
                    wanted[(i, side)] = (self.points[i] + toward * (GHOST_PX / self.canvas.zoom / norm), True)
        if set(wanted) != set(self.controls):
            for control in self.controls.values():
                self._discard(control)
            self.controls = {key: Control(self, *key) for key in wanted}
        guides = QPainterPath()
        for (i, side), (point, ghost) in wanted.items():
            control = self.controls[(i, side)]
            control.syncing = True
            control.setPos(point)
            control.syncing = False
            control.set_ghost(ghost)
            guides.moveTo(self.points[i])
            guides.lineTo(point)
        self.guides.setPath(guides)

    def move_node(self, i: int, point: QPointF) -> None:
        """Move node ``i`` and its handles to ``point``."""
        delta = point - self.points[i]
        self.points[i] = point
        for handles in (self.hin, self.hout):
            if handles[i] is not None:
                handles[i] = handles[i] + delta
        self.update_path()
        self.place_controls()

    def move_control(self, i: int, side: str, point: QPointF, paired: bool) -> None:
        """Move a Bézier handle.

        A sharp node becomes free. With ``paired`` (smooth or symmetric node) the
        other handle is moved too: opposite direction, and the same length for
        symmetric nodes or its own length for smooth nodes.
        """
        mine, other = (self.hin, self.hout) if side == "in" else (self.hout, self.hin)
        mine[i] = point
        if self.types[i] == "sharp":
            self.types[i] = "free"
        if paired:
            anchor, away = self.points[i], point - self.points[i]
            length = math.hypot(away.x(), away.y())
            if length > 0:
                reach = length if self.types[i] == "symmetric" or other[i] is None else _dist(other[i], anchor)
                other[i] = anchor - away * (reach / length)
        self.update_path()
        self.place_controls()

    def set_type(self, kind: str, indices: list[int]) -> None:
        """Set the type of nodes.

        ``sharp`` removes the handles, ``free`` keeps them independent,
        ``smooth`` aligns them on one line and ``symmetric`` also equalizes
        their length. Nodes without handles get ones aimed along the line
        between their neighbours.
        """
        n, closed = len(self.points), self.kind == "polygon"
        for i in indices:
            here = self.points[i]
            if kind == "sharp":
                self.hin[i] = self.hout[i] = None
            elif kind in ("smooth", "symmetric"):
                prev = self.points[(i - 1) % n] if closed or i > 0 else None
                nxt = self.points[(i + 1) % n] if closed or i < n - 1 else None
                a, b = self.hin[i], self.hout[i]
                if a is not None and b is not None:
                    tangent = b - a
                elif a is not None or b is not None:
                    tangent = (b - here) if b is not None else (here - a)
                else:
                    tangent = (nxt or here) - (prev or here)
                norm = math.hypot(tangent.x(), tangent.y())
                if norm > 0:
                    tangent = tangent / norm
                    out_len = _dist(b, here) if b is not None else (_dist(nxt, here) / 3 if nxt is not None else None)
                    in_len = _dist(a, here) if a is not None else (_dist(prev, here) / 3 if prev is not None else None)
                    if kind == "symmetric" and out_len is not None and in_len is not None:
                        out_len = in_len = (out_len + in_len) / 2
                    if out_len is not None:
                        self.hout[i] = here + tangent * out_len
                    if in_len is not None:
                        self.hin[i] = here - tangent * in_len
            self.types[i] = kind
        self.update_path()
        self.place_controls()

    def delete_nodes(self, indices: list[int]) -> bool:
        """Delete nodes; returns ``False`` and changes nothing if too few would remain."""
        if len(self.points) - len(set(indices)) < MIN_NODES.get(self.kind, 2):
            return False
        for i in sorted(set(indices), reverse=True):
            for items in (self.points, self.hin, self.hout, self.types):
                del items[i]
        self.update_path()
        self.clear_handles()
        return True

    def extrude(self, indices: list[int]) -> list[int]:
        """Add a new node at the position of each given node and return the new indices.

        On an open path the first node is extended backwards, any other node forwards.
        """
        closed, chosen = self.kind == "polygon", set(indices)
        out: list[list] = []
        new: list[int] = []

        def spawn(p: QPointF) -> None:
            new.append(len(out))
            out.append([QPointF(p), None, None, "sharp"])

        for i, p in enumerate(self.points):
            if i in chosen and not closed and i == 0:
                spawn(p)
            out.append([p, self.hin[i], self.hout[i], self.types[i]])
            if i in chosen and (closed or i > 0):
                spawn(p)
        self.points = [o[0] for o in out]
        self.hin, self.hout, self.types = [o[1] for o in out], [o[2] for o in out], [o[3] for o in out]
        self.update_path()
        self.clear_handles()
        return new

    def insert_node(self, point: QPointF, tolerance: float) -> int | None:
        """Insert a node on the segment nearest to ``point``, keeping curves unchanged.

        Returns:
            The new node's index, or ``None`` if no segment is within ``tolerance``.
        """
        n, p = len(self.points), self.points
        best: tuple[float, int, int, float] | None = None
        for i in range(n if self.kind == "polygon" else n - 1):
            j = (i + 1) % n
            a, b = self.hout[i], self.hin[j]
            if a is None and b is None:
                d = p[j] - p[i]
                span = d.x() ** 2 + d.y() ** 2
                t = 0.0 if span == 0 else max(0.0, min(1.0, ((point - p[i]).x() * d.x() + (point - p[i]).y() * d.y()) / span))
                at = lambda t, i=i, d=d: p[i] + d * t  # noqa: E731
            else:
                ctrl = [p[i], a if a is not None else p[i], b if b is not None else p[j], p[j]]
                t = min((k / 64 for k in range(65)), key=lambda t, c=ctrl: _dist(_bezier(c, t), point))
                lo, hi = max(0.0, t - 1 / 64), min(1.0, t + 1 / 64)
                for _ in range(24):
                    m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
                    if _dist(_bezier(ctrl, m1), point) < _dist(_bezier(ctrl, m2), point):
                        hi = m2
                    else:
                        lo = m1
                t = (lo + hi) / 2
                at = lambda t, c=ctrl: _bezier(c, t)  # noqa: E731
            dist = _dist(at(t), point)
            if best is None or dist < best[0]:
                best = (dist, i, j, t)
        if best is None or best[0] > tolerance:
            return None
        _dist_, i, j, t = best
        a, b = self.hout[i], self.hin[j]
        if a is None and b is None:
            anchor, new_in, new_out = p[i] + (p[j] - p[i]) * t, None, None
        else:
            left, right = _split([p[i], a if a is not None else p[i], b if b is not None else p[j], p[j]], t)
            anchor, new_in, new_out = left[3], left[2], right[1]
            self.hout[i], self.hin[j] = left[1], right[2]
        self.points.insert(i + 1, anchor)
        self.hin.insert(i + 1, new_in)
        self.hout.insert(i + 1, new_out)
        self.types.insert(i + 1, "free" if new_in is None else "smooth")
        self.update_path()
        self.clear_handles()
        return i + 1

    def convert(self) -> tuple | None:
        """Turn a rectangle, ellipse or line into an equal node path so its nodes can be edited.

        Returns:
            A token for :meth:`restore`, or ``None`` if the shape already is a path.
        """
        if self.kind in CURVED:
            return None
        token = (self.kind, [QPointF(q) for q in self.points])
        p = self.points
        if self.kind == "rect":
            r = QRectF(p[0], p[1]).normalized()
            self.points = [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
            self.hin, self.hout, self.kind = [], [], "polygon"
        elif self.kind == "circle":
            r = QRectF(p[0], p[1]).normalized()
            c, rx, ry, k = r.center(), r.width() / 2, r.height() / 2, KAPPA
            at = lambda x, y: QPointF(c.x() + x * rx, c.y() + y * ry)  # noqa: E731
            self.points = [at(1, 0), at(0, 1), at(-1, 0), at(0, -1)]
            self.hin = [at(1, -k), at(k, 1), at(-1, k), at(-k, -1)]
            self.hout = [at(1, k), at(-k, 1), at(-1, -k), at(k, -1)]
            self.kind = "polygon"
        else:
            self.hin, self.hout, self.kind = [], [], "polyline"
        self.derive_types()
        self.update_path()
        return token

    def restore(self, token: tuple) -> None:
        """Undo :meth:`convert`."""
        self.kind, self.points = token[0], [QPointF(q) for q in token[1]]
        self.hin, self.hout, self.types = [], [], []
        self.set_op(self.op)
        self.update_path()

    # -- Qt ------------------------------------------------------------------

    def bake(self) -> None:
        """Fold the item offset into ``points`` and handles."""
        offset = self.pos()
        for c in self.contours:
            c.points = [p + offset for p in c.points]
            c.hin = [None if q is None else q + offset for q in c.hin]
            c.hout = [None if q is None else q + offset for q in c.hout]
        self.baking = True
        self.setPos(0, 0)
        self.baking = False
        self.update_path()

    def paint(self, painter, option, widget=None) -> None:
        super().paint(painter, _plain(option), widget)
        if self.isSelected():
            painter.setPen(_pen(NODE, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path())

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(PICK_PX / self.canvas.zoom)
        outline = stroker.createStroke(self.path())
        return outline.united(self.path()) if self.kind in CLOSED else outline

    def boundingRect(self) -> QRectF:
        margin = PICK_PX / self.canvas.zoom
        return self.shape().boundingRect().adjusted(-margin, -margin, margin, margin)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None and not self.baking:
            moving = set(self.scene().selectedItems())
            first = self.points[0]
            return self.canvas.snap(first + value, moving) - first
        if change == QGraphicsItem.ItemPositionHasChanged and not self.baking:
            self.canvas.update_region()
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.update()
        return super().itemChange(change, value)

    def to_dict(self) -> dict:
        """Return the shape as a ``planning.parse_shape`` dictionary."""
        off = self.pos()
        p = [q + off for q in self.points]
        if self.kind in ("rect", "circle", "line"):
            out = {"type": self.kind, "x0": p[0].x(), "y0": p[0].y(), "x1": p[1].x(), "y1": p[1].y()}
        else:

            def xy(q: QPointF | None):
                return None if q is None else (q.x() + off.x(), q.y() + off.y())

            out = {"type": "path", "path": ""}
            for k, c in enumerate(self.contours):
                nodes = [((q.x() + off.x(), q.y() + off.y()), xy(a), xy(b)) for q, a, b in zip(c.points, c.hin, c.hout)]
                out["path"] += format_path(nodes, k > 0 or self.kind == "polygon")
        if self.kind in CLOSED:
            out["op"] = self.op
        return out


class Canvas(QGraphicsView):
    """Scene view with a design mode and a read-only preview / monitor mode.

    In ``design`` mode shapes are drawn in coordinates relative to the starting
    stage position (the origin). The filled (yellow) area is the combined scan
    region: added shapes minus subtracted shapes. Design mode has two
    sub-modes, like Blender: *object* mode selects and moves whole shapes, and
    *edit* mode (:meth:`enter_edit`) edits the nodes and Bézier handles of one
    shape. In ``preview`` and ``monitor`` mode the scan path, the stage range
    and the stage position are shown in absolute stage coordinates.

    Signals:
        changed: The set of shapes changed (draw, edit, delete, undo or redo).
        cursorMoved: Cursor position in microns (x, y).
        toolChanged: The active tool name changed.
        editChanged: Edit mode was entered (``True``) or left (``False``).
        message: A short notice for the user.
    """

    changed = Signal()
    cursorMoved = Signal(float, float)
    toolChanged = Signal(str)
    editChanged = Signal(bool)
    message = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.scene_ = QGraphicsScene(self)
        self.scene_.setSceneRect(-SCENE_LIMIT, -SCENE_LIMIT, 2 * SCENE_LIMIT, 2 * SCENE_LIMIT)
        self.setScene(self.scene_)
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(120)
        self.snap_on, self.tool, self.mode, self.new_op = True, "select", "design", "add"
        self.stage = QRectF(0, 0, 114000, 75000)
        self._shapes: list[ShapeItem] = []
        self._draft: ShapeItem | None = None
        self.editing: ShapeItem | None = None
        self._edit_token: tuple | None = None
        self._edit_start: dict | None = None
        self._pen_drag: int | None = None
        self._control: tuple[Control, QPointF] | None = None
        self._xform: dict | None = None
        self._loading = False
        self._quiet = False
        self._region = QGraphicsPathItem()
        self._region.setPen(Qt.NoPen)
        self._region.setBrush(FILL)
        self._region.setZValue(0.5)
        self._region.setAcceptedMouseButtons(Qt.NoButton)
        self.scene_.addItem(self._region)
        self._preview: list[QGraphicsItem] = []
        self._bounds = QRectF()
        self._exceeds = False
        self._pan: QPointF | None = None
        self._history: list[list[dict]] = [[]]
        self._index = 0
        self._progress = QGraphicsPathItem()
        self._progress_path = QPainterPath()
        self._progress_at = (0, -1)
        self._indicator = self._ring(INK, 12)
        self._marker = QGraphicsPathItem(self._cross())
        self._marker.setPen(QPen(ACCENT, 3))
        self._marker.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self._marker.setZValue(3)
        for item in (self._indicator, self._marker):
            item.setVisible(False)
            self.scene_.addItem(item)
        self.scene_.selectionChanged.connect(self._sync_handles)
        self._fitted = False
        self.set_mode("design")

    @staticmethod
    def _cross() -> QPainterPath:
        cross = QPainterPath()
        cross.moveTo(-9, 0), cross.lineTo(9, 0), cross.moveTo(0, -9), cross.lineTo(0, 9)
        return cross

    @staticmethod
    def _ring(color: QColor, size: int) -> QGraphicsEllipseItem:
        ring = QGraphicsEllipseItem(-size / 2, -size / 2, size, size)
        ring.setPen(QPen(color, 2))
        ring.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        ring.setZValue(4)
        return ring

    @property
    def zoom(self) -> float:
        """Pixels per micron."""
        return abs(self.transform().m11()) or 1.0

    @property
    def grid_step(self) -> float:
        """Grid spacing in microns: 1, 2, 5, 10, ... chosen so lines are at least ``GRID_PX`` apart."""
        target = GRID_PX / self.zoom
        exponent = math.floor(math.log10(target))
        for factor in (1, 2, 5, 10):
            if factor * 10.0**exponent >= target:
                return max(1.0, factor * 10.0**exponent)
        return 1.0

    def set_mode(self, mode: str) -> None:
        """Switch between ``design``, ``preview`` and ``monitor`` and fit the view.

        Args:
            mode: One of ``MODES``.
        """
        self._cancel_draft()
        self.exit_edit()
        self.mode = mode
        design = mode == "design"
        self._region.setVisible(design)
        for item in self._shapes:
            item.setVisible(design)
        for item in self._preview:
            item.setVisible(not design)
        self._marker.setVisible(not design and self._marker.data(0) is True)
        self._indicator.setVisible(False)
        self.scene_.clearSelection()
        self._apply_tool()
        self.fit()

    def set_stage(self, stage: QRectF) -> None:
        """Set the absolute stage range shown in preview and monitor mode."""
        self.stage = QRectF(stage)
        self.viewport().update()

    def fit(self) -> None:
        """Fit the view to the shapes (design) or to the path and, if it leaves it, the stage range."""
        if self.mode == "design":
            xs = [0.0] + [p.x() for item in self._shapes for p in item.all_points()]
            ys = [0.0] + [p.y() for item in self._shapes for p in item.all_points()]
            rect = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
            if not self._shapes:
                rect = QRectF(-500, -325, 1000, 650)
        else:
            rect = QRectF(self._bounds) if not self._bounds.isNull() else QRectF(self.stage)
            if self._exceeds:
                rect = rect.united(self.stage)
        self._fit_rect(rect)

    def fit_stage(self) -> None:
        """Fit the view to the whole stage range."""
        self._fit_rect(self.stage)

    def _fit_rect(self, rect: QRectF) -> None:
        width, height = max(rect.width(), 20.0), max(rect.height(), 20.0)
        scale = 0.88 * min(self.viewport().width() / width, self.viewport().height() / height)
        scale = min(max(scale, ZOOM_RANGE[0]), ZOOM_RANGE[1])
        self.setTransform(QTransform.fromScale(scale, -scale))
        self.centerOn(rect.center())
        self._refresh_items()

    def set_tool(self, tool: str) -> None:
        """Activate a drawing tool and cancel any unfinished shape.

        Args:
            tool: One of ``TOOLS``.
        """
        if tool != "select":
            self.exit_edit()
        self.tool = tool
        self._apply_tool()
        self.toolChanged.emit(tool)

    def _apply_tool(self) -> None:
        self._cancel_draft()
        drawing = self.mode == "design" and self.tool != "select"
        if self.mode == "design":
            self.setDragMode(QGraphicsView.NoDrag if drawing else QGraphicsView.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setCursor(Qt.CrossCursor if drawing else Qt.ArrowCursor)
        self._indicator.setVisible(False)

    def set_new_op(self, op: str) -> None:
        """Set how newly drawn closed shapes act.

        Args:
            op: ``add`` or ``subtract`` to add or remove area, or ``merge`` to
                add area and fuse the shape with every added shape it touches.
        """
        self.new_op = op

    def apply_op(self, op: str) -> None:
        """Set the operation of the selected closed shapes."""
        for item in self.selected_shapes():
            item.set_op(op)
        self._commit()

    def selected_shapes(self) -> list[ShapeItem]:
        """Return the shape being edited, or else the selected shapes."""
        if self.editing is not None:
            return [self.editing]
        return [i for i in self.scene_.selectedItems() if isinstance(i, ShapeItem)]

    def shapes(self) -> list[dict]:
        """Return all shapes as dictionaries understood by ``planning.parse_shape``."""
        return [s.to_dict() for s in self._shapes]

    def set_shapes(self, shapes: list[dict], record: bool = True) -> None:
        """Replace all shapes.

        Args:
            shapes: Shape dictionaries.
            record: Whether to add the change to the undo history.
        """
        self._cancel_draft()
        self._drop_edit()
        self._loading = self._quiet = True
        for item in self._shapes:
            self.scene_.removeItem(item)
        self._shapes = []
        self._quiet = False
        for d in shapes:
            hin = hout = None
            holes: list[Contour] = []
            if d["type"] == "path":
                contours = parse_contours(d["path"])
                if not contours:
                    continue
                nodes, closed = contours[0]
                pts = [QPointF(*a) for a, _i, _o in nodes]
                hin = [None if i is None else QPointF(*i) for _a, i, _o in nodes]
                hout = [None if o is None else QPointF(*o) for _a, _i, o in nodes]
                kind = "polygon" if closed and len(nodes) >= 3 else "polyline"
                if kind == "polygon":
                    for hole, hole_closed in contours[1:]:
                        if hole_closed and len(hole) >= 3:
                            holes.append(
                                Contour(
                                    [QPointF(*a) for a, _i, _o in hole],
                                    [None if i is None else QPointF(*i) for _a, i, _o in hole],
                                    [None if o is None else QPointF(*o) for _a, _i, o in hole],
                                )
                            )
            else:
                kind, pts = d["type"], [QPointF(d["x0"], d["y0"]), QPointF(d["x1"], d["y1"])]
            item = self._add(kind, pts, d.get("op", "add"), hin, hout)
            item.contours += holes
            item.update_path()
            item.convert()  # rectangles, ellipses and lines from older files become node paths
            item.derive_types()
            item.setVisible(self.mode == "design")
        self._loading = False
        self.update_region()
        if record:
            self._commit()

    def set_preview(
        self,
        plan: list[Segment],
        polygons: list,
        origin: tuple[float, float],
        flags: list[bool],
    ) -> None:
        """Show the scan path in absolute coordinates.

        Args:
            plan: Scan segments in absolute microns.
            polygons: Shapely polygons of the scan region in absolute microns.
            origin: Absolute stage position the scan starts from.
            flags: Per-segment flag, true if the segment leaves the stage range.
        """
        for item in self._preview:
            self.scene_.removeItem(item)
        self._preview = []
        visible = self.mode != "design"
        region = QPainterPath()
        region.setFillRule(Qt.OddEvenFill)
        for poly in polygons:
            for ring in (poly.exterior, *poly.interiors):
                region.addPolygon(QPolygonF([QPointF(x, y) for x, y in ring.coords]))
        here, transit = origin, []
        for seg in plan:
            transit.append([here, tuple(seg.points[0])])
            here = tuple(seg.points[-1])
        good = [s.points for s, bad in zip(plan, flags) if not bad]
        bad = [s.points for s, bad in zip(plan, flags) if bad]
        layers = (
            (region, None, QColor(245, 184, 0, 45), 0.2),
            (_path(transit), _pen(QColor("#8a8f98"), 0, Qt.DotLine), None, 0.5),
            (_path(good), _pen(INK), None, 0.6),
            (_path(bad), _pen(RED, 2), None, 0.7),
        )
        for path, pen, brush, z in layers:
            item = QGraphicsPathItem(path)
            item.setPen(pen or Qt.NoPen)
            if brush is not None:
                item.setBrush(brush)
            item.setZValue(z)
            item.setAcceptedMouseButtons(Qt.NoButton)
            self._preview.append(item)
        start = self._ring(INK, 14)
        start.setPos(*origin)
        self._progress = QGraphicsPathItem()
        self._progress.setPen(_pen(ACCENT, 3))
        self._progress.setZValue(0.9)
        self._progress_path, self._progress_at = QPainterPath(), (0, -1)
        self._preview += [start, self._progress]
        for item in self._preview:
            item.setVisible(visible)
            self.scene_.addItem(item)
        pts = [p for s in plan for p in (s.points.min(axis=0), s.points.max(axis=0))] + [origin]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self._bounds = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
        self._exceeds = any(flags)

    def set_progress(self, plan: list[Segment], seg: int, pt: int) -> None:
        """Draw the path up to point ``pt`` of segment ``seg`` in the accent colour (monitor mode)."""
        i, j = self._progress_at
        while (i, j) != (seg, pt) and i < len(plan):
            if j + 1 < len(plan[i].points):
                j += 1
                x, y = plan[i].points[j]
                if j > 0 and plan[i].laser:
                    self._progress_path.lineTo(x, y)
                else:
                    self._progress_path.moveTo(x, y)
            else:
                i, j = i + 1, -1
        self._progress_at = (i, j)
        self._progress.setPath(self._progress_path)

    def set_marker(self, position: tuple[float, float] | None) -> None:
        """Move the stage position marker (absolute microns); ``None`` hides it."""
        self._marker.setData(0, position is not None)
        self._marker.setVisible(position is not None and self.mode != "design")
        if position is not None:
            self._marker.setPos(*position)

    def snap(self, point: QPointF, exclude: set[ShapeItem] = frozenset()) -> QPointF:
        """Snap a point to a nearby vertex or the grid.

        Args:
            point: Point in microns.
            exclude: Shapes whose vertices are not snap targets.

        Returns:
            The snapped point, or ``point`` itself if snapping is off.
        """
        if not self.snap_on:
            return QPointF(point)
        reach = PICK_PX * 2 / self.zoom
        best = min(
            (q for s in self._shapes if s not in exclude and s is not self._draft for q in s.all_points()),
            key=lambda q: math.hypot(q.x() - point.x(), q.y() - point.y()),
            default=None,
        )
        if best is not None and math.hypot(best.x() - point.x(), best.y() - point.y()) <= reach:
            return QPointF(best)
        step = self.grid_step
        return QPointF(round(point.x() / step) * step, round(point.y() / step) * step)

    def undo(self) -> None:
        """Undo the last shape change."""
        if self.mode == "design" and self._index > 0:
            self._index -= 1
            self._restore_history()

    def redo(self) -> None:
        """Redo the last undone shape change."""
        if self.mode == "design" and self._index < len(self._history) - 1:
            self._index += 1
            self._restore_history()

    def _restore_history(self) -> None:
        editing = self._shapes.index(self.editing) if self.editing in self._shapes else None
        self.set_shapes(self._history[self._index], record=False)
        if editing is not None and editing < len(self._shapes):
            self._shapes[editing].setSelected(True)
            self.enter_edit()
        self.changed.emit()

    def delete_selected(self) -> None:
        """Delete the selected shapes, or in edit mode the selected nodes."""
        if self.mode != "design" or self._xform is not None:
            return
        if self.editing is not None:
            nodes = self.editing.selected_nodes()
            if nodes and not self.editing.delete_nodes(nodes):
                self.message.emit(
                    f"A {self.editing.kind} needs at least {MIN_NODES[self.editing.kind]} nodes. "
                    "Leave Edit mode (Tab) to delete the whole shape."
                )
            self._commit()
            return
        for item in self.selected_shapes():
            self._shapes.remove(item)
            self.scene_.removeItem(item)
        self._commit()

    def select_all(self) -> None:
        """Select every shape, or in edit mode every node."""
        if self.mode != "design":
            return
        for item in self.editing.handles if self.editing is not None else self._shapes:
            item.setSelected(True)

    def toggle_edit(self) -> None:
        """Enter edit mode for the selected shape, or leave it."""
        self.exit_edit() if self.editing is not None else self.enter_edit()

    def enter_edit(self) -> bool:
        """Edit the nodes of the one selected shape.

        Rectangles, ellipses and lines become node paths; they turn back if
        nothing was changed. Returns whether edit mode is active.
        """
        if self.mode != "design" or self._draft is not None or self._xform is not None:
            return False
        if self.editing is not None:
            return True
        chosen = self.selected_shapes()
        if len(chosen) != 1:
            self.message.emit("Select one shape first, then press Tab to edit its nodes.")
            return False
        self.set_tool("select")
        item = chosen[0]
        self._edit_token = item.convert()
        self._edit_start = item.to_dict()
        self.editing = item
        self.scene_.clearSelection()
        for shape in self._shapes:
            shape.set_interactive(False)
            shape.setOpacity(1.0 if shape is item else 0.35)
        item.place_handles()
        self.editChanged.emit(True)
        return True

    def exit_edit(self) -> None:
        """Leave edit mode and select the edited shape again."""
        item = self.editing
        if item is None:
            return
        self.editing = None
        item.place_handles()
        item.active = 0
        self.scene_.clearSelection()
        if self._edit_token is not None and item.to_dict() == self._edit_start:
            item.restore(self._edit_token)
        for shape in self._shapes:
            shape.set_interactive(True)
            shape.setOpacity(1.0)
        item.setSelected(True)
        self._edit_token = None
        self._commit()
        self.editChanged.emit(False)

    def _drop_edit(self) -> None:
        item = self.editing
        if item is not None:
            self.editing, self._edit_token = None, None
            item.place_handles()  # removes the node handles and Bézier handles
            item.active = 0
            self.editChanged.emit(False)

    def set_node_type(self, kind: str) -> None:
        """Set the type of the selected nodes: ``sharp``, ``free``, ``smooth`` or ``symmetric``."""
        item = self.editing
        if item is None:
            return
        nodes = item.selected_nodes()
        if not nodes:
            self.message.emit("Select one or more nodes first.")
            return
        item.set_type(kind, nodes)
        self._commit()

    def apply_subtract(self) -> None:
        """Cut Subtract shapes into the Add shapes they touch, so the new edges become real nodes.

        Curves stay curves when skia-python is installed. Uses the selected
        Subtract shapes, or all of them if none is selected. A cut that leaves a
        hole makes it an extra contour of the shape; click its edge in Edit mode
        to edit it.
        """
        if self.mode != "design":
            return
        self.exit_edit()
        cutters = [s for s in self.selected_shapes() if s.op == "subtract"] or [
            s for s in self._shapes if s.op == "subtract"
        ]
        if not cutters:
            self.message.emit("No Subtract shape to apply.")
            return
        fresh = []
        for cutter in cutters:
            blade = _scene_path(cutter)
            pieces = [
                (s, subtract(_scene_path(s), blade))
                for s in self._shapes
                if s is not cutter and s.kind in CLOSED and s.op == "add" and _scene_path(s).intersects(blade)
            ]
            for s, parts in pieces:
                self._shapes.remove(s)
                self.scene_.removeItem(s)
                for outline, *holes in _nest(parts):
                    item = self._add("polygon", outline[0], "add", outline[1], outline[2])
                    item.contours += [Contour(*h) for h in holes]
                    item.update_path()
                    item.derive_types()
                    fresh.append(item)
            self._shapes.remove(cutter)
            self.scene_.removeItem(cutter)
        self.scene_.clearSelection()
        for item in fresh:
            item.setSelected(True)
        self._commit()

    # -- Blender-style selection and modal transforms -------------------------

    def deselect_all(self) -> None:
        """Deselect every shape, or in edit mode every node."""
        self.scene_.clearSelection()

    def invert_selection(self) -> None:
        """Invert the selection of shapes, or in edit mode of nodes."""
        if self.mode == "design":
            for item in self.editing.handles if self.editing is not None else self._shapes:
                item.setSelected(not item.isSelected())

    def pick_tool(self) -> None:
        """Switch between the Select and Bézier pen tools."""
        if self.mode == "design":
            self.set_tool("pen" if self.tool == "select" else "select")

    def duplicate(self) -> None:
        """Copy the selected shapes and start moving the copies."""
        chosen = self.selected_shapes()
        if self.mode != "design" or self.editing is not None or self._xform or not chosen:
            return
        self.scene_.clearSelection()
        for item in chosen:
            copy = self._add(item.kind, item.points, item.op, item.hin, item.hout)
            copy.contours = [c.copy() for c in item.contours]
            copy.update_path()
            copy.derive_types()
            copy.setSelected(True)
        self._commit()
        self.start_transform("grab")

    def type_menu(self) -> None:
        """Pop up the node type menu at the cursor (edit mode)."""
        if self.editing is None or self._xform is not None:
            return
        menu = QMenu(self)
        for kind in NODE_TYPES:
            menu.addAction(kind.capitalize(), lambda k=kind: self.set_node_type(k))
        menu.exec(QCursor.pos())

    @property
    def transforming(self) -> bool:
        """Whether a grab / rotate / scale is in progress."""
        return self._xform is not None

    def _cursor_scene(self) -> QPointF:
        return self.mapToScene(self.mapFromGlobal(QCursor.pos()))

    def extrude(self) -> None:
        """Duplicate the selected nodes next to themselves and start moving the new ones (edit mode).

        On an open path this extends it from its end node. Cancelling removes the new nodes again.
        """
        item = self.editing
        if item is None or self._xform is not None:
            return
        nodes = item.selected_nodes()
        if not nodes:
            self.message.emit("Select one or more nodes to extrude.")
            return
        new = item.extrude(nodes)
        self.scene_.clearSelection()
        for i in new:
            item.handles[i].setSelected(True)
        self.start_transform("grab", extrude=True)

    def start_transform(self, mode: str, extrude: bool = False) -> None:
        """Start moving (``grab``), ``rotate`` or ``scale`` the selected shapes or, in edit mode, nodes.

        The mouse drives it; click or Enter confirms, Esc or right-click cancels,
        X / Y lock an axis (grab and scale).
        """
        if self.mode != "design" or self._xform is not None or self._draft is not None:
            return
        if self.editing is not None:
            nodes = self.editing.selected_nodes()
            targets = [(self.editing, self.editing.active, nodes)] if nodes else []
        else:
            targets = [
                (s, k, list(range(len(c.points)))) for s in self.selected_shapes() for k, c in enumerate(s.contours)
            ]
        if not targets:
            self.message.emit("Select something first.")
            return
        items = [
            (s, k, idx, ([QPointF(p) for p in s.contours[k].points], list(s.contours[k].hin), list(s.contours[k].hout)))
            for s, k, idx in targets
        ]
        anchors = [saved[0][i] for _s, _k, idx, saved in items for i in idx]
        pivot = QPointF(sum(p.x() for p in anchors) / len(anchors), sum(p.y() for p in anchors) / len(anchors))
        self._xform = {
            "mode": mode,
            "items": items,
            "pivot": pivot,
            "start": self._cursor_scene(),
            "probe": anchors[0],
            "axis": None,
            "extrude": extrude,
        }
        self.message.emit(
            {"grab": "Grab", "rotate": "Rotate", "scale": "Scale"}[mode]
            + ": move the mouse, click or Enter to confirm, Esc or right-click to cancel, X / Y to lock an axis."
        )

    def set_axis(self, axis: str) -> None:
        """Lock the running transform to ``x`` or ``y``; pressing the same key again unlocks."""
        if self._xform is not None:
            self._xform["axis"] = None if self._xform["axis"] == axis else axis
            self._update_transform(self._cursor_scene())

    def _update_transform(self, cursor: QPointF) -> None:
        x = self._xform
        pivot, start, axis = x["pivot"], x["start"], x["axis"]
        if x["mode"] == "grab":
            delta = cursor - start
            if self.snap_on:
                moving = {s for s, *_rest in x["items"]}
                delta = self.snap(x["probe"] + delta, moving) - x["probe"]
            if axis == "x":
                delta.setY(0)
            elif axis == "y":
                delta.setX(0)

            def move(p: QPointF) -> QPointF:
                return p + delta

        elif x["mode"] == "scale":
            r0, r1 = _dist(start, pivot), _dist(cursor, pivot)
            k = r1 / r0 if r0 > 1e-9 else 1.0
            kx, ky = (1.0 if axis == "y" else k), (1.0 if axis == "x" else k)

            def move(p: QPointF) -> QPointF:
                return QPointF(pivot.x() + (p.x() - pivot.x()) * kx, pivot.y() + (p.y() - pivot.y()) * ky)

        else:
            turn = math.atan2(cursor.y() - pivot.y(), cursor.x() - pivot.x()) - math.atan2(
                start.y() - pivot.y(), start.x() - pivot.x()
            )
            cos, sin = math.cos(turn), math.sin(turn)

            def move(p: QPointF) -> QPointF:
                dx, dy = p.x() - pivot.x(), p.y() - pivot.y()
                return QPointF(pivot.x() + dx * cos - dy * sin, pivot.y() + dx * sin + dy * cos)

        for shape, k, indices, (points, hin, hout) in x["items"]:
            c = shape.contours[k]
            for i in indices:
                c.points[i] = move(points[i])
                c.hin[i] = None if hin[i] is None else move(hin[i])
                c.hout[i] = None if hout[i] is None else move(hout[i])
            shape.update_path()
            shape.place_handles()

    def finish_transform(self, confirm: bool) -> None:
        """Confirm or cancel the running transform."""
        x, self._xform = self._xform, None
        if x is None:
            return
        if not confirm and x["extrude"]:
            self._restore_history()  # drop the uncommitted new nodes
            return
        if not confirm:
            for shape, k, indices, (points, hin, hout) in x["items"]:
                c = shape.contours[k]
                for i in indices:
                    c.points[i], c.hin[i], c.hout[i] = points[i], hin[i], hout[i]
                shape.update_path()
                shape.place_handles()
        self._commit()

    def update_region(self) -> None:
        """Redraw the yellow scan region: added shapes minus subtracted shapes."""
        if self._loading:
            return
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for poly in region_polygons([s.to_dict() for s in self._shapes]):
            for ring in (poly.exterior, *poly.interiors):
                path.addPolygon(QPolygonF([QPointF(x, y) for x, y in ring.coords]))
        self._region.setPath(path)

    def _add(
        self,
        kind: str,
        points: list[QPointF],
        op: str = "add",
        hin: list[QPointF | None] | None = None,
        hout: list[QPointF | None] | None = None,
    ) -> ShapeItem:
        item = ShapeItem(kind, points, self, op, hin, hout)
        self.scene_.addItem(item)
        item.place_handles()
        self._shapes.append(item)
        return item

    def _commit(self) -> None:
        self.update_region()
        now = self.shapes()
        if now != self._history[self._index]:
            self._history = self._history[: self._index + 1] + [now]
            self._index += 1
            self.changed.emit()

    def _sync_handles(self) -> None:
        if self._quiet:
            return
        for item in self._shapes:
            item.place_handles()

    def _refresh_items(self) -> None:
        for item in self._shapes:
            item.prepareGeometryChange()
        if self.editing is not None:
            self.editing.place_controls()
        self.viewport().update()

    def _cancel_draft(self) -> None:
        if self._draft is not None:
            self.scene_.removeItem(self._draft)
            self._draft = None

    def _finish_draft(self, trailing: bool = True) -> None:
        """Finish the shape being drawn; ``trailing`` drops the point that follows the cursor."""
        draft, self._draft = self._draft, None
        self._pen_drag = None
        if draft is None:
            return
        if trailing and draft.kind in CURVED:
            draft.points.pop()
        if len(draft.points) < (3 if draft.kind == "polygon" else 2) or (
            draft.kind in ("rect", "circle", "line") and draft.points[0] == draft.points[1]
        ):
            self.scene_.removeItem(draft)
            return
        draft.set_op(draft.op)
        draft.derive_types()
        draft.update_path()
        self._shapes.append(draft)
        if self.new_op == "merge" and draft.kind in CLOSED:
            self._merge(draft)
        self._commit()
        # Next step of the workflow: set node types and handles in Edit mode.
        if draft in self._shapes:
            self.scene_.clearSelection()
            draft.setSelected(True)
        self.set_tool("select")
        if len(self.selected_shapes()) == 1:
            self.enter_edit()

    def _merge(self, item: ShapeItem) -> None:
        """Fuse ``item`` with every added closed shape it touches into one polygon."""
        touched = [
            (s, g)
            for s in self._shapes
            if s is not item and s.kind in CLOSED and s.op == "add"
            for g in [parse_shape(s.to_dict())]
            if g is not None and g.intersects(parse_shape(item.to_dict()))
        ]
        if not touched:
            return
        union = unary_union([parse_shape(item.to_dict())] + [g for _s, g in touched])
        if union.geom_type != "Polygon" or list(union.interiors):
            self.message.emit("Not merged: the result would have a hole or be split. The shape was added separately.")
            return
        minx, miny, maxx, maxy = union.bounds
        union = union.simplify(1e-3 * math.hypot(maxx - minx, maxy - miny))
        for old in [item] + [s for s, _g in touched]:
            self._shapes.remove(old)
            self.scene_.removeItem(old)
        self.scene_.clearSelection()
        merged = self._add("polygon", [QPointF(x, y) for x, y in union.exterior.coords[:-1]])
        merged.setSelected(True)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        design = self.mode == "design"
        painter.fillRect(rect, QColor("#ffffff" if design else "#eef0f3"))
        area = rect
        painter.save()
        if not design:
            painter.fillRect(self.stage, QColor("#ffffff"))
            painter.setClipRect(self.stage)
            area = rect.intersected(self.stage)
        step = self.grid_step
        minor, major = [], []
        for i in range(math.ceil(area.left() / step), math.floor(area.right() / step) + 1):
            (major if i % 5 == 0 else minor).append(QLineF(i * step, area.top(), i * step, area.bottom()))
        for i in range(math.ceil(area.top() / step), math.floor(area.bottom() / step) + 1):
            (major if i % 5 == 0 else minor).append(QLineF(area.left(), i * step, area.right(), i * step))
        painter.setPen(QPen(QColor("#eef0f3"), 0))
        painter.drawLines(minor)
        painter.setPen(QPen(QColor("#dde0e5"), 0))
        painter.drawLines(major)
        painter.restore()
        painter.setPen(QPen(QColor("#8a8f98"), 0))
        if design:
            painter.drawLine(QLineF(0, rect.top(), 0, rect.bottom()))
            painter.drawLine(QLineF(rect.left(), 0, rect.right(), 0))
        else:
            painter.drawRect(self.stage)

    def wheelEvent(self, event) -> None:
        """Zoom about the cursor; Shift + wheel pans vertically and Ctrl + wheel horizontally, like Blender."""
        delta = event.angleDelta().y() or event.angleDelta().x() or event.pixelDelta().y()
        if not delta:
            return
        modifiers = event.modifiers()
        if modifiers & (Qt.ShiftModifier | Qt.ControlModifier):
            bar = self.verticalScrollBar() if modifiers & Qt.ShiftModifier else self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            return
        factor = 1.2 ** (delta / 120)
        if ZOOM_RANGE[0] < self.zoom * factor < ZOOM_RANGE[1]:
            self.scale(factor, factor)
            self._refresh_items()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            self.fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_items()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        focus = self.window().focusWidget() if self.window() else None
        if focus is None or not isinstance(focus, (QLineEdit, QAbstractSpinBox)):
            self.setFocus()  # hotkeys act where the mouse is, like Blender

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        if self._xform is not None:
            if event.button() in (Qt.LeftButton, Qt.RightButton):
                self.finish_transform(event.button() == Qt.LeftButton)
            return
        if event.button() == Qt.MiddleButton:
            self._pan = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self.editing is not None and self.tool == "select" and event.button() == Qt.LeftButton:
            hit = self.itemAt(event.position().toPoint())
            if isinstance(hit, Control):
                hit.begin(bool(event.modifiers() & Qt.AltModifier))
                grab = hit.shape_item.mapFromScene(self.mapToScene(event.position().toPoint()))
                self._control = (hit, hit.pos() - grab)
                return
            if not isinstance(hit, Handle):  # clicking another outline of the shape (a hole) edits that one
                other = self.editing.contour_at(self.mapToScene(event.position().toPoint()), PICK_PX / self.zoom)
                if other is not None:
                    self.scene_.clearSelection()
                    self.editing.set_active(other)
                    return
        if self.mode != "design" or self.tool == "select" or event.button() != Qt.LeftButton:
            if self._draft is not None and event.button() == Qt.RightButton:
                self._finish_draft()
            elif self.mode != "design" or self.tool == "select":
                super().mousePressEvent(event)
            return
        point = self.snap(self.mapToScene(event.position().toPoint()))
        op = "add" if self.new_op == "merge" else self.new_op
        if self.tool in ("polyline", "polygon", "pen") and self._draft is not None:
            first = self._draft.points[0]
            if self.tool == "pen" and len(self._draft.points) >= 4 and _dist(first, point) <= PICK_PX * 2 / self.zoom:
                self._draft.points.pop()  # clicking the first node closes the path
                self._draft.kind = "polygon"
                self._draft.set_op(op)
                self._finish_draft(trailing=False)
                return
            self._draft.points[-1] = point
            self._draft.points.append(QPointF(point))
            self._pen_drag = len(self._draft.points) - 2 if self.tool == "pen" else None
        else:
            kind = "polyline" if self.tool == "pen" else self.tool
            self._draft = ShapeItem(kind, [point, point], self, op)
            if kind in CLOSED and op == "add":
                self._draft.setBrush(FILL)
            self.scene_.addItem(self._draft)
            self._pen_drag = 0 if self.tool == "pen" else None
        self._draft.update_path()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._draft is not None:
            self._finish_draft()
        elif self.editing is not None and self.tool == "select" and event.button() == Qt.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            reach = PICK_PX * 1.5 / self.zoom
            if all(_dist(q, point) > reach for q in self.editing.points):
                added = self.editing.insert_node(point, PICK_PX / self.zoom)
                if added is not None:
                    self.scene_.clearSelection()
                    self.editing.handles[added].setSelected(True)
                    self._commit()
        else:
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pan is not None:
            delta = event.position() - self._pan
            self._pan = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            return
        point = self.mapToScene(event.position().toPoint())
        if self._xform is not None:
            self._update_transform(point)
            self.cursorMoved.emit(point.x(), point.y())
            return
        if self._control is not None:
            control, offset = self._control
            shape = control.shape_item
            shape.move_control(control.index, control.side, shape.mapFromScene(point) + offset, control.paired)
        elif self.mode != "design" or self.tool == "select":
            super().mouseMoveEvent(event)
        else:
            raw, point = point, self.snap(point)
            self._indicator.setPos(point)
            self._indicator.setVisible(self.snap_on)
            draft = self._draft
            if draft is not None and self._pen_drag is not None and event.buttons() & Qt.LeftButton:
                i = self._pen_drag  # dragging out a symmetric Bézier handle from the node just placed
                if i < len(draft.points) - 1 and _dist(draft.points[i], raw) > 3 / self.zoom:
                    draft.hout[i], draft.hin[i] = raw, draft.points[i] * 2 - raw
                    draft.update_path()
            elif draft is not None:
                draft.points[-1] = point
                draft.update_path()
        self.cursorMoved.emit(point.x(), point.y())

    def mouseReleaseEvent(self, event) -> None:
        self._pen_drag = None
        if self._xform is not None:
            return
        if self._control is not None:
            self._control = None
            self._commit()
            return
        if event.button() == Qt.MiddleButton:
            self._pan = None
            self._apply_tool()
            return
        if self.mode != "design":
            super().mouseReleaseEvent(event)
        elif self.tool == "select":
            super().mouseReleaseEvent(event)
            for item in self._shapes:
                if not item.pos().isNull():
                    item.bake()
            self._commit()
        elif self._draft is not None and self._draft.kind not in CURVED:
            self._finish_draft()

    def keyPressEvent(self, event) -> None:
        if self._xform is not None:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.finish_transform(True)
            elif event.key() == Qt.Key_Escape:
                self.finish_transform(False)
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finish_draft()
        elif event.key() == Qt.Key_Escape:
            if self._draft is not None:
                self._cancel_draft()
            elif self.editing is not None and not self.editing.selected_nodes():
                self.exit_edit()
            else:
                self.scene_.clearSelection()
        else:
            super().keyPressEvent(event)
