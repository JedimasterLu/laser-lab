"""Shape operations that need geometry libraries: merging shapes. Shapes are path dictionaries."""

from __future__ import annotations

import math

from shapely.ops import unary_union

from laserscan.planning import format_path, parse_shape


def _is_closed(shape: dict) -> bool:
    return "op" in shape


def _fuse(shapes: list[dict], geoms: list, drop: set[int]) -> tuple[list[dict], list[int], str]:
    """Replace the shapes in ``drop`` by the union of ``geoms``, if that is one polygon without holes."""
    union = unary_union(geoms)
    if union.geom_type != "Polygon" or list(union.interiors):
        return shapes, [], "Not merged: the result would have a hole or be split. The shapes were kept separate."
    minx, miny, maxx, maxy = union.bounds
    union = union.simplify(1e-3 * math.hypot(maxx - minx, maxy - miny))
    nodes = [((x, y), None, None) for x, y in union.exterior.coords[:-1]]
    result = [s for i, s in enumerate(shapes) if i not in drop] + [{"type": "path", "path": format_path(nodes, True), "op": "add"}]
    return result, [len(result) - 1], ""


def merge(shapes: list[dict], index: int) -> tuple[list[dict], list[int], str]:
    """Fuse the closed shape at ``index`` with every added closed shape it touches.

    Returns:
        The shapes, the indices to select, and a message (empty unless nothing was merged because
        the result would have a hole or be split).
    """
    item = parse_shape(shapes[index])
    touched = [
        (i, g)
        for i, s in enumerate(shapes)
        if i != index and _is_closed(s) and s["op"] == "add"
        for g in [parse_shape(s)]
        if g is not None and item is not None and g.intersects(item)
    ]
    if not touched:
        return shapes, [], ""
    return _fuse(shapes, [item] + [g for _i, g in touched], {index} | {i for i, _g in touched})


def merge_many(shapes: list[dict], indices: list[int]) -> tuple[list[dict], list[int], str]:
    """Fuse the closed Add shapes at ``indices`` into one polygon.

    Returns:
        The shapes, the indices to select, and a message if nothing was merged.
    """
    picked = [(i, parse_shape(shapes[i])) for i in indices if _is_closed(shapes[i]) and shapes[i]["op"] == "add"]
    picked = [(i, g) for i, g in picked if g is not None]
    if len(picked) < 2:
        return shapes, [], "Select two or more closed Add shapes to merge."
    return _fuse(shapes, [g for _i, g in picked], {i for i, _g in picked})
