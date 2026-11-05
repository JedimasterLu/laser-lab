"""Path boolean operations that return node outlines. Uses skia-python (curves stay curves) if installed, else Qt (curves are flattened)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath

try:
    import skia
except ImportError:  # optional dependency
    skia = None

Outline = tuple[list[QPointF], list[QPointF | None], list[QPointF | None]]
"""Anchors, incoming handles and outgoing handles of one closed outline."""


def _close(a: QPointF, b: QPointF) -> bool:
    return math.hypot(a.x() - b.x(), a.y() - b.y()) < 1e-6


def _outlines(raw: list[list]) -> list[Outline]:
    """Turn ``[[anchor, hin, hout], ...]`` lists into closed outlines, dropping the repeated start point."""
    result = []
    for nodes in raw:
        if len(nodes) > 1 and _close(nodes[0][0], nodes[-1][0]):
            nodes[0][1] = nodes[-1][1]
            nodes.pop()
        nodes = [n for k, n in enumerate(nodes) if k == 0 or not _close(n[0], nodes[k - 1][0])]
        if len(nodes) >= 3:
            result.append(([n[0] for n in nodes], [n[1] for n in nodes], [n[2] for n in nodes]))
    return result


def _from_qt(path: QPainterPath) -> list[Outline]:
    raw: list[list] = []
    for k in range(path.elementCount()):
        e = path.elementAt(k)
        if e.type == QPainterPath.MoveToElement:
            raw.append([[QPointF(e.x, e.y), None, None]])
        elif e.type == QPainterPath.LineToElement:
            raw[-1].append([QPointF(e.x, e.y), None, None])
        elif e.type == QPainterPath.CurveToElement:
            c2, end = path.elementAt(k + 1), path.elementAt(k + 2)
            raw[-1][-1][2] = QPointF(e.x, e.y)
            raw[-1].append([QPointF(end.x, end.y), QPointF(c2.x, c2.y), None])
    return _outlines(raw)


def _to_skia(path: QPainterPath):
    out = skia.Path()
    k = 0
    while k < path.elementCount():
        e = path.elementAt(k)
        if e.type == QPainterPath.MoveToElement:
            if k:
                out.close()
            out.moveTo(e.x, e.y)
        elif e.type == QPainterPath.LineToElement:
            out.lineTo(e.x, e.y)
        elif e.type == QPainterPath.CurveToElement:
            c2, end = path.elementAt(k + 1), path.elementAt(k + 2)
            out.cubicTo(e.x, e.y, c2.x, c2.y, end.x, end.y)
            k += 2
        k += 1
    out.close()
    return out


def _from_skia(path) -> list[Outline]:
    raw: list[list] = []

    def pt(p) -> QPointF:
        return QPointF(p.x(), p.y())

    def cubic(c1: QPointF, c2: QPointF, end: QPointF) -> None:
        raw[-1][-1][2] = c1
        raw[-1].append([end, c2, None])

    it = skia.Path.Iter(path, False)
    for verb, pts in it:
        if verb == skia.Path.kMove_Verb:
            raw.append([[pt(pts[0]), None, None]])
        elif verb == skia.Path.kLine_Verb:
            raw[-1].append([pt(pts[1]), None, None])
        elif verb == skia.Path.kCubic_Verb:
            cubic(pt(pts[1]), pt(pts[2]), pt(pts[3]))
        elif verb in (skia.Path.kQuad_Verb, skia.Path.kConic_Verb):
            if verb == skia.Path.kConic_Verb:
                quads = skia.Path.ConvertConicToQuads(pts[0], pts[1], pts[2], it.conicWeight(), 1)
            else:
                quads = [pts[0], pts[1], pts[2]]
            for q in range(0, len(quads) - 1, 2):
                a, b, c = pt(quads[q]), pt(quads[q + 1]), pt(quads[q + 2])
                cubic(a + (b - a) * (2 / 3), c + (b - c) * (2 / 3), c)
    return _outlines(raw)


def subtract(target: QPainterPath, blade: QPainterPath) -> list[Outline]:
    """Return the outlines of ``target`` minus ``blade``."""
    if skia is not None:
        return _from_skia(skia.Op(_to_skia(target), _to_skia(blade), skia.PathOp.kDifference_PathOp))
    target.setFillRule(Qt.WindingFill)
    return _from_qt(target.subtracted(blade))
