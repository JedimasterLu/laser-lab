/*
 * Shape model on top of Paper.js (https://paperjs.org): conversion between the project-file path strings and
 * Paper items, and the node operations of the editor. Paper does the Bézier maths (splitting, nearest point,
 * flattening, transforms, hit tests); this file only adds what it does not have: node types and the file format.
 *
 * World coordinates are microns (X, Y) as in the project files and in planning.py. The view shows screen up as +X
 * and screen right as +Y (it matches the microscope camera), so every item lives in Paper's own frame
 * p = (Y, -X): a plain rotation, which keeps Paper's zoom and pan, hit tolerances and stroke widths as they are.
 *
 * A shape is a CompoundPath whose `data` is {kind, op, active}. kind 'polygon' is closed: children[0] is the
 * outline and the rest are holes. kind 'polyline' is one open path. Every child path carries `data.types`, one of
 * 'sharp' | 'free' | 'smooth' | 'symmetric' per segment.
 */
(function (root) {
  'use strict';
  const paper = root.paper || (typeof require !== 'undefined' ? require('paper/dist/paper-core') : null);
  const { Point, Path, CompoundPath, Matrix, Segment } = paper;

  const MIN_NODES = { polygon: 3, polyline: 2 };
  const EPS = 1e-9;
  const FRAME = new Matrix(0, -1, 1, 0, 0, 0); // world (X, Y) -> Paper (Y, -X)

  const toPaper = (p) => new Point(p[1], -p[0]);
  const toWorld = (pt) => [-pt.y, pt.x];

  const hasHandle = (h) => Math.abs(h.x) > EPS || Math.abs(h.y) > EPS;
  const isClosed = (shape, k) => k > 0 || shape.data.kind === 'polygon';

  // ---- node types ---------------------------------------------------------------------------

  /** The type list of a path, kept the same length as its segments. */
  function typesOf(path) {
    const n = path.segments.length;
    if (!path.data) path.data = {};
    const t = (path.data.types = path.data.types || []);
    t.length = Math.min(t.length, n);
    while (t.length < n) t.push('free');
    return t;
  }

  /** Read the node types off the handles: aligned handles are smooth, also of equal length symmetric. */
  function deriveTypes(path) {
    const types = typesOf(path);
    path.segments.forEach((s, i) => {
      const a = s.handleIn, b = s.handleOut, ha = hasHandle(a), hb = hasHandle(b);
      if (!ha && !hb) types[i] = 'sharp';
      else if (!ha || !hb) types[i] = 'free';
      else {
        const la = a.length, lb = b.length;
        const aligned = Math.abs(a.cross(b)) <= 1e-3 * la * lb && a.dot(b) < 0;
        types[i] = aligned ? (Math.abs(la - lb) <= 1e-3 * Math.max(la, lb) ? 'symmetric' : 'smooth') : 'free';
      }
    });
  }

  // ---- project-file format ----------------------------------------------------------------------

  /** Four decimals; a tiny negative number (a rotation's rounding noise) prints as 0, not -0.0000. */
  const num = (v) => { const t = v.toFixed(4); return t === '-0.0000' ? '0.0000' : t; };
  const fmt = (p) => `${num(p[0])},${num(p[1])}`;

  /** Absolute M/L/C/Z string in world coordinates; the format planning.py reads. */
  function formatPath(path, closed) {
    const segs = path.segments, n = segs.length;
    const P = (pt) => fmt(toWorld(pt));
    const out = ['M' + P(segs[0].point)];
    const count = closed ? n : n - 1;
    for (let i = 0; i < count; i++) {
      const a = segs[i], b = segs[(i + 1) % n];
      const ha = hasHandle(a.handleOut), hb = hasHandle(b.handleIn);
      if (!ha && !hb) {
        if (!(closed && i === count - 1)) out.push('L' + P(b.point)); // Z draws the closing side
      } else {
        out.push('C' + [ha ? a.point.add(a.handleOut) : a.point, hb ? b.point.add(b.handleIn) : b.point, b.point].map(P).join(' '));
      }
    }
    return out.join('') + (closed ? 'Z' : '');
  }

  let nextId = 1;

  /** Wrap child paths (already in the Paper frame) as a shape. Not inserted into any layer. */
  function makeShape(kind, paths, op) {
    paths.forEach((p) => { p.closed = isClosed({ data: { kind } }, paths.indexOf(p)); typesOf(p); });
    const shape = new CompoundPath({ children: paths, fillRule: 'evenodd', insert: false });
    shape.data = { id: nextId++, kind, op: kind === 'polygon' ? op || 'add' : 'add', active: 0 };
    return shape;
  }

  function fromWorld(item) { item.transform(FRAME); return item; }

  /** Build a shape from a planning.parse_shape dictionary (path, or the older rect / circle / line). */
  function shapeFromDict(d) {
    const rect = () => [Math.min(d.x0, d.x1), Math.min(d.y0, d.y1), Math.max(d.x0, d.x1), Math.max(d.y0, d.y1)];
    const done = (kind, path) => { deriveTypes(path); return makeShape(kind, [path], d.op); };
    if (d.type === 'rect') {
      const [x0, y0, x1, y1] = rect();
      return done('polygon', fromWorld(new Path.Rectangle({ from: [x0, y0], to: [x1, y1], insert: false })));
    }
    if (d.type === 'circle') {
      const [x0, y0, x1, y1] = rect();
      return done('polygon', fromWorld(new Path.Ellipse({ from: [x0, y0], to: [x1, y1], insert: false })));
    }
    if (d.type === 'line') return done('polyline', fromWorld(new Path.Line({ from: [d.x0, d.y0], to: [d.x1, d.y1], insert: false })));
    if (d.type !== 'path' || typeof d.path !== 'string') return null;

    const parsed = new CompoundPath({ pathData: d.path, insert: false });
    const paths = parsed.children.filter((c) => c.segments.length >= 2);
    if (!paths.length) return null;
    const first = paths[0];
    const closed = first.closed && first.segments.length >= 3;
    const keep = closed ? [first, ...paths.slice(1).filter((c) => c.closed && c.segments.length >= 3)] : [first];
    keep.forEach(deriveTypes);
    const shape = makeShape(closed ? 'polygon' : 'polyline', keep, d.op);
    fromWorld(shape);
    return shape;
  }

  function shapeToDict(shape) {
    const closed = shape.data.kind === 'polygon';
    const out = { type: 'path', path: shape.children.map((c, k) => formatPath(c, k > 0 || closed)).join('') };
    if (closed) out.op = shape.data.op;
    return out;
  }

  /** A copy with the same node types, not inserted into any layer. */
  function copyShape(shape) {
    const c = shape.clone({ insert: false, deep: true });
    c.data = { ...shape.data, id: nextId++, active: 0 };
    c.children.forEach((child, k) => { child.data = { types: typesOf(shape.children[k]).slice() }; });
    return c;
  }

  // ---- node operations (all in the Paper frame) ----------------------------------------------------

  /** Every selected node, with its handles as absolute points, so a transform can be replayed from this copy. */
  function snapshot(path, indices) {
    return indices.map((i) => {
      const s = path.segments[i];
      return { i, point: s.point.clone(), hin: s.point.add(s.handleIn), hout: s.point.add(s.handleOut) };
    });
  }

  /** Put the nodes of a snapshot through `fn` (Point -> Point); handles move with their node. */
  function applySnapshot(path, saved, fn) {
    for (const { i, point, hin, hout } of saved) {
      const s = path.segments[i];
      const moved = fn(point);
      s.point = moved;
      s.handleIn = fn(hin).subtract(moved);
      s.handleOut = fn(hout).subtract(moved);
    }
  }

  function restoreSnapshot(path, saved) { applySnapshot(path, saved, (p) => p); }

  /** Retype the nodes `indices`: sharp drops the handles, the others align them (equal length when symmetric). */
  function setNodeType(path, indices, kind) {
    const types = typesOf(path), segs = path.segments, n = segs.length, closed = path.closed;
    for (const i of indices) {
      const s = segs[i], here = s.point;
      if (kind === 'sharp') { s.handleIn = new Point(0, 0); s.handleOut = new Point(0, 0); }
      else if (kind === 'smooth' || kind === 'symmetric') {
        const prev = closed || i > 0 ? segs[(i - 1 + n) % n].point : null;
        const next = closed || i < n - 1 ? segs[(i + 1) % n].point : null;
        const a = hasHandle(s.handleIn) ? s.handleIn : null, b = hasHandle(s.handleOut) ? s.handleOut : null;
        let tangent;
        if (a && b) tangent = b.subtract(a);
        else if (a || b) tangent = b || a.multiply(-1);
        else tangent = (next || here).subtract(prev || here);
        if (tangent.length > 0) {
          tangent = tangent.normalize();
          let out = b ? b.length : next ? next.getDistance(here) / 3 : null;
          let inn = a ? a.length : prev ? prev.getDistance(here) / 3 : null;
          if (kind === 'symmetric' && out !== null && inn !== null) out = inn = (out + inn) / 2;
          if (out !== null) s.handleOut = tangent.multiply(out);
          if (inn !== null) s.handleIn = tangent.multiply(-inn);
        }
      }
      types[i] = kind;
    }
  }

  /**
   * Drag one handle of node `i` to the absolute point `p`. A paired (smooth or symmetric) node moves the other
   * handle along: opposite direction, equal length if symmetric or if the other handle did not exist.
   */
  function moveControl(path, i, side, p, paired) {
    const types = typesOf(path), s = path.segments[i];
    const mine = side === 'in' ? 'handleIn' : 'handleOut', other = side === 'in' ? 'handleOut' : 'handleIn';
    const away = p.subtract(s.point);
    s[mine] = away;
    if (types[i] === 'sharp') types[i] = 'free';
    if (paired && away.length > 0) {
      const reach = types[i] === 'symmetric' || !hasHandle(s[other]) ? away.length : s[other].length;
      s[other] = away.normalize().multiply(-reach);
    }
  }

  /** Insert a node on the curve nearest to `point` (within `tolerance`); returns its index or null. */
  function insertNode(path, point, tolerance) {
    const loc = path.getNearestLocation(point);
    if (!loc || loc.distance > tolerance) return null;
    const seg = path.divideAt(loc);
    if (!seg) return null;
    const types = typesOf(path);
    types.splice(seg.index, 0, hasHandle(seg.handleIn) ? 'smooth' : 'free');
    types.length = path.segments.length;
    return seg.index;
  }

  /** Delete nodes unless fewer than `min` would remain; returns whether it did. */
  function deleteNodes(path, indices, min) {
    if (path.segments.length - new Set(indices).size < min) return false;
    const types = typesOf(path);
    [...new Set(indices)].sort((a, b) => b - a).forEach((i) => { path.removeSegment(i); types.splice(i, 1); });
    return true;
  }

  /** Add a sharp twin after each chosen node (before the first node of an open path); returns the twins' indices. */
  function extrudeNodes(path, chosen) {
    const types = typesOf(path), closed = path.closed;
    const out = [], created = [];
    const spawn = (s) => { created.push(out.length); out.push([new Segment(s.point.clone()), 'sharp']); };
    path.segments.slice().forEach((s, i) => {
      if (chosen.has(i) && !closed && i === 0) spawn(s);
      out.push([new Segment(s.point.clone(), s.handleIn.clone(), s.handleOut.clone()), types[i]]);
      if (chosen.has(i) && (closed || i > 0)) spawn(s);
    });
    path.segments = out.map((o) => o[0]);
    path.data.types = out.map((o) => o[1]);
    return created;
  }

  /** Path for a ring of world points (the scan region from planning.py), in the Paper frame. */
  function ringPath(ring) {
    return new Path({ segments: ring.map(toPaper), closed: true, insert: false });
  }

  const api = {
    MIN_NODES, FRAME, toPaper, toWorld, hasHandle, isClosed, typesOf, deriveTypes, formatPath, makeShape,
    shapeFromDict, shapeToDict, copyShape, snapshot, applySnapshot, restoreSnapshot, setNodeType, moveControl,
    insertNode, deleteNodes, extrudeNodes, ringPath,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Shapes = api;
})(typeof window !== 'undefined' ? window : globalThis);
