"""Import drawings (SVG, DXF, GDSII, bitmaps) as shapes, export the drawing (SVG, DXF) and the scan path (CSV, G-code, NPZ).

All units are microns inside the program; the files use the units of their format.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely.geometry import MultiLineString
from shapely.ops import linemerge

from laserscan.planning import Params, Segment, flatten_nodes, format_path, parse_nodes

IMPORT_SUFFIXES = (".svg", ".dxf", ".gds", ".gds2", ".gdsii", ".csv")
DRAWING_SUFFIXES = (".svg", ".dxf")
"""Formats the drawing can be exported as."""
PATH_SUFFIXES = (".csv", ".gcode", ".npz")
"""Formats the scan path can be exported as."""
SVG_PX_UM = 25400 / 96
"""One CSS pixel (1/96 inch) in microns."""
DXF_UNITS_UM = {1: 25400.0, 2: 304800.0, 3: 1609344000.0, 4: 1000.0, 5: 10000.0, 6: 1e6, 7: 1e9, 13: 1.0, 14: 1e5}
"""DXF ``$INSUNITS`` code to microns per drawing unit (inch, foot, mile, mm, cm, m, km, micron, decimeter)."""
DXF_TOLERANCE_UM = 1.0
"""Maximum distance between a flattened DXF curve and the true curve."""
SVG_SAMPLES = 24
"""Points sampled along each SVG curve segment."""

BITMAP_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp")
BITMAP_MAX_PX = 1200
"""Bitmaps are scaled down to at most this many pixels on the long side before thresholding and tracing."""

Contour = tuple[list[tuple[float, float]], bool]  # (points, closed)


@dataclass
class Imported:
    """Result of an import.

    Attributes:
        shapes: Shape dictionaries (``type: "path"``) in microns, y up.
        message: What was read, with the unit assumption and anything skipped.
    """

    shapes: list[dict]
    message: str


def _clean(points, closed: bool) -> list[tuple[float, float]]:
    """Drop repeated points (and the repeated first point of a closed ring)."""
    out: list[tuple[float, float]] = []
    for x, y in points:
        p = (float(x), float(y))
        if not out or p != out[-1]:
            out.append(p)
    if closed and len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _path(contours: list[Contour]) -> str:
    return "".join(format_path([(p, None, None) for p in pts], closed) for pts, closed in contours)


def _shapes(contours: list[Contour]) -> list[dict]:
    """Turn contours into shapes: closed contours of one element form one shape with holes, open ones are separate."""
    contours = [(c, closed) for pts, closed in contours if len(c := _clean(pts, closed)) >= (3 if closed else 2)]
    if contours and all(closed for _, closed in contours):
        return [{"type": "path", "path": _path(contours), "op": "add"}]
    return [{"type": "path", "path": _path([c]), "op": "add"} for c in contours]


def _nest(contours: list[Contour]) -> list[dict]:
    """Shapes from loose contours: closed contours inside another closed one become its holes (even-odd)."""
    from shapely.geometry import Polygon

    cleaned = [(c, closed) for pts, closed in contours if len(c := _clean(pts, closed)) >= (3 if closed else 2)]
    closed_ids = [i for i, (_c, closed) in enumerate(cleaned) if closed]
    polys = {i: Polygon(cleaned[i][0]).buffer(0) for i in closed_ids}
    parents = {i: [j for j in closed_ids if j != i and polys[j].area > polys[i].area and polys[j].contains(polys[i])] for i in closed_ids}
    holes: dict[int, list[int]] = {}
    shapes_: list[dict] = []
    for i in closed_ids:
        if len(parents[i]) % 2:  # odd depth: a hole of its smallest container
            holes.setdefault(min(parents[i], key=lambda j: polys[j].area), []).append(i)
    for i, (c, closed) in enumerate(cleaned):
        if closed and len(parents[i]) % 2:
            continue
        group = [(c, closed)] + [(cleaned[h][0], True) for h in holes.get(i, [])]
        shapes_.append({"type": "path", "path": _path(group), "op": "add"})
    return shapes_


def _centre(shapes: list[dict]) -> list[dict]:
    """Translate shapes so that the centre of their bounding box is the origin; curves are kept."""
    from laserscan.planning import parse_contours

    parsed = [parse_contours(s["path"]) for s in shapes]
    anchors = [a for contours in parsed for nodes, _ in contours for a, _i, _o in nodes]
    if not anchors:
        return shapes
    cx = (min(p[0] for p in anchors) + max(p[0] for p in anchors)) / 2
    cy = (min(p[1] for p in anchors) + max(p[1] for p in anchors)) / 2

    def move(p):
        return None if p is None else (p[0] - cx, p[1] - cy)

    return [
        {**s, "path": "".join(format_path([(move(a), move(i), move(o)) for a, i, o in nodes], closed) for nodes, closed in contours)}
        for s, contours in zip(shapes, parsed)
    ]


def _merge_open(contours: list[Contour]) -> list[Contour]:
    """Join open polylines that share end points (CAD drawings often store a rectangle as four lines)."""
    open_ = [pts for pts, closed in contours if not closed]
    rest = [c for c in contours if c[1]]
    if len(open_) < 2:
        return contours
    rounded = [[(round(x, 3), round(y, 3)) for x, y in pts] for pts in open_]
    merged = linemerge(MultiLineString(rounded))
    for line in getattr(merged, "geoms", [merged]):
        pts = list(line.coords)
        rest.append((pts, line.is_ring))
    return rest


def _import_svg(path: Path) -> Imported:
    from svgelements import SVG, Close, Path as SvgPath, Shape

    svg = SVG.parse(str(path), reify=True, ppi=96)
    shapes: list[dict] = []
    for element in svg.elements():
        if not isinstance(element, Shape):
            continue
        contours: list[Contour] = []
        for sub in SvgPath(element).as_subpaths():
            sub = SvgPath(sub)
            pts = []
            for seg in sub:
                if isinstance(seg, Close):
                    continue
                n = 1 if type(seg).__name__ in ("Line", "Move") else SVG_SAMPLES
                pts.extend((seg.point(t).x, seg.point(t).y) for t in np.linspace(0, 1, n + 1)[1:])
            closed = any(isinstance(seg, Close) for seg in sub) or (len(pts) > 2 and pts[0] == pts[-1])
            contours.append(([(x * SVG_PX_UM, -y * SVG_PX_UM) for x, y in pts], closed))
        shapes += _shapes(contours)
    return Imported(_centre(shapes), "SVG read at 96 px/inch (1 px = 264.6 µm), y axis flipped")


def _import_dxf(path: Path) -> Imported:
    import ezdxf
    from ezdxf import path as dxf_path

    doc = ezdxf.readfile(str(path))
    code = int(doc.header.get("$INSUNITS", 0))
    factor = DXF_UNITS_UM.get(code)
    basis = "drawing units" if factor else "no drawing units set, assuming millimetres"
    factor = factor or 1000.0
    contours: list[Contour] = []
    skipped: dict[str, int] = {}
    for entity in doc.modelspace():
        try:
            p = dxf_path.make_path(entity)
        except TypeError:
            skipped[entity.dxftype()] = skipped.get(entity.dxftype(), 0) + 1
            continue
        for sub in p.sub_paths():
            pts = [(v.x * factor, v.y * factor) for v in sub.flattening(DXF_TOLERANCE_UM / factor)]
            contours.append((pts, sub.is_closed))
    shapes = _nest(_merge_open(contours))
    message = f"DXF read using {basis} (x{factor:g} µm)"
    if skipped:
        message += "; skipped " + ", ".join(f"{n} {kind}" for kind, n in sorted(skipped.items()))
    return Imported(_centre(shapes), message)


def _import_gds(path: Path) -> Imported:
    """Read a GDSII library: all top-level cells with references and paths expanded, polygons united per layer."""
    import gdstk
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    lib = gdstk.read_gds(str(path))
    factor = lib.unit * 1e6  # user units to microns
    tops = lib.top_level()
    if not tops:
        raise ValueError("The GDSII file has no cells.")
    layers: dict[tuple[int, int], list[Polygon]] = {}
    for cell in tops:
        for poly in cell.get_polygons():
            geom = Polygon(poly.points * factor).buffer(0)
            if not geom.is_empty:
                layers.setdefault((poly.layer, poly.datatype), []).append(geom)
    shapes: list[dict] = []
    for _key, polys in sorted(layers.items()):
        merged = unary_union(polys)
        for g in getattr(merged, "geoms", [merged]):
            if g.geom_type == "Polygon" and not g.is_empty:
                shapes.append({"type": "path", "path": _path([(list(r.coords), True) for r in (g.exterior, *g.interiors)]), "op": "add"})
    message = f"GDSII read from cell {', '.join(c.name for c in tops)} (1 unit = {lib.unit * 1e6:g} µm), {len(layers)} layer(s) imported"
    return Imported(_centre(shapes), message)


def _import_csv(path: Path) -> Imported:
    """Read x,y points in microns; blank lines separate polylines. Two-column rows only, a header row is skipped."""
    groups: list[list[tuple[float, float]]] = [[]]
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            cells = [c.strip() for c in row if c.strip()]
            if not cells:
                groups.append([])
                continue
            try:
                groups[-1].append((float(cells[0]), float(cells[1])))
            except (ValueError, IndexError):
                if any(groups):
                    raise ValueError(f"Not an x,y row: {','.join(row)}") from None
    contours = [(g, len(g) > 3 and g[0] == g[-1]) for g in groups if len(g) >= 2]
    return Imported(_shapes_each(contours), "CSV read as x,y in µm relative to the start position")


def _shapes_each(contours: list[Contour]) -> list[dict]:
    return [s for c in contours for s in _shapes([c])]


def import_shapes(path: str | Path) -> Imported:
    """Read a drawing as shapes.

    SVG, DXF and GDSII drawings are scaled to microns from their units and centred on the
    start position; CSV points are taken as microns as they are.

    Args:
        path: ``.svg``, ``.dxf`` or ``.csv`` file.

    Returns:
        The shapes and a description of the units used.

    Raises:
        ValueError: If the format is unsupported, the file is unreadable, or it holds no geometry.
    """
    path = Path(path)
    readers = {".svg": _import_svg, ".dxf": _import_dxf, ".gds": _import_gds, ".gds2": _import_gds, ".gdsii": _import_gds, ".csv": _import_csv}
    reader = readers.get(path.suffix.lower())
    if reader is None:
        raise ValueError(f"Unsupported file type {path.suffix or path.name!r}; use " + ", ".join(IMPORT_SUFFIXES) + ".")
    try:
        result = reader(path)
    except ValueError:
        raise
    except Exception as exc:  # parsers raise many unrelated types on bad input
        raise ValueError(f"Cannot read {path.name}: {exc}") from exc
    if not result.shapes:
        raise ValueError(f"No lines or outlines found in {path.name}.")
    result.message = f"Imported {len(result.shapes)} shape(s) from {path.name}: {result.message}."
    return result


# -- export ------------------------------------------------------------------------


def drawing_geometry(shapes: list[dict]) -> tuple[list, list]:
    """Polygons (subtractions applied, curves flattened) and open lines of a drawing, in microns, y up."""
    from laserscan.planning import _polygons, build_region

    region, lines = build_region(shapes)
    polygons = [] if region is None else _polygons(region)
    if not polygons and not lines:
        raise ValueError("Nothing to export: draw a shape first.")
    return polygons, lines


def _export_svg(polygons, lines, path: Path) -> None:
    """SVG in millimetres with a micron-scaled view box; y is flipped because SVG points down."""
    bounds = np.array([g.bounds for g in (*polygons, *lines)])
    x0, y0, x1, y1 = bounds[:, 0].min(), bounds[:, 1].min(), bounds[:, 2].max(), bounds[:, 3].max()
    pad = max(x1 - x0, y1 - y0) * 0.02 or 1.0
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad

    def ring(coords) -> str:
        pts = list(coords)
        return "M" + "L".join(f"{x:.4f},{-y:.4f}" for x, y in pts[:-1]) + "Z"

    def poly(g) -> str:
        return "".join(ring(r.coords) for r in (g.exterior, *g.interiors))

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{(x1 - x0) / 1000:.6f}mm" height="{(y1 - y0) / 1000:.6f}mm" '
        f'viewBox="{x0:.4f} {-y1:.4f} {x1 - x0:.4f} {y1 - y0:.4f}">',
        "<!-- laserscan export: 1 view-box unit = 1 micron -->",
    ]
    out += [f'<path d="{poly(g)}" fill="#000" fill-rule="evenodd"/>' for g in polygons]
    width = (x1 - x0) / 1000
    out += [
        f'<path d="M{"L".join(f"{x:.4f},{-y:.4f}" for x, y in g.coords)}" fill="none" stroke="#000" stroke-width="{width:.4f}"/>'
        for g in lines
    ]
    out.append("</svg>")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _export_dxf(polygons, lines, path: Path) -> None:
    """DXF R2010 in millimetres (``$INSUNITS`` = 4); outlines and holes are closed polylines, open shapes open ones."""
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for g in polygons:
        for r in (g.exterior, *g.interiors):
            msp.add_lwpolyline([(x / 1000, y / 1000) for x, y in r.coords[:-1]], close=True)
    for g in lines:
        msp.add_lwpolyline([(x / 1000, y / 1000) for x, y in g.coords])
    doc.saveas(str(path))


def export_drawing(shapes: list[dict], path: str | Path) -> str:
    """Write the drawing as a standard 2D graphics file; the format follows the suffix.

    Subtracted shapes are applied and curves are flattened, so the file holds what will be scanned.

    - ``.svg``: millimetres, y axis pointing down as SVG expects; 1 view-box unit is 1 µm.
    - ``.dxf``: millimetres, y axis up.

    Args:
        shapes: Shape dictionaries in microns, relative to the start position.
        path: Destination.

    Returns:
        A short description of what was written.

    Raises:
        ValueError: If the drawing is empty or the suffix is unsupported.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    writer = {".svg": _export_svg, ".dxf": _export_dxf}.get(suffix)
    if writer is None:
        raise ValueError(f"Unsupported export type {suffix!r}; use " + ", ".join(DRAWING_SUFFIXES) + ".")
    polygons, lines = drawing_geometry(shapes)
    writer(polygons, lines, path)
    return f"{len(polygons)} outline(s), {len(lines)} open path(s)"


def export_plan(plan: list[Segment], params: Params, path: str | Path) -> None:
    """Write a scan plan; the format follows the suffix. Coordinates are relative to the start position.

    - ``.csv``: ``segment,x_um,y_um,laser,speed_um_s`` rows.
    - ``.gcode``: millimetres, absolute moves; ``M3`` / ``M5`` switch the laser, feed ``F`` is mm/min.
    - ``.npz``: ``points`` (N, 2), ``segment`` (N,), ``laser`` (per segment), ``speed_um_s``.

    Args:
        plan: Segments to write.
        params: Scan parameters (the speed is written out).
        path: Destination.

    Raises:
        ValueError: If the plan is empty or the suffix is unsupported.
    """
    path = Path(path)
    if not plan:
        raise ValueError("Nothing to export: the plan is empty.")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["segment", "x_um", "y_um", "laser", "speed_um_s"])
            for i, seg in enumerate(plan):
                for x, y in seg.points:
                    w.writerow([i, f"{x:.4f}", f"{y:.4f}", int(seg.laser), f"{params.speed:g}"])
    elif suffix == ".gcode":
        feed = params.speed * 60 / 1000
        lines = [
            "; laserscan export, coordinates relative to the start position",
            f"; pattern={params.pattern} step={params.step:g}um angle={params.angle:g} speed={params.speed:g}um/s passes={params.passes}",
            "G21 ; millimetres",
            "G90 ; absolute",
        ]
        for i, seg in enumerate(plan):
            (x0, y0), rest = seg.points[0], seg.points[1:]
            lines += [f"; segment {i}", f"G0 X{x0 / 1000:.5f} Y{y0 / 1000:.5f}"]
            if seg.laser:
                lines.append("M3")
            lines += [f"G{1 if seg.laser else 0} X{x / 1000:.5f} Y{y / 1000:.5f} F{feed:.4f}" for x, y in rest]
            if seg.laser:
                lines.append("M5")
        lines.append("M2")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif suffix == ".npz":
        np.savez(
            path,
            points=np.vstack([s.points for s in plan]),
            segment=np.concatenate([np.full(len(s.points), i) for i, s in enumerate(plan)]),
            laser=np.array([s.laser for s in plan]),
            speed_um_s=params.speed,
        )
    else:
        raise ValueError(f"Unsupported export type {suffix!r}; use " + ", ".join(PATH_SUFFIXES) + ".")


# -- bitmaps -----------------------------------------------------------------------


def load_bitmap(path: str | Path) -> np.ndarray:
    """Read an image as an 8-bit grey array (0 black, 255 white), at most ``BITMAP_MAX_PX`` on the long side.

    Transparent pixels count as white, EXIF rotation is applied, and only the first frame of multi-page files is read.

    Raises:
        ValueError: If the file is not a readable image.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(path) as im:
            im.draft("L", (BITMAP_MAX_PX * 2, BITMAP_MAX_PX * 2))  # lets JPEG decode at reduced size
            im = ImageOps.exif_transpose(im)
            if im.mode.startswith("I"):  # 16- and 32-bit greys: stretch to the full range
                raw = np.asarray(im, dtype=float)
                span = (raw.max() - raw.min()) or 1.0
                im = Image.fromarray(((raw - raw.min()) * 255 / span).astype(np.uint8))
            elif "A" in im.mode or "transparency" in im.info:
                rgba = im.convert("RGBA")
                backdrop = Image.new("RGBA", rgba.size, "white")
                im = Image.alpha_composite(backdrop, rgba)
            im = im.convert("L")
            im.thumbnail((BITMAP_MAX_PX, BITMAP_MAX_PX), Image.LANCZOS)
            return np.asarray(im, dtype=np.uint8).copy()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Cannot read {Path(path).name} as an image: {exc}") from exc


def otsu_threshold(gray: np.ndarray) -> int:
    """Threshold (0-255) that best separates dark from bright pixels (Otsu's method)."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    total = hist.sum()
    levels = np.arange(256)
    w0 = np.cumsum(hist)
    m0 = np.cumsum(hist * levels)
    w1 = total - w0
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (m0[-1] * w0 - m0 * total) ** 2 / (w0 * w1)
    between = np.nan_to_num(between)
    best = np.flatnonzero(between >= between.max() * (1 - 1e-9))  # a plateau for two-level images: take its middle
    return int(best.mean()) + 1  # pixels below the threshold are the dark class


def bitmap_mask(gray: np.ndarray, threshold: int, invert: bool) -> np.ndarray:
    """Pixels to scan: darker than ``threshold``, or at least that bright when ``invert``."""
    return gray >= threshold if invert else gray < threshold


def _bezier_path(curve, scale: float) -> str:
    """Write a potrace curve as one closed ``M L C Z`` contour in microns with y up."""

    def pt(p) -> str:
        return f"{p.x * scale:.4f},{-p.y * scale:.4f}"

    out = ["M" + pt(curve.start_point)]
    for seg in curve.segments:
        if seg.is_corner:
            out.append("L" + pt(seg.c) + "L" + pt(seg.end_point))
        else:
            out.append("C" + " ".join(pt(p) for p in (seg.c1, seg.c2, seg.end_point)))
    return "".join(out) + "Z"


def _group(items: list[tuple[str, object]]) -> list[dict]:
    """Group single-contour closed paths into shapes: a contour inside another becomes its hole, one inside a hole an island."""
    polys = [poly for _path_, poly in items]
    parents = [[j for j, q in enumerate(polys) if j != i and q.area > p.area and q.contains(p)] for i, p in enumerate(polys)]
    holes: dict[int, list[int]] = {}
    for i, up in enumerate(parents):
        if len(up) % 2:
            holes.setdefault(min(up, key=lambda j: polys[j].area), []).append(i)
    return [
        {"type": "path", "path": items[i][0] + "".join(items[h][0] for h in holes.get(i, [])), "op": "add"}
        for i in range(len(items))
        if len(parents[i]) % 2 == 0
    ]


def trace_bitmap(
    gray: np.ndarray,
    threshold: int,
    invert: bool,
    width_um: float,
    speckle_px: int = 4,
    smoothness: float = 1.0,
) -> Imported:
    """Trace the dark (or bright) parts of a grey image into closed shapes with Bézier outlines.

    Args:
        gray: 8-bit grey array from :func:`load_bitmap`.
        threshold: Level 0-255 separating scanned from unscanned pixels.
        invert: Scan the bright parts instead of the dark ones.
        width_um: Width the image gets on the stage; the height follows from the aspect ratio.
        speckle_px: Ignore blobs of at most this many pixels.
        smoothness: Potrace corner threshold, 0 (all corners) to 1.33 (smoothest).

    Returns:
        The shapes, centred on the start position, and a summary.

    Raises:
        ValueError: If the width is not positive, or no pixel is selected.
    """
    import potrace
    from shapely.geometry import Polygon

    if not width_um > 0:
        raise ValueError("The width must be positive.")
    mask = bitmap_mask(gray, threshold, invert)
    if not mask.any():
        raise ValueError("No pixels are selected at this threshold.")
    scale = width_um / gray.shape[1]
    curves = potrace.Bitmap(~mask).trace(turdsize=max(0, int(speckle_px)), alphamax=float(np.clip(smoothness, 0.0, 4 / 3)), opttolerance=0.2)
    items = []
    for curve in curves:
        text = _bezier_path(curve, scale)
        nodes, closed = parse_nodes(text)
        poly = Polygon(flatten_nodes(nodes, closed)).buffer(0)
        if not poly.is_empty:
            items.append((text, poly))
    shapes = _centre(_group(items))
    if not shapes:
        raise ValueError("Nothing left after removing specks; lower the speck size.")
    height_um = gray.shape[0] * scale
    return Imported(shapes, f"Traced {len(shapes)} shape(s) from a {gray.shape[1]}x{gray.shape[0]} px bitmap, {width_um:g} x {height_um:g} µm")
