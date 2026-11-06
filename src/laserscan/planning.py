"""Shape parsing, scan path generation and plan estimation. All units are microns."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

PATTERNS = ("serpentine", "raster", "outline")
SHAPE_KEYS = ("type", "x0", "y0", "x1", "y1", "path", "op")
SIMPLIFY_UM = 0.5
_TOKEN = re.compile(r"[MLCZmlcz]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


@dataclass(frozen=True)
class Params:
    """Scan parameters shared by all shapes.

    Attributes:
        pattern: One of ``PATTERNS``; applies to closed shapes only.
        step: Distance between scan lines in microns.
        angle: Scan line angle in degrees from the x axis.
        speed: Stage speed in microns/s.
        margin: Inset from the shape boundary in microns.
        passes: Number of times the whole plan is repeated.
    """

    pattern: str = "serpentine"
    step: float = 3.0
    angle: float = 0.0
    speed: float = 20.0
    margin: float = 0.0
    passes: int = 1


@dataclass
class Segment:
    """A polyline traversed with the laser on or off.

    Attributes:
        points: Array of shape (N, 2) in microns.
        laser: Whether the laser is on along this segment.
    """

    points: np.ndarray
    laser: bool = True


XY = tuple[float, float]
PathNode = tuple[XY, XY | None, XY | None]  # (anchor, handle_in, handle_out); None = straight side


def parse_nodes(path: str) -> tuple[list[PathNode], bool]:
    """Parse a path string made of absolute ``M``, ``L``, ``C`` and ``Z`` commands.

    Numbers without a command are read as ``L`` vertices, and a path whose last
    curve returns to the first anchor is folded into that anchor's incoming handle.

    Returns:
        The nodes and whether the path is closed.
    """
    tokens = _TOKEN.findall(path)
    nodes: list[list] = []
    command, i, closed = "L", 0, False
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command, i = token.upper(), i + 1
            closed = closed or command == "Z"
            continue
        want = 6 if command == "C" else 2
        values = [float(t) for t in tokens[i : i + want] if not t.isalpha()]
        if len(values) < want:
            break
        i += want
        if command == "C" and nodes:
            nodes[-1][2] = (values[0], values[1])
            nodes.append([(values[4], values[5]), (values[2], values[3]), None])
        elif command in "MLC":
            nodes.append([(values[0], values[1]), None, None])
            command = "L" if command == "M" else command
    if closed and len(nodes) > 1 and nodes[-1][0] == nodes[0][0]:
        nodes[0][1] = nodes[-1][1]
        nodes.pop()
    return [(a, h_in, h_out) for a, h_in, h_out in nodes], closed


def parse_contours(path: str) -> list[tuple[list[PathNode], bool]]:
    """Split a path string at each ``M`` into contours; an outline followed by closed holes is one shape."""
    chunks = [c for c in re.split(r"(?=[Mm])", path) if c.strip()]
    contours = [parse_nodes(c) for c in chunks]
    return [(nodes, closed) for nodes, closed in contours if len(nodes) >= 2]


def _fmt(p: XY) -> str:
    return f"{p[0]:.4f},{p[1]:.4f}"


def format_path(nodes: list[PathNode], closed: bool) -> str:
    """Write nodes as a path string; the inverse of :func:`parse_nodes`."""
    out = ["M" + _fmt(nodes[0][0])]
    pairs = list(zip(nodes, nodes[1:]))
    if closed:
        pairs.append((nodes[-1], nodes[0]))
    for k, ((a, _in, a_out), (b, b_in, _out)) in enumerate(pairs):
        if a_out is None and b_in is None:
            if not (closed and k == len(pairs) - 1):  # ``Z`` already draws the straight closing segment
                out.append("L" + _fmt(b))
        else:
            out.append("C" + " ".join(_fmt(p) for p in (a_out or a, b_in or b, b)))
    return "".join(out) + ("Z" if closed else "")


def flatten_nodes(nodes: list[PathNode], closed: bool) -> list[XY]:
    """Approximate the path by a polyline; curves are sampled finely enough for micron-scale scanning."""
    pts = [nodes[0][0]]
    pairs = list(zip(nodes, nodes[1:]))
    if closed:
        pairs.append((nodes[-1], nodes[0]))
    for k, ((a, _in, a_out), (b, b_in, _out)) in enumerate(pairs):
        if a_out is None and b_in is None:
            pts.append(b)
            continue
        c1, c2 = a_out or a, b_in or b
        length = sum(np.hypot(q[0] - p[0], q[1] - p[1]) for p, q in ((a, c1), (c1, c2), (c2, b)))
        n = int(min(256, max(16, length / 2)))
        for t in np.linspace(0, 1, n + 1)[1:]:
            u = 1 - t
            pts.append(
                tuple(u**3 * a[d] + 3 * u * u * t * c1[d] + 3 * u * t * t * c2[d] + t**3 * b[d] for d in (0, 1))
            )
    return pts[:-1] if closed else pts


def parse_path(path: str) -> list[XY]:
    """Extract the (x, y) vertices of a path string such as ``M0,0L1,1Z``; curves are flattened."""
    return flatten_nodes(*parse_nodes(path)) if path.strip() else []


def clean_shape(shape: dict) -> dict:
    """Keep only the keys of a shape dictionary that define its geometry and operation."""
    return {k: shape[k] for k in SHAPE_KEYS if k in shape}


def parse_shape(shape: dict) -> Polygon | LineString | None:
    """Convert a shape dictionary to a shapely geometry.

    Args:
        shape: Shape dictionary (``rect``, ``circle``, ``line`` or ``path``).

    Returns:
        A polygon for closed shapes, a line string for open ones, or ``None``
        if the shape is degenerate or of an unsupported type.
    """
    kind = shape.get("type")
    if kind in ("rect", "circle", "line"):
        x0, y0, x1, y1 = (float(shape[k]) for k in ("x0", "y0", "x1", "y1"))
    if kind == "rect":
        geom = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    elif kind == "circle":
        geom = affinity.scale(Point((x0 + x1) / 2, (y0 + y1) / 2).buffer(1, 64), abs(x1 - x0) / 2, abs(y1 - y0) / 2)
    elif kind == "line":
        geom = LineString([(x0, y0), (x1, y1)])
    elif kind == "path":
        contours = parse_contours(shape["path"])
        if not contours:
            return None
        points = flatten_nodes(*contours[0])
        closed = contours[0][1] and len(points) >= 3
        if closed:
            geom = Polygon(points).buffer(0)
            for nodes, hole_closed in contours[1:]:  # further closed contours are holes (even-odd)
                ring = flatten_nodes(nodes, hole_closed)
                if hole_closed and len(ring) >= 3:
                    geom = geom.symmetric_difference(Polygon(ring).buffer(0))
        else:
            geom = LineString(points)
    else:
        return None
    return None if geom.is_empty or geom.length == 0 or geom.geom_type not in ("Polygon", "LineString") else geom


def _lines(geom) -> list[LineString]:
    return [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "LineString" and g.length > 0]


def _hatch(region: Polygon, step: float, angle: float, alternate: bool) -> list[np.ndarray]:
    origin = region.centroid
    rotated = affinity.rotate(region, -angle, origin=origin)
    x0, y0, x1, y1 = rotated.bounds
    out: list[np.ndarray] = []
    for row, y in enumerate(np.arange(y0, y1 + 1e-9, step)):
        hits = _lines(rotated.intersection(LineString([(x0 - 1, y), (x1 + 1, y)])))
        for line in sorted(hits, key=lambda g: g.coords[0][0]):
            pts = np.asarray(affinity.rotate(line, angle, origin=origin).coords)
            out.append(pts[::-1] if alternate and row % 2 else pts)
    return out


def _join(lines: list[np.ndarray], region: Polygon) -> list[np.ndarray]:
    joined = [lines[0]]
    covered = region.buffer(1e-6)
    for line in lines[1:]:
        if covered.covers(LineString([joined[-1][-1], line[0]])):
            joined[-1] = np.vstack([joined[-1], line])
        else:
            joined.append(line)
    return joined


def _polygons(geom) -> list[Polygon]:
    return [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and not g.is_empty]


def build_region(shapes: list[dict]) -> tuple[Polygon | MultiPolygon | None, list[LineString]]:
    """Combine shapes into one scan region and a list of open paths.

    Closed shapes with ``"op": "subtract"`` are removed from the union of the
    other closed shapes. Open shapes are returned as drawn.

    Args:
        shapes: Shape dictionaries in microns.

    Returns:
        The region, or ``None`` if nothing remains, and the open paths.
    """
    adds, subtracts, lines = [], [], []
    for shape in shapes:
        geom = parse_shape(shape)
        if geom is None:
            continue
        if geom.geom_type == "LineString":
            lines.append(geom)
        else:
            (subtracts if shape.get("op") == "subtract" else adds).append(geom)
    region = unary_union(adds) if adds else None
    if region is not None and subtracts:
        region = region.difference(unary_union(subtracts))
    return (None if region is None or not _polygons(region) else region), lines


def build_plan(shapes: list[dict], params: Params) -> list[Segment]:
    """Generate scan segments for all shapes.

    Open shapes are traversed as drawn. The combined closed region is filled
    according to ``params.pattern``.

    Args:
        shapes: Shape dictionaries in microns.
        params: Scan parameters.

    Returns:
        The segments (open paths first, then the region), repeated ``params.passes`` times.

    Raises:
        ValueError: If the step or pattern is invalid.
    """
    if params.step <= 0 or params.pattern not in PATTERNS:
        raise ValueError("Step must be positive and the pattern one of " + ", ".join(PATTERNS))
    region, paths = build_region(shapes)
    arrays = [np.asarray(line.simplify(SIMPLIFY_UM).coords) for line in paths]
    if region is not None:
        region = region.buffer(-params.margin) if params.margin else region
        if not region.is_empty:
            if params.pattern == "outline":
                arrays += [np.asarray(r.coords) for p in _polygons(region) for r in (p.exterior, *p.interiors)]
            else:
                lines = _hatch(region, params.step, params.angle, params.pattern == "serpentine")
                arrays += _join(lines, region) if lines and params.pattern == "serpentine" else lines
    return [Segment(a) for a in arrays] * max(1, params.passes)


def region_polygons(shapes: list[dict], origin: tuple[float, float] = (0.0, 0.0)) -> list[Polygon]:
    """Return the scan region as polygons translated by ``origin``."""
    region, _ = build_region(shapes)
    return [] if region is None else [affinity.translate(p, *origin) for p in _polygons(region)]


def shift(plan: list[Segment], origin: tuple[float, float]) -> list[Segment]:
    """Translate a plan by ``origin`` (relative to absolute coordinates)."""
    offset = np.asarray(origin, dtype=float)
    return [Segment(seg.points + offset, seg.laser) for seg in plan]


def trace_arrays(plan: list[Segment], origin: tuple[float, float] | None = None):
    """Build plot coordinates for the laser-on and transit paths.

    Args:
        plan: Scan segments.
        origin: Starting position of the stage for the first transit, if known.

    Returns:
        Two (x, y) pairs of lists, ``(on, off)``, with ``None`` separating segments.
    """
    on: tuple[list, list] = ([], [])
    off: tuple[list, list] = ([], [])
    here = origin
    for seg in plan:
        if here is not None:
            off[0].extend([here[0], seg.points[0][0], None])
            off[1].extend([here[1], seg.points[0][1], None])
        on[0].extend([*seg.points[:, 0], None])
        on[1].extend([*seg.points[:, 1], None])
        here = tuple(seg.points[-1])
    return on, off


def move_time(distance, speed: float, accel: float | None = None, ramp: float = 0.0):
    """Duration of point-to-point moves that start and end at rest.

    Args:
        distance: Move length(s) in microns.
        speed: Maximum speed in microns/s.
        accel: Acceleration in microns/s^2, or ``None`` for constant speed.
        ramp: Extra time per move for the S-curve jerk phases, in seconds.

    Returns:
        Move duration(s) in seconds. Moves shorter than ``2 * speed**2 / accel``
        never reach full speed and use a triangular profile.
    """
    d = np.asarray(distance, dtype=float)
    if not accel:
        return d / speed
    time = np.where(d >= speed**2 / accel, d / speed + speed / accel, 2 * np.sqrt(d / accel)) + ramp
    return np.where(d > 0, time, 0.0)


def estimate(
    plan: list[Segment], speed: float, accel: float | None = None, ramp: float = 0.0
) -> tuple[float, float, float]:
    """Estimate path length and duration for a plan starting at the origin (0, 0).

    Every point is a separate move that stops at its target, so each leg pays
    its own acceleration and deceleration.

    Args:
        plan: Scan segments relative to the starting stage position.
        speed: Maximum stage speed in microns/s.
        accel: Acceleration in microns/s^2, or ``None`` for constant speed.
        ramp: Extra time per move for the S-curve jerk phases, in seconds.

    Returns:
        Laser-on length and transit length in microns, and total time in seconds.
    """
    on, off, here = [], [], np.zeros(2)
    for seg in plan:
        off.append(float(np.hypot(*(seg.points[0] - here))))
        on.extend(np.hypot(*np.diff(seg.points, axis=0).T))
        here = seg.points[-1]
    legs = np.array(off + on)
    total = float(move_time(legs, speed, accel, ramp).sum()) if speed > 0 and len(legs) else 0.0
    return float(sum(on)), float(sum(off)), total


def overrun(
    plan: list[Segment], origin: tuple[float, float], x_range: tuple[float, float], y_range: tuple[float, float]
) -> tuple[list[bool], list[str]]:
    """Check a plan placed at ``origin`` against the stage range.

    Args:
        plan: Segments relative to ``origin``.
        origin: Absolute stage position the plan starts from, in microns.
        x_range: Allowed (min, max) x in microns.
        y_range: Allowed (min, max) y in microns.

    Returns:
        A per-segment flag that is true if the segment leaves the range, and
        messages describing how far the plan exceeds each side.
    """
    low, high = np.array([x_range[0], y_range[0]]), np.array([x_range[1], y_range[1]])
    flags, messages = [], []
    lo = hi = np.asarray(origin, dtype=float)
    for seg in plan:
        points = seg.points + origin
        lo, hi = np.minimum(lo, points.min(axis=0)), np.maximum(hi, points.max(axis=0))
        flags.append(bool((points.min(axis=0) < low).any() or (points.max(axis=0) > high).any()))
    for axis, name in enumerate("XY"):
        if lo[axis] < low[axis]:
            messages.append(f"{name} min exceeded by {low[axis] - lo[axis]:.1f} µm")
        if hi[axis] > high[axis]:
            messages.append(f"{name} max exceeded by {hi[axis] - high[axis]:.1f} µm")
    return flags, messages
