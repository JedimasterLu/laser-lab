"""Tests for drawing import and export and scan path export."""

import numpy as np
import pytest

from laserscan import fileio
from laserscan.planning import Params, build_plan, parse_shape

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10">
<rect x="0" y="0" width="4" height="2"/>
<path d="M6 6 L9 6 L9 9 Z M7.5 6.5 L8.5 6.5 L8.5 7.5 Z"/>
<circle cx="5" cy="5" r="1"/>
<path d="M0 9 L2 9" fill="none" stroke="black"/>
</svg>"""


def test_svg_import_units_and_flip(tmp_path):
    f = tmp_path / "a.svg"
    f.write_text(SVG)
    result = fileio.import_shapes(f)
    assert len(result.shapes) == 4
    geoms = [parse_shape(s) for s in result.shapes]
    assert all(g is not None for g in geoms)
    rect = next(g for g in geoms if g.geom_type == "Polygon" and abs(g.area - 8e6) < 1e4)  # 4 mm x 2 mm
    assert rect.bounds[2] - rect.bounds[0] == pytest.approx(4000, abs=1)
    xs = np.concatenate([np.asarray(g.bounds)[[0, 2]] for g in geoms])
    assert xs.min() == pytest.approx(-xs.max(), abs=1)  # centred
    holed = next(g for g in geoms if g.geom_type == "Polygon" and g.interiors)
    assert len(holed.interiors) == 1
    # y axis flipped: the rectangle at the top of the SVG is above the line at the bottom
    line = next(g for g in geoms if g.geom_type == "LineString")
    assert rect.centroid.y > line.centroid.y


def test_dxf_import_merges_lines(tmp_path):
    import ezdxf

    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in [((0, 0), (2, 0)), ((2, 0), (2, 1)), ((2, 1), (0, 1)), ((0, 1), (0, 0))]:
        msp.add_line(a, b)
    msp.add_circle((10, 0), 1)
    msp.add_circle((10, 0), 0.5)  # inside the other circle: a hole
    f = tmp_path / "a.dxf"
    doc.saveas(f)
    result = fileio.import_shapes(f)
    areas = sorted(parse_shape(s).area for s in result.shapes)
    assert len(areas) == 2
    assert areas[0] == pytest.approx(2e6, rel=1e-3)  # 2 mm x 1 mm rectangle from four lines
    assert areas[1] == pytest.approx(np.pi * 0.75e6, rel=2e-3)  # ring: outer circle minus the hole


def test_gds_import(tmp_path):
    import gdstk

    lib = gdstk.Library(unit=1e-6, precision=1e-9)
    top, sub = lib.new_cell("TOP"), lib.new_cell("SUB")
    top.add(gdstk.rectangle((0, 0), (40, 20), layer=1))
    top.add(gdstk.rectangle((10, 5), (20, 15), layer=2))  # other layer, inside the first rectangle
    sub.add(gdstk.rectangle((0, 0), (10, 10), layer=1))
    top.add(gdstk.Reference(sub, (100, 0)))  # referenced cells are expanded
    top.add(gdstk.rectangle((200, 0), (230, 30), layer=3))
    top.add(gdstk.rectangle((205, 5), (215, 15), layer=3))  # same layer, overlapping: united, not a hole
    f = tmp_path / "a.gds"
    lib.write_gds(f)
    result = fileio.import_shapes(f)
    areas = sorted(parse_shape(s).area for s in result.shapes)
    assert areas == pytest.approx(sorted([100, 800, 100, 900]), rel=1e-6)  # µm^2: sub, rect 1, rect 2, rect 3
    xs = [b for s in result.shapes for b in parse_shape(s).bounds]
    assert min(xs) == pytest.approx(-max(xs), abs=0.01)  # centred


def test_csv_import(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("x,y\n0,0\n10,0\n10,5\n\n0,20\n5,20\n")
    result = fileio.import_shapes(f)
    assert [parse_shape(s).geom_type for s in result.shapes] == ["LineString", "LineString"]
    assert list(parse_shape(result.shapes[0]).coords)[1] == (10.0, 0.0)  # taken as microns, not centred


def test_import_errors(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "e.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    for name in ("a.txt", "e.svg"):
        with pytest.raises(ValueError):
            fileio.import_shapes(tmp_path / name)


def _plan():
    shapes = [{"type": "path", "path": "M0,0L100,0L100,50L0,50Z", "op": "add"}]
    params = Params(step=10.0, speed=20.0)
    return build_plan(shapes, params), params


def test_export_formats(tmp_path):
    plan, params = _plan()
    fileio.export_plan(plan, params, tmp_path / "a.csv")
    lines = (tmp_path / "a.csv").read_text().splitlines()
    assert lines[0] == "segment,x_um,y_um,laser,speed_um_s"
    assert len(lines) == 1 + sum(len(s.points) for s in plan)
    fileio.export_plan(plan, params, tmp_path / "a.gcode")
    gcode = (tmp_path / "a.gcode").read_text()
    assert gcode.count("M3") == gcode.count("M5") == len(plan) and "F1.2000" in gcode
    fileio.export_plan(plan, params, tmp_path / "a.npz")
    data = np.load(tmp_path / "a.npz")
    assert data["points"].shape == (sum(len(s.points) for s in plan), 2)
    with pytest.raises(ValueError):
        fileio.export_plan([], params, tmp_path / "b.csv")
    with pytest.raises(ValueError):
        fileio.export_plan(plan, params, tmp_path / "b.pdf")


SHAPES = [
    {"type": "path", "path": "M0,0L4000,0L4000,2000L0,2000Z", "op": "add"},
    {"type": "path", "path": "M1000,500L2000,500L2000,1500L1000,1500Z", "op": "subtract"},
    {"type": "path", "path": "M0,3000L1000,3500", "op": "add"},
]


@pytest.mark.parametrize("suffix", [".svg", ".dxf"])
def test_drawing_export_round_trips_through_import(tmp_path, suffix):
    f = tmp_path / f"a{suffix}"
    fileio.export_drawing(SHAPES, f)
    back = [parse_shape(s) for s in fileio.import_shapes(f).shapes]
    assert sorted(g.geom_type for g in back) == ["LineString", "Polygon"]
    poly = next(g for g in back if g.geom_type == "Polygon")
    assert poly.area == pytest.approx(4000 * 2000 - 1000 * 1000, rel=1e-3)  # the subtraction is applied
    assert len(poly.interiors) == 1
    assert poly.bounds[2] - poly.bounds[0] == pytest.approx(4000, abs=1)  # units survive the trip


def test_svg_export_flips_y_and_uses_millimetres(tmp_path):
    import re

    fileio.export_drawing(SHAPES[:1], tmp_path / "a.svg")  # 4 x 2 mm rectangle with its corner at the origin
    text = (tmp_path / "a.svg").read_text()
    assert re.search(r'width="4\.\d+mm" height="2\.\d+mm"', text) is not None  # plus a small margin
    d = re.search(r'<path d="([^"]+)"', text).group(1)
    ys = [float(y) for y in re.findall(r",(-?[\d.]+)", d)]
    assert max(ys) == 0 and min(ys) == pytest.approx(-2000)  # SVG y points down, so the drawing is at y <= 0


def test_drawing_export_errors(tmp_path):
    with pytest.raises(ValueError, match="Nothing to export"):
        fileio.export_drawing([], tmp_path / "a.svg")
    with pytest.raises(ValueError, match="Unsupported"):
        fileio.export_drawing(SHAPES, tmp_path / "a.pdf")


def _bitmap(tmp_path, suffix=".png"):
    from PIL import Image, ImageDraw

    im = Image.new("L", (400, 300), 255)
    d = ImageDraw.Draw(im)
    d.ellipse((50, 50, 250, 250), fill=0)  # a disc with a bright hole holding a dark island
    d.ellipse((100, 100, 200, 200), fill=255)
    d.ellipse((130, 130, 170, 170), fill=0)
    d.rectangle((300, 50, 380, 100), fill=0)
    f = tmp_path / f"b{suffix}"
    im.save(f)
    return f


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".tif", ".webp"])
def test_bitmap_formats_load(tmp_path, suffix):
    gray = fileio.load_bitmap(_bitmap(tmp_path, suffix))
    assert gray.shape == (300, 400) and gray.dtype == np.uint8
    assert 60 < fileio.otsu_threshold(gray) < 200


def test_bitmap_trace_holes_islands_and_scale(tmp_path):
    gray = fileio.load_bitmap(_bitmap(tmp_path))
    th = fileio.otsu_threshold(gray)
    result = fileio.trace_bitmap(gray, th, invert=False, width_um=4000)  # 10 µm per pixel
    geoms = sorted((parse_shape(s) for s in result.shapes), key=lambda g: -g.area)
    assert len(geoms) == 3  # ring, island inside its hole, rectangle
    ring = geoms[0]
    assert len(ring.interiors) == 1
    px_um2 = 100.0
    assert ring.area == pytest.approx((np.pi * 100**2 - np.pi * 50**2) * px_um2, rel=0.03)
    assert geoms[2].area == pytest.approx(np.pi * 20**2 * px_um2, rel=0.05)
    xs = [b for g in geoms for b in (g.bounds[0], g.bounds[2])]
    assert min(xs) == pytest.approx(-max(xs), abs=1)
    assert "C" in "".join(s["path"] for s in result.shapes)  # curves stay curves
    inverted = fileio.trace_bitmap(gray, th, invert=True, width_um=4000)
    assert max(parse_shape(s).area for s in inverted.shapes) > 3 * ring.area  # the white background


def test_bitmap_options_and_errors(tmp_path):
    gray = fileio.load_bitmap(_bitmap(tmp_path))
    with pytest.raises(ValueError, match="width"):
        fileio.trace_bitmap(gray, 128, False, 0)
    with pytest.raises(ValueError, match="No pixels"):
        fileio.trace_bitmap(gray, 0, False, 1000)
    with pytest.raises(ValueError, match="specks"):
        fileio.trace_bitmap(gray, 128, False, 1000, speckle_px=10**6)
    corners = fileio.trace_bitmap(gray, 128, False, 1000, smoothness=0.0)
    assert "C" not in "".join(s["path"] for s in corners.shapes)  # smoothness 0: straight sides only
    bad = tmp_path / "x.png"
    bad.write_text("not an image")
    with pytest.raises(ValueError, match="image"):
        fileio.load_bitmap(bad)


def test_bitmap_transparency_counts_as_white(tmp_path):
    from PIL import Image

    im = Image.new("RGBA", (100, 100), (0, 0, 0, 0))  # fully transparent black
    im.paste((0, 0, 0, 255), (20, 20, 60, 60))
    f = tmp_path / "t.png"
    im.save(f)
    gray = fileio.load_bitmap(f)
    assert gray[0, 0] == 255 and gray[40, 40] == 0
