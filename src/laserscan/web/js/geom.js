/* Geometry helpers: Bézier maths and the path string format shared with planning.py. Units are microns. */
(function (root) {
  'use strict';

  const KAPPA = 0.5522847498;
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
  const mul = (a, k) => [a[0] * k, a[1] * k];
  const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

  function bezier(p, t) {
    const u = 1 - t;
    return [0, 1].map((d) => u * u * u * p[0][d] + 3 * u * u * t * p[1][d] + 3 * u * t * t * p[2][d] + t * t * t * p[3][d]);
  }

  /** De Casteljau split of a cubic into the control points of its two halves. */
  function split(p, t) {
    const a = lerp(p[0], p[1], t), b = lerp(p[1], p[2], t), c = lerp(p[2], p[3], t);
    const d = lerp(a, b, t), e = lerp(b, c, t), m = lerp(d, e, t);
    return [[p[0], a, d, m], [m, e, c, p[3]]];
  }

  /** A contour is {pts, hin, hout, types}; handles are [x, y] or null. */
  function makeContour(pts, hin, hout, types) {
    const c = { pts: pts.map((p) => p.slice()), hin: (hin || []).map((q) => q && q.slice()), hout: (hout || []).map((q) => q && q.slice()), types: (types || []).slice() };
    fit(c);
    return c;
  }

  function fit(c) {
    const n = c.pts.length;
    for (const key of ['hin', 'hout']) {
      c[key].length = Math.min(c[key].length, n);
      while (c[key].length < n) c[key].push(null);
    }
    c.types.length = Math.min(c.types.length, n);
    while (c.types.length < n) c.types.push('free');
  }

  function copyContour(c) { return makeContour(c.pts, c.hin, c.hout, c.types); }

  function deriveTypes(c) {
    fit(c);
    c.pts.forEach((p, i) => {
      const a = c.hin[i], b = c.hout[i];
      if (!a && !b) c.types[i] = 'sharp';
      else if (!a || !b) c.types[i] = 'free';
      else {
        const u = sub(a, p), v = sub(b, p);
        const lu = Math.hypot(...u), lv = Math.hypot(...v);
        let aligned = lu > 0 && lv > 0 && Math.abs(u[0] * v[1] - u[1] * v[0]) <= 1e-3 * lu * lv;
        aligned = aligned && u[0] * v[0] + u[1] * v[1] < 0;
        c.types[i] = aligned ? (Math.abs(lu - lv) <= 1e-3 * Math.max(lu, lv) ? 'symmetric' : 'smooth') : 'free';
      }
    });
  }

  /** Cubic control points of the segment from node i to node j, or null for a straight side. */
  function segment(c, i, j) {
    const a = c.hout[i], b = c.hin[j];
    if (!a && !b) return null;
    return [c.pts[i], a || c.pts[i], b || c.pts[j], c.pts[j]];
  }

  /** Flatten a contour to a polyline (used for hit tests). */
  function flatten(c, closed, per) {
    per = per || 16;
    const n = c.pts.length, out = [c.pts[0]];
    for (let i = 0; i < (closed ? n : n - 1); i++) {
      const j = (i + 1) % n, seg = segment(c, i, j);
      if (!seg) { out.push(c.pts[j]); continue; }
      for (let k = 1; k <= per; k++) out.push(bezier(seg, k / per));
    }
    return out;
  }

  const TOKEN = /[MLCZmlcz]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?/g;

  /** Parse an absolute M/L/C/Z path string; mirrors planning.parse_nodes. */
  function parseNodes(path) {
    const tokens = path.match(TOKEN) || [];
    const nodes = [];
    let command = 'L', i = 0, closed = false;
    while (i < tokens.length) {
      const token = tokens[i];
      if (/[A-Za-z]/.test(token)) { command = token.toUpperCase(); i++; closed = closed || command === 'Z'; continue; }
      const want = command === 'C' ? 6 : 2;
      const values = tokens.slice(i, i + want).filter((t) => !/[A-Za-z]/.test(t)).map(Number);
      if (values.length < want) break;
      i += want;
      if (command === 'C' && nodes.length) {
        nodes[nodes.length - 1][2] = [values[0], values[1]];
        nodes.push([[values[4], values[5]], [values[2], values[3]], null]);
      } else if ('MLC'.includes(command)) {
        nodes.push([[values[0], values[1]], null, null]);
        if (command === 'M') command = 'L';
      }
    }
    if (closed && nodes.length > 1 && nodes[nodes.length - 1][0][0] === nodes[0][0][0] && nodes[nodes.length - 1][0][1] === nodes[0][0][1]) {
      nodes[0][1] = nodes[nodes.length - 1][1];
      nodes.pop();
    }
    return { nodes, closed };
  }

  function parseContours(path) {
    return path.split(/(?=[Mm])/).filter((s) => s.trim()).map(parseNodes).filter((c) => c.nodes.length >= 2);
  }

  const fmt = (p) => `${p[0].toFixed(4)},${p[1].toFixed(4)}`;

  function formatContour(c, closed) {
    const out = ['M' + fmt(c.pts[0])];
    const n = c.pts.length, count = closed ? n : n - 1;
    for (let i = 0; i < count; i++) {
      const j = (i + 1) % n, a = c.hout[i], b = c.hin[j];
      if (!a && !b) {
        if (!(closed && i === count - 1)) out.push('L' + fmt(c.pts[j]));
      } else {
        out.push('C' + [a || c.pts[i], b || c.pts[j], c.pts[j]].map(fmt).join(' '));
      }
    }
    return out.join('') + (closed ? 'Z' : '');
  }

  function contourFromNodes(nodes) {
    return makeContour(nodes.map((n) => n[0]), nodes.map((n) => n[1]), nodes.map((n) => n[2]));
  }

  let nextId = 1;

  /** A shape: kind 'polygon' (closed) or 'polyline'; contours[0] is the outline, the rest are holes. */
  function makeShape(kind, contours, op) {
    return { id: nextId++, kind, op: kind === 'polygon' ? op || 'add' : 'add', contours, active: 0 };
  }

  /** Build a shape from a planning.parse_shape dictionary (path, or old rect / circle / line). */
  function shapeFromDict(d) {
    const rect = () => { const x0 = Math.min(d.x0, d.x1), x1 = Math.max(d.x0, d.x1), y0 = Math.min(d.y0, d.y1), y1 = Math.max(d.y0, d.y1); return [x0, y0, x1, y1]; };
    if (d.type === 'rect') {
      const [x0, y0, x1, y1] = rect();
      const c = makeContour([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]);
      deriveTypes(c);
      return makeShape('polygon', [c], d.op);
    }
    if (d.type === 'circle') {
      const [x0, y0, x1, y1] = rect();
      const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, rx = (x1 - x0) / 2, ry = (y1 - y0) / 2, k = KAPPA;
      const at = (x, y) => [cx + x * rx, cy + y * ry];
      const c = makeContour([at(1, 0), at(0, 1), at(-1, 0), at(0, -1)],
        [at(1, -k), at(k, 1), at(-1, k), at(-k, -1)], [at(1, k), at(-k, 1), at(-1, -k), at(k, -1)]);
      deriveTypes(c);
      return makeShape('polygon', [c], d.op);
    }
    if (d.type === 'line') {
      const c = makeContour([[d.x0, d.y0], [d.x1, d.y1]]);
      deriveTypes(c);
      return makeShape('polyline', [c]);
    }
    if (d.type === 'path') {
      const parsed = parseContours(d.path);
      if (!parsed.length) return null;
      const first = parsed[0];
      const closed = first.closed && first.nodes.length >= 3;
      const contours = [contourFromNodes(first.nodes)];
      if (closed) for (const h of parsed.slice(1)) if (h.closed && h.nodes.length >= 3) contours.push(contourFromNodes(h.nodes));
      contours.forEach(deriveTypes);
      return makeShape(closed ? 'polygon' : 'polyline', contours, d.op);
    }
    return null;
  }

  function shapeToDict(s) {
    const closed = s.kind === 'polygon';
    const out = { type: 'path', path: s.contours.map((c, k) => formatContour(c, k > 0 || closed)).join('') };
    if (closed) out.op = s.op;
    return out;
  }

  function copyShape(s) {
    const c = makeShape(s.kind, s.contours.map(copyContour), s.op);
    return c;
  }

  /** Distance from point p to segment ab. */
  function distToSegment(p, a, b) {
    const d = sub(b, a), span = d[0] * d[0] + d[1] * d[1];
    const t = span === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / span));
    return dist(p, add(a, mul(d, t)));
  }

  function pointInRings(p, rings) {
    let inside = false;
    for (const ring of rings) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const a = ring[i], b = ring[j];
        if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]) inside = !inside;
      }
    }
    return inside;
  }

  /** Whether segment ab touches the axis-aligned rectangle [x0, y0, x1, y1] (Liang-Barsky). */
  function segmentHitsRect(a, b, r) {
    let t0 = 0, t1 = 1;
    const dx = b[0] - a[0], dy = b[1] - a[1];
    for (const [p, q] of [[-dx, a[0] - r[0]], [dx, r[2] - a[0]], [-dy, a[1] - r[1]], [dy, r[3] - a[1]]]) {
      if (p === 0) { if (q < 0) return false; continue; }
      const t = q / p;
      if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; }
      else { if (t < t0) return false; if (t < t1) t1 = t; }
    }
    return true;
  }

  const api = {
    KAPPA, dist, add, sub, mul, lerp, bezier, split, makeContour, copyContour, deriveTypes, fit, segment, flatten,
    parseNodes, parseContours, formatContour, makeShape, shapeFromDict, shapeToDict, copyShape,
    distToSegment, pointInRings, segmentHitsRect,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Geom = api;
})(typeof window !== 'undefined' ? window : globalThis);
