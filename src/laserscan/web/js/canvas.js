/*
 * Drawing canvas: grid, snapping, selection, Bézier nodes, modal transforms, undo, and the preview / monitor overlay.
 *
 * World coordinates are microns (X, Y). The view is rotated to match the microscope camera:
 * screen up is +X and screen right is +Y.
 */
(function (root) {
  'use strict';
  const G = root.Geom;
  const NS = 'http://www.w3.org/2000/svg';
  const PICK_PX = 8, GRID_PX = 12, GHOST_PX = 16, ZOOM = [1e-4, 200];
  const INK = '#0b0b0b', RED = '#c0392b', BLUE = '#8b5a2b';
  const MIN_NODES = { polygon: 3, polyline: 2 };

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  class Canvas {
    /**
     * @param {HTMLElement} wrap Container holding the canvas and svg elements.
     * @param {object} hooks Callbacks: changed, message, cursor, editChanged, toolChanged, selectionChanged, merge, apply.
     */
    constructor(wrap, hooks) {
      this.wrap = wrap;
      this.hooks = hooks;
      this.grid = document.createElement('canvas');
      this.svg = document.createElementNS(NS, 'svg');
      this.svg.setAttribute('tabindex', '0');
      wrap.append(this.grid, this.svg);
      this.mode = 'design';
      this.tool = 'select';
      this.newOp = 'add';
      this.penType = 'symmetric';
      this.snapOn = true;
      this.shapes = [];
      this.sel = new Set();
      this.editing = null;
      this.selNodes = new Set();
      this.draft = null;
      this.penDrag = null;
      this.xform = null;
      this.drag = null;
      this.rubber = null;
      this.pan = null;
      this.stage = { x: [0, 114000], y: [0, 75000] };
      this.region = [];
      this.preview = null;
      this.progress = [];
      this.progressAt = [0, -1];
      this.marker = null;
      this.pointer = [0, 0];
      this.indicator = null;
      this.views = {};
      this.view = { s: 0.01, ox: 0, oy: 0 };
      this.history = ['[]'];
      this.hidx = 0;
      this.locked = false;
      this._frame = 0;
      this._bind();
      new ResizeObserver(() => { this.size(); this.render(); }).observe(wrap);
      this.size();
      this.fit();
    }

    // ---- view -------------------------------------------------------------

    size() {
      const r = this.wrap.getBoundingClientRect();
      this.W = Math.max(1, r.width);
      this.H = Math.max(1, r.height);
      const dpr = window.devicePixelRatio || 1;
      this.grid.width = Math.round(this.W * dpr);
      this.grid.height = Math.round(this.H * dpr);
    }

    w2s(p) { return [this.view.ox + this.view.s * p[1], this.view.oy - this.view.s * p[0]]; }
    s2w(x, y) { return [(this.view.oy - y) / this.view.s, (x - this.view.ox) / this.view.s]; }
    get zoom() { return this.view.s; }

    gridStep() {
      const target = GRID_PX / this.view.s;
      const exp = Math.floor(Math.log10(target));
      for (const f of [1, 2, 5, 10]) if (f * 10 ** exp >= target) return Math.max(1, f * 10 ** exp);
      return 1;
    }

    fitRect(x0, x1, y0, y1) {
      const w = Math.max(y1 - y0, 20), h = Math.max(x1 - x0, 20);
      let s = 0.88 * Math.min(this.W / w, this.H / h);
      s = Math.min(Math.max(s, ZOOM[0]), ZOOM[1]);
      const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
      this.view = { s, ox: this.W / 2 - s * cy, oy: this.H / 2 + s * cx };
      this.render();
    }

    fit() {
      let box;
      if (this.mode === 'design') {
        const pts = this.shapes.flatMap((sh) => sh.contours.flatMap((c) => c.pts));
        box = pts.length ? bounds(pts) : [-325, 325, -500, 500];
      } else if (this.preview && this.preview.bounds) {
        box = this.preview.bounds.slice();
        if (this.preview.exceeds) box = [Math.min(box[0], this.stage.x[0]), Math.max(box[1], this.stage.x[1]), Math.min(box[2], this.stage.y[0]), Math.max(box[3], this.stage.y[1])];
      } else box = [this.stage.x[0], this.stage.x[1], this.stage.y[0], this.stage.y[1]];
      this.fitRect(...box);
    }

    fitStage() { this.fitRect(this.stage.x[0], this.stage.x[1], this.stage.y[0], this.stage.y[1]); }

    setMode(mode) {
      if (mode === this.mode) return;
      this.views[this.mode] = this.view;
      this.mode = mode;
      if (mode !== 'design') { this.exitEdit(true); this.cancelDraft(); this.xform = null; }
      if (mode === 'design' && this.views.design) { this.view = this.views.design; this.render(); }
      else if (mode === 'monitor' && this.views.preview) { this.view = this.views.preview; this.render(); }
      else this.fit();
    }

    setStage(x0, x1, y0, y1) { this.stage = { x: [x0, x1], y: [y0, y1] }; this.render(); }

    // ---- model ------------------------------------------------------------

    dicts() { return this.shapes.map(G.shapeToDict); }

    setShapes(dicts, record) {
      this.cancelDraft();
      this.exitEdit(true);
      this.shapes = dicts.map(G.shapeFromDict).filter(Boolean);
      this.sel.clear();
      this.selNodes.clear();
      if (record) this.commit();
      else this.render();
    }

    commit() {
      const now = JSON.stringify(this.dicts());
      if (now !== this.history[this.hidx]) {
        this.history = this.history.slice(0, this.hidx + 1).concat(now);
        this.hidx++;
      }
      this.hooks.changed();
      this.render();
    }

    restoreHistory() {
      this.cancelDraft();
      this.exitEdit(true);
      this.shapes = JSON.parse(this.history[this.hidx]).map(G.shapeFromDict).filter(Boolean);
      this.sel.clear();
      this.selNodes.clear();
      this.hooks.changed();
      this.render();
    }

    undo() { if (this.mode === 'design' && !this.locked && this.hidx > 0) { this.hidx--; this.restoreHistory(); } }
    redo() { if (this.mode === 'design' && !this.locked && this.hidx < this.history.length - 1) { this.hidx++; this.restoreHistory(); } }

    setRegion(rings) { this.region = rings; this.render(); }

    /** Show the scan plan. `plan` is [{pts, laser, bad}] already in absolute microns. */
    setPreview(data) { this.preview = data; this.render(); }

    clearProgress() { this.progress = []; this.progressAt = [0, -1]; this.render(); }

    setProgress(seg, pt) {
      const plan = this.preview && this.preview.plan;
      if (!plan) return;
      let [i, j] = this.progressAt;
      while ((i !== seg || j !== pt) && i < plan.length) {
        if (j + 1 < plan[i].pts.length) {
          j++;
          const p = plan[i].pts[j];
          if (j > 0 && plan[i].laser && this.progress.length) this.progress[this.progress.length - 1].push(p);
          else this.progress.push([p]);
        } else { i++; j = -1; }
      }
      this.progressAt = [i, j];
      this.render();
    }

    setMarker(p) { this.marker = p; this.render(); }

    // ---- selection helpers ---------------------------------------------------

    selectedShapes() { return this.editing ? [this.editing] : this.shapes.filter((s) => this.sel.has(s)); }

    setSelection(list) { this.sel = new Set(list); this.hooks.selectionChanged(); this.render(); }

    setNewOp(op) { this.newOp = op; }

    /** Type of the nodes placed next with the pen tool: dragging pulls handles of that kind. */
    setPenType(kind) { this.penType = kind; this.hooks.toolChanged(this.tool); }

    applyOp(op) {
      for (const s of this.selectedShapes()) if (s.kind === 'polygon') s.op = op;
      this.commit();
    }

    setTool(tool) {
      if (tool !== 'select') this.exitEdit();
      this.cancelDraft();
      this.tool = tool;
      this.hooks.toolChanged(tool);
      this.svg.style.cursor = tool === 'pen' && this.mode === 'design' ? 'crosshair' : 'default';
      this.render();
    }

    pickTool() { if (this.mode === 'design') this.setTool(this.tool === 'select' ? 'pen' : 'select'); }

    selectAll() {
      if (this.mode !== 'design') return;
      if (this.editing) this.selNodes = new Set(this.editing.contours[this.editing.active].pts.keys());
      else this.sel = new Set(this.shapes);
      this.hooks.selectionChanged();
      this.render();
    }

    deselectAll() { this.sel.clear(); this.selNodes.clear(); this.hooks.selectionChanged(); this.render(); }

    invertSelection() {
      if (this.mode !== 'design') return;
      if (this.editing) {
        const all = this.editing.contours[this.editing.active].pts.keys();
        this.selNodes = new Set([...all].filter((i) => !this.selNodes.has(i)));
      } else this.sel = new Set(this.shapes.filter((s) => !this.sel.has(s)));
      this.hooks.selectionChanged();
      this.render();
    }

    deleteSelected() {
      if (this.mode !== 'design' || this.xform || this.locked) return;
      if (this.editing) {
        const sh = this.editing;
        if (this.selNodes.size) {
          if (!this.deleteNodes(sh, [...this.selNodes])) {
            this.hooks.message(`A ${sh.kind} needs at least ${MIN_NODES[sh.kind]} nodes. Leave Edit mode (Tab) to delete the whole shape.`, true);
          }
        }
        this.commit();
        return;
      }
      this.shapes = this.shapes.filter((s) => !this.sel.has(s));
      this.sel.clear();
      this.hooks.selectionChanged();
      this.commit();
    }

    duplicate() {
      const chosen = this.selectedShapes();
      if (this.mode !== 'design' || this.editing || this.xform || !chosen.length) return;
      const copies = chosen.map((s) => { const c = G.copyShape(s); this.shapes.push(c); return c; });
      this.sel = new Set(copies);
      this.hooks.selectionChanged();
      this.commit();
      this.startTransform('grab');
    }

    invertOp() {
      const sel = this.selectedShapes();
      if (this.mode === 'design' && sel.length) this.applyOp(sel[0].op === 'subtract' ? 'add' : 'subtract');
    }

    // ---- edit mode -------------------------------------------------------------

    enterEdit() {
      if (this.mode !== 'design' || this.draft || this.xform || this.locked) return false;
      if (this.editing) return true;
      const chosen = this.selectedShapes();
      if (chosen.length !== 1) { this.hooks.message('Select one shape first, then press Tab to edit its nodes.', false); return false; }
      this.setTool('select');
      this.editing = chosen[0];
      this.editing.active = 0;
      this.sel.clear();
      this.selNodes.clear();
      this.hooks.editChanged(true);
      this.render();
      return true;
    }

    exitEdit(silent) {
      const sh = this.editing;
      if (!sh) return;
      this.editing = null;
      this.selNodes.clear();
      sh.active = 0;
      if (!silent) { this.sel = new Set([sh]); this.commit(); }
      this.hooks.editChanged(false);
      this.hooks.selectionChanged();
      this.render();
    }

    toggleEdit() { if (this.editing) this.exitEdit(); else this.enterEdit(); }

    get contour() { return this.editing && this.editing.contours[this.editing.active]; }

    moveNode(sh, c, i, p) {
      const d = G.sub(p, c.pts[i]);
      c.pts[i] = p;
      for (const h of [c.hin, c.hout]) if (h[i]) h[i] = G.add(h[i], d);
    }

    moveControl(c, i, side, p, paired) {
      const [mine, other] = side === 'in' ? [c.hin, c.hout] : [c.hout, c.hin];
      mine[i] = p;
      if (c.types[i] === 'sharp') c.types[i] = 'free';
      if (paired) {
        const away = G.sub(p, c.pts[i]), len = Math.hypot(...away);
        if (len > 0) {
          const reach = c.types[i] === 'symmetric' || !other[i] ? len : G.dist(other[i], c.pts[i]);
          other[i] = G.sub(c.pts[i], G.mul(away, reach / len));
        }
      }
    }

    setNodeType(kind) {
      const sh = this.editing;
      if (!sh) return;
      if (!this.selNodes.size) { this.hooks.message('Select one or more nodes first.', false); return; }
      const c = this.contour, n = c.pts.length, closed = sh.kind === 'polygon';
      for (const i of this.selNodes) {
        const here = c.pts[i];
        if (kind === 'sharp') c.hin[i] = c.hout[i] = null;
        else if (kind === 'smooth' || kind === 'symmetric') {
          const prev = closed || i > 0 ? c.pts[(i - 1 + n) % n] : null;
          const next = closed || i < n - 1 ? c.pts[(i + 1) % n] : null;
          const a = c.hin[i], b = c.hout[i];
          let tangent;
          if (a && b) tangent = G.sub(b, a);
          else if (a || b) tangent = b ? G.sub(b, here) : G.sub(here, a);
          else tangent = G.sub(next || here, prev || here);
          const norm = Math.hypot(...tangent);
          if (norm > 0) {
            tangent = G.mul(tangent, 1 / norm);
            let out = b ? G.dist(b, here) : next ? G.dist(next, here) / 3 : null;
            let inn = a ? G.dist(a, here) : prev ? G.dist(prev, here) / 3 : null;
            if (kind === 'symmetric' && out !== null && inn !== null) out = inn = (out + inn) / 2;
            if (out !== null) c.hout[i] = G.add(here, G.mul(tangent, out));
            if (inn !== null) c.hin[i] = G.sub(here, G.mul(tangent, inn));
          }
        }
        c.types[i] = kind;
      }
      this.commit();
    }

    deleteNodes(sh, idx) {
      const c = sh.contours[sh.active];
      const keep = new Set(idx);
      if (c.pts.length - keep.size < MIN_NODES[sh.kind]) return false;
      const pick = (arr) => arr.filter((_, i) => !keep.has(i));
      c.pts = pick(c.pts); c.hin = pick(c.hin); c.hout = pick(c.hout); c.types = pick(c.types);
      this.selNodes.clear();
      return true;
    }

    extrude() {
      const sh = this.editing;
      if (!sh || this.xform) return;
      if (!this.selNodes.size) { this.hooks.message('Select one or more nodes to extrude.', false); return; }
      const c = this.contour, closed = sh.kind === 'polygon', chosen = this.selNodes;
      const out = [], created = [];
      const spawn = (p) => { created.push(out.length); out.push([p.slice(), null, null, 'sharp']); };
      c.pts.forEach((p, i) => {
        if (chosen.has(i) && !closed && i === 0) spawn(p);
        out.push([p, c.hin[i], c.hout[i], c.types[i]]);
        if (chosen.has(i) && (closed || i > 0)) spawn(p);
      });
      c.pts = out.map((o) => o[0]); c.hin = out.map((o) => o[1]); c.hout = out.map((o) => o[2]); c.types = out.map((o) => o[3]);
      this.selNodes = new Set(created);
      this.startTransform('grab', true);
    }

    insertNode(sh, c, wp, tolerance) {
      const n = c.pts.length, closed = sh.kind === 'polygon' || sh.active > 0;
      let best = null;
      for (let i = 0; i < (closed ? n : n - 1); i++) {
        const j = (i + 1) % n, seg = G.segment(c, i, j);
        let t, at;
        if (!seg) {
          const d = G.sub(c.pts[j], c.pts[i]), span = d[0] * d[0] + d[1] * d[1];
          t = span === 0 ? 0 : Math.max(0, Math.min(1, ((wp[0] - c.pts[i][0]) * d[0] + (wp[1] - c.pts[i][1]) * d[1]) / span));
          at = (tt) => G.add(c.pts[i], G.mul(d, tt));
        } else {
          let bt = 0, bd = Infinity;
          for (let k = 0; k <= 64; k++) { const dd = G.dist(G.bezier(seg, k / 64), wp); if (dd < bd) { bd = dd; bt = k / 64; } }
          let lo = Math.max(0, bt - 1 / 64), hi = Math.min(1, bt + 1 / 64);
          for (let k = 0; k < 24; k++) {
            const m1 = lo + (hi - lo) / 3, m2 = hi - (hi - lo) / 3;
            if (G.dist(G.bezier(seg, m1), wp) < G.dist(G.bezier(seg, m2), wp)) hi = m2; else lo = m1;
          }
          t = (lo + hi) / 2;
          at = (tt) => G.bezier(seg, tt);
        }
        const d = G.dist(at(t), wp);
        if (!best || d < best[0]) best = [d, i, j, t];
      }
      if (!best || best[0] > tolerance) return null;
      const [, i, j, t] = best;
      const seg = G.segment(c, i, j);
      let anchor, nin = null, nout = null;
      if (!seg) anchor = G.lerp(c.pts[i], c.pts[j], t);
      else {
        const [left, right] = G.split(seg, t);
        anchor = left[3]; nin = left[2]; nout = right[1];
        c.hout[i] = left[1]; c.hin[j] = right[2];
      }
      c.pts.splice(i + 1, 0, anchor);
      c.hin.splice(i + 1, 0, nin);
      c.hout.splice(i + 1, 0, nout);
      c.types.splice(i + 1, 0, nin ? 'smooth' : 'free');
      return i + 1;
    }

    // ---- modal transforms (G / R / S) ------------------------------------------

    get transforming() { return !!this.xform; }

    startTransform(mode, extrude) {
      if (this.mode !== 'design' || this.xform || this.draft || this.locked) return;
      let targets;
      if (this.editing) {
        targets = this.selNodes.size ? [[this.editing, this.editing.active, [...this.selNodes]]] : [];
      } else {
        targets = this.selectedShapes().flatMap((s) => s.contours.map((c, k) => [s, k, [...c.pts.keys()]]));
      }
      if (!targets.length) { this.hooks.message('Select something first.', false); return; }
      const items = targets.map(([s, k, idx]) => {
        const c = s.contours[k];
        return { s, k, idx, saved: { pts: c.pts.map((p) => p.slice()), hin: c.hin.map((q) => q && q.slice()), hout: c.hout.map((q) => q && q.slice()) } };
      });
      const anchors = items.flatMap((it) => it.idx.map((i) => it.saved.pts[i]));
      const pivot = [anchors.reduce((a, p) => a + p[0], 0) / anchors.length, anchors.reduce((a, p) => a + p[1], 0) / anchors.length];
      this.xform = { mode, items, pivot, start: this.s2w(...this.pointer), probe: anchors[0], axis: null, extrude: !!extrude };
      this.hooks.message({ grab: 'Grab', rotate: 'Rotate', scale: 'Scale' }[mode] +
        ': move the mouse, click or Enter to confirm, Esc or right-click to cancel, X / Y to lock an axis.', false);
    }

    setAxis(axis) {
      if (!this.xform) return;
      this.xform.axis = this.xform.axis === axis ? null : axis;
      this.updateTransform(this.s2w(...this.pointer));
    }

    updateTransform(cursor) {
      const x = this.xform, { pivot, start, axis } = x;
      let move;
      if (x.mode === 'grab') {
        let delta = G.sub(cursor, start);
        if (this.snapOn) {
          const moving = new Set(x.items.map((it) => it.s));
          delta = G.sub(this.snap(G.add(x.probe, delta), moving), x.probe);
        }
        if (axis === 'x') delta[1] = 0; else if (axis === 'y') delta[0] = 0;
        move = (p) => G.add(p, delta);
      } else if (x.mode === 'scale') {
        const r0 = G.dist(start, pivot), r1 = G.dist(cursor, pivot);
        const k = r0 > 1e-9 ? r1 / r0 : 1;
        const kx = axis === 'y' ? 1 : k, ky = axis === 'x' ? 1 : k;
        move = (p) => [pivot[0] + (p[0] - pivot[0]) * kx, pivot[1] + (p[1] - pivot[1]) * ky];
      } else {
        const turn = Math.atan2(cursor[1] - pivot[1], cursor[0] - pivot[0]) - Math.atan2(start[1] - pivot[1], start[0] - pivot[0]);
        const cos = Math.cos(turn), sin = Math.sin(turn);
        move = (p) => { const dx = p[0] - pivot[0], dy = p[1] - pivot[1]; return [pivot[0] + dx * cos - dy * sin, pivot[1] + dx * sin + dy * cos]; };
      }
      for (const { s, k, idx, saved } of x.items) {
        const c = s.contours[k];
        for (const i of idx) {
          c.pts[i] = move(saved.pts[i]);
          c.hin[i] = saved.hin[i] && move(saved.hin[i]);
          c.hout[i] = saved.hout[i] && move(saved.hout[i]);
        }
      }
      this.render();
    }

    finishTransform(confirm) {
      const x = this.xform;
      this.xform = null;
      if (!x) return;
      if (!confirm && x.extrude) { this.restoreHistory(); return; }
      if (!confirm) {
        for (const { s, k, idx, saved } of x.items) {
          const c = s.contours[k];
          for (const i of idx) { c.pts[i] = saved.pts[i]; c.hin[i] = saved.hin[i]; c.hout[i] = saved.hout[i]; }
        }
      }
      this.commit();
    }

    // ---- snapping --------------------------------------------------------------

    snap(p, exclude) {
      if (!this.snapOn) return p.slice();
      const reach = (PICK_PX * 2) / this.view.s;
      let best = null, bd = Infinity;
      for (const s of this.shapes) {
        if (exclude && exclude.has(s)) continue;
        for (const c of s.contours) for (const q of c.pts) { const d = G.dist(q, p); if (d < bd) { bd = d; best = q; } }
      }
      if (best && bd <= reach) return best.slice();
      const step = this.gridStep();
      return [Math.round(p[0] / step) * step, Math.round(p[1] / step) * step];
    }

    // ---- hit testing -------------------------------------------------------------

    rings(sh) { return sh.contours.map((c, k) => G.flatten(c, k > 0 || sh.kind === 'polygon').map((p) => this.w2s(p))); }

    hitShape(sp) {
      let best = null, bd = PICK_PX;
      for (let n = this.shapes.length - 1; n >= 0; n--) {
        const sh = this.shapes[n];
        const rings = this.rings(sh);
        let d = Infinity;
        rings.forEach((r, k) => {
          const closed = k > 0 || sh.kind === 'polygon';
          for (let i = 0; i < r.length - 1; i++) d = Math.min(d, G.distToSegment(sp, r[i], r[i + 1]));
          if (closed && r.length > 1) d = Math.min(d, G.distToSegment(sp, r[r.length - 1], r[0]));
        });
        if (sh.kind === 'polygon' && G.pointInRings(sp, rings)) d = 0;
        if (d < bd || (d === 0 && bd > 0)) { bd = d; best = sh; if (d === 0) break; }
      }
      return best;
    }

    hitNode(sp) {
      const c = this.contour;
      if (!c) return null;
      let best = null, bd = PICK_PX + 2;
      c.pts.forEach((p, i) => { const d = G.dist(this.w2s(p), sp); if (d <= bd) { bd = d; best = i; } });
      return best;
    }

    controlPoints() {
      const sh = this.editing;
      if (!sh) return [];
      const c = this.contour, n = c.pts.length, closed = sh.kind === 'polygon' || sh.active > 0;
      const out = [];
      for (const i of this.selNodes) {
        for (const [side, handles, j, exists] of [['in', c.hin, i - 1, closed || i > 0], ['out', c.hout, i + 1, closed || i < n - 1]]) {
          if (!exists) continue;
          if (handles[i]) { out.push({ i, side, p: handles[i], ghost: false }); continue; }
          const toward = G.sub(c.pts[(j + n) % n], c.pts[i]);
          const norm = Math.hypot(...toward) || 1;
          out.push({ i, side, p: G.add(c.pts[i], G.mul(toward, GHOST_PX / this.view.s / norm)), ghost: true });
        }
      }
      return out;
    }

    hitControl(sp) {
      return this.controlPoints().find((c) => G.dist(this.w2s(c.p), sp) <= PICK_PX) || null;
    }

    contourAt(sp) {
      const sh = this.editing;
      for (let k = 0; k < sh.contours.length; k++) {
        if (k === sh.active) continue;
        const r = G.flatten(sh.contours[k], k > 0 || sh.kind === 'polygon').map((p) => this.w2s(p));
        for (let i = 0; i < r.length; i++) if (G.distToSegment(sp, r[i], r[(i + 1) % r.length]) <= PICK_PX) return k;
      }
      return null;
    }

    // ---- pen tool -----------------------------------------------------------------

    cancelDraft() { this.draft = null; this.penDrag = null; }

    finishDraft(trailing) {
      const d = this.draft;
      this.draft = null;
      this.penDrag = null;
      if (!d) return;
      const c = d.contours[0];
      if (trailing && d.kind === 'polyline') { c.pts.pop(); c.hin.pop(); c.hout.pop(); c.types.pop(); }
      if (c.pts.length < (d.kind === 'polygon' ? 3 : 2)) { this.render(); return; }
      G.fit(c);
      this.shapes.push(d);
      const closed = d.kind === 'polygon';
      const merge = this.newOp === 'merge' && closed;
      this.setTool('select');
      this.sel = new Set([d]);
      this.commit();
      if (merge) this.hooks.merge(this.dicts(), this.shapes.length - 1);
      else if (this.shapes.includes(d)) this.enterEdit();
    }

    penPress(wp, sp) {
      const op = this.newOp === 'merge' ? 'add' : this.newOp;
      const point = this.snap(wp);
      if (this.draft) {
        const c = this.draft.contours[0];
        if (c.pts.length >= 4 && G.dist(c.pts[0], point) <= (PICK_PX * 2) / this.view.s) {
          for (const k of ['pts', 'hin', 'hout', 'types']) c[k].pop();
          this.draft.kind = 'polygon';
          this.draft.op = op;
          this.finishDraft(false);
          return;
        }
        c.pts[c.pts.length - 1] = point;
        c.pts.push(point.slice()); c.hin.push(null); c.hout.push(null); c.types.push('sharp');
        this.penDrag = c.pts.length - 2;
      } else {
        const c = G.makeContour([point, point], [], [], ['sharp', 'sharp']);
        this.draft = G.makeShape('polyline', [c], op);
        this.draft.pendingOp = op;
        this.penDrag = 0;
      }
      this.render();
    }

    // ---- rubber band -----------------------------------------------------------------

    finishRubber(add) {
      const r = this.rubber;
      this.rubber = null;
      if (!r) return;
      const rect = [Math.min(r.a[0], r.b[0]), Math.min(r.a[1], r.b[1]), Math.max(r.a[0], r.b[0]), Math.max(r.a[1], r.b[1])];
      if (rect[2] - rect[0] < 3 && rect[3] - rect[1] < 3) { if (!add) this.deselectAll(); this.render(); return; }
      if (this.editing) {
        const c = this.contour, hit = [];
        c.pts.forEach((p, i) => { const q = this.w2s(p); if (q[0] >= rect[0] && q[0] <= rect[2] && q[1] >= rect[1] && q[1] <= rect[3]) hit.push(i); });
        this.selNodes = add ? new Set([...this.selNodes, ...hit]) : new Set(hit);
      } else {
        const hit = this.shapes.filter((sh) => this.rings(sh).some((r2, k) => {
          const closed = k > 0 || sh.kind === 'polygon';
          for (let i = 0; i < r2.length - (closed ? 0 : 1); i++) if (G.segmentHitsRect(r2[i], r2[(i + 1) % r2.length], rect)) return true;
          return false;
        }));
        this.sel = add ? new Set([...this.sel, ...hit]) : new Set(hit);
      }
      this.hooks.selectionChanged();
      this.render();
    }

    // ---- events -----------------------------------------------------------------------

    _bind() {
      const svg = this.svg;
      const local = (e) => { const r = svg.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
      svg.addEventListener('contextmenu', (e) => e.preventDefault());
      svg.addEventListener('pointerenter', () => { const a = document.activeElement; if (!a || !/INPUT|TEXTAREA|SELECT/.test(a.tagName)) svg.focus({ preventScroll: true }); });

      svg.addEventListener('pointerdown', (e) => {
        svg.focus({ preventScroll: true });
        try { svg.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events have no active pointer */ }
        const sp = local(e), wp = this.s2w(...sp);
        this.pointer = sp;
        if (this.xform) { if (e.button === 0 || e.button === 2) this.finishTransform(e.button === 0); return; }
        if (e.button === 1 || (this.mode !== 'design' && e.button === 0)) { this.pan = { from: sp, view: { ...this.view } }; svg.style.cursor = 'grabbing'; return; }
        if (this.mode !== 'design' || this.locked) return;
        if (e.button === 2) { if (this.draft) this.finishDraft(true); return; }
        if (e.button !== 0) return;
        if (this.tool === 'pen') { this.penPress(wp, sp); return; }
        if (this.editing) {
          const ctl = this.hitControl(sp);
          if (ctl) {
            const c = this.contour;
            if (e.altKey && ['smooth', 'symmetric'].includes(c.types[ctl.i])) c.types[ctl.i] = 'free';
            this.drag = { kind: 'control', i: ctl.i, side: ctl.side, paired: ['smooth', 'symmetric'].includes(c.types[ctl.i]), offset: G.sub(ctl.p, wp) };
            return;
          }
          const node = this.hitNode(sp);
          if (node !== null) {
            if (e.shiftKey) { this.selNodes.has(node) ? this.selNodes.delete(node) : this.selNodes.add(node); }
            else if (!this.selNodes.has(node)) this.selNodes = new Set([node]);
            const c = this.contour;
            this.drag = { kind: 'nodes', start: wp, saved: [...this.selNodes].map((i) => [i, c.pts[i].slice(), c.hin[i] && c.hin[i].slice(), c.hout[i] && c.hout[i].slice()]), moved: false };
            this.hooks.selectionChanged();
            this.render();
            return;
          }
          const other = this.contourAt(sp);
          if (other !== null) { this.editing.active = other; this.selNodes.clear(); this.hooks.selectionChanged(); this.render(); return; }
          this.rubber = { a: sp, b: sp, add: e.shiftKey };
          return;
        }
        const hit = this.hitShape(sp);
        if (hit) {
          if (e.shiftKey) { this.sel.has(hit) ? this.sel.delete(hit) : this.sel.add(hit); }
          else if (!this.sel.has(hit)) this.sel = new Set([hit]);
          const moving = this.selectedShapes();
          this.drag = { kind: 'shapes', start: wp, moved: false, saved: moving.map((s) => [s, s.contours.map(G.copyContour)]) };
          this.hooks.selectionChanged();
          this.render();
        } else this.rubber = { a: sp, b: sp, add: e.shiftKey };
      });

      svg.addEventListener('pointermove', (e) => {
        const sp = local(e), wp = this.s2w(...sp);
        this.pointer = sp;
        this.hooks.cursor(wp[0], wp[1]);
        if (this.pan) {
          const v = this.pan.view;
          this.view = { s: v.s, ox: v.ox + sp[0] - this.pan.from[0], oy: v.oy + sp[1] - this.pan.from[1] };
          this.render();
          return;
        }
        if (this.xform) { this.updateTransform(wp); return; }
        if (this.drag) { this.dragTo(wp, e); return; }
        if (this.rubber) { this.rubber.b = sp; this.render(); return; }
        if (this.mode === 'design' && this.tool === 'pen') {
          const point = this.snap(wp);
          this.indicator = this.snapOn ? point : null;
          const d = this.draft;
          if (d && this.penDrag !== null && (e.buttons & 1)) {
            const c = d.contours[0], i = this.penDrag;
            if (this.penType !== 'sharp' && i < c.pts.length - 1 && G.dist(c.pts[i], wp) > 3 / this.view.s) {
              c.hout[i] = wp;
              c.hin[i] = this.penType === 'free' ? null : G.sub(G.mul(c.pts[i], 2), wp);
              c.types[i] = this.penType;
            }
          } else if (d) { const c = d.contours[0]; c.pts[c.pts.length - 1] = point; }
          this.render();
        }
      });

      svg.addEventListener('pointerup', (e) => {
        this.penDrag = null;
        if (this.pan) { this.pan = null; svg.style.cursor = this.tool === 'pen' && this.mode === 'design' ? 'crosshair' : 'default'; return; }
        if (this.xform) return;
        if (this.drag) {
          const d = this.drag;
          this.drag = null;
          if (d.moved) this.commit(); else this.render();
          return;
        }
        if (this.rubber) this.finishRubber(this.rubber.add);
      });

      svg.addEventListener('dblclick', (e) => {
        if (this.draft) { this.finishDraft(true); return; }
        if (this.editing && this.tool === 'select' && this.mode === 'design') {
          const sp = local(e), wp = this.s2w(...sp), c = this.contour;
          if (c.pts.every((q) => G.dist(this.w2s(q), sp) > PICK_PX * 1.5)) {
            const added = this.insertNode(this.editing, c, wp, PICK_PX / this.view.s);
            if (added !== null) { this.selNodes = new Set([added]); this.commit(); this.hooks.selectionChanged(); }
          }
        }
      });

      svg.addEventListener('wheel', (e) => {
        e.preventDefault();
        const sp = local(e);
        const mouseWheel = e.deltaMode !== 0 || (e.deltaX === 0 && e.wheelDeltaY && e.wheelDeltaY % 120 === 0);
        if (mouseWheel) {
          // Mouse wheel: zoom; Shift pans vertically and Ctrl horizontally, like Blender.
          const delta = e.deltaY || e.deltaX;
          if (!delta) return;
          if (e.shiftKey) this.view.oy -= delta * (e.deltaMode ? 20 : 1);
          else if (e.ctrlKey) this.view.ox -= delta * (e.deltaMode ? 20 : 1);
          else return this.zoomAt(sp, Math.exp(-delta * (e.deltaMode === 0 ? 0.0015 : 0.05)));
          this.render();
        } else if (e.ctrlKey) {
          this.zoomAt(sp, Math.exp(-e.deltaY * 0.01)); // trackpad pinch
        } else {
          this.view.ox -= e.deltaX; // trackpad two-finger scroll pans
          this.view.oy -= e.deltaY;
          this.render();
        }
      }, { passive: false });
    }

    /** Trackpad pinch: `value` is the relative size change, (x, y) the pinch centre in page pixels. */
    pinch(value, x, y) {
      const r = this.svg.getBoundingClientRect();
      this.zoomAt([x - r.left, y - r.top], Math.max(0.2, 1 + value));
    }

    /** Zoom by `factor` about the screen point `sp`. */
    zoomAt(sp, factor) {
      const s = Math.min(Math.max(this.view.s * factor, ZOOM[0]), ZOOM[1]);
      const k = s / this.view.s;
      this.view = { s, ox: sp[0] - (sp[0] - this.view.ox) * k, oy: sp[1] - (sp[1] - this.view.oy) * k };
      this.render();
    }

    dragTo(wp, e) {
      const d = this.drag;
      if (d.kind === 'control') {
        this.moveControl(this.contour, d.i, d.side, G.add(wp, d.offset), d.paired);
        d.moved = true;
      } else if (d.kind === 'nodes') {
        const c = this.contour;
        let delta = G.sub(wp, d.start);
        if (d.saved.length === 1) delta = G.sub(this.snap(G.add(d.saved[0][1], delta), new Set([this.editing])), d.saved[0][1]);
        for (const [i, p, a, b] of d.saved) {
          c.pts[i] = G.add(p, delta);
          c.hin[i] = a && G.add(a, delta);
          c.hout[i] = b && G.add(b, delta);
        }
        d.moved = d.moved || G.dist(wp, d.start) * this.view.s > 2;
      } else if (d.kind === 'shapes') {
        if (!d.moved && G.dist(wp, d.start) * this.view.s < 3) return;
        d.moved = true;
        let delta = G.sub(wp, d.start);
        const first = d.saved[0][1][0].pts[0];
        if (this.snapOn) delta = G.sub(this.snap(G.add(first, delta), new Set(d.saved.map((x) => x[0]))), first);
        for (const [s, saved] of d.saved) {
          s.contours.forEach((c, k) => {
            const o = saved[k];
            c.pts = o.pts.map((p) => G.add(p, delta));
            c.hin = o.hin.map((q) => q && G.add(q, delta));
            c.hout = o.hout.map((q) => q && G.add(q, delta));
          });
        }
      }
      this.render();
    }

    /** Key handling; returns true if the key was used. */
    key(e) {
      const k = e.key;
      if (this.xform) {
        if (k === 'Enter') this.finishTransform(true);
        else if (k === 'Escape') this.finishTransform(false);
        else if (k.toLowerCase() === 'x') this.setAxis('x');
        else if (k.toLowerCase() === 'y') this.setAxis('y');
        else return false;
        return true;
      }
      if (k === 'Enter') { this.finishDraft(true); return true; }
      if (k === 'Escape') {
        if (this.draft) this.cancelDraft();
        else if (this.editing && !this.selNodes.size) this.exitEdit();
        else this.deselectAll();
        this.render();
        return true;
      }
      return false;
    }

    // ---- rendering -----------------------------------------------------------------------

    render() {
      if (this._frame) return;
      this._frame = requestAnimationFrame(() => { this._frame = 0; this.draw(); });
    }

    contourD(c, closed) {
      const P = (p) => this.w2s(p).map((v) => v.toFixed(2)).join(',');
      const n = c.pts.length;
      let d = 'M' + P(c.pts[0]);
      for (let i = 0; i < (closed ? n : n - 1); i++) {
        const j = (i + 1) % n, seg = G.segment(c, i, j);
        d += seg ? `C${P(seg[1])} ${P(seg[2])} ${P(seg[3])}` : `L${P(c.pts[j])}`;
      }
      return d + (closed ? 'Z' : '');
    }

    shapeD(sh) { return sh.contours.map((c, k) => this.contourD(c, k > 0 || sh.kind === 'polygon')).join(''); }

    ringD(ring) { return 'M' + ring.map((p) => this.w2s(p).map((v) => v.toFixed(2)).join(',')).join('L') + 'Z'; }

    polyD(pts) { return 'M' + pts.map((p) => this.w2s(p).map((v) => v.toFixed(2)).join(',')).join('L'); }

    drawGrid() {
      const g = this.grid.getContext('2d'), dpr = window.devicePixelRatio || 1;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      const design = this.mode === 'design';
      g.fillStyle = design ? '#ffffff' : '#eef0f3';
      g.fillRect(0, 0, this.W, this.H);
      let [x0, x1] = [this.s2w(0, this.H)[0], this.s2w(0, 0)[0]];
      let [y0, y1] = [this.s2w(0, 0)[1], this.s2w(this.W, 0)[1]];
      g.save();
      if (!design) {
        const a = this.w2s([this.stage.x[0], this.stage.y[0]]), b = this.w2s([this.stage.x[1], this.stage.y[1]]);
        const rx = Math.min(a[0], b[0]), ry = Math.min(a[1], b[1]), rw = Math.abs(a[0] - b[0]), rh = Math.abs(a[1] - b[1]);
        g.fillStyle = '#ffffff';
        g.fillRect(rx, ry, rw, rh);
        g.beginPath(); g.rect(rx, ry, rw, rh); g.clip();
        x0 = Math.max(x0, this.stage.x[0]); x1 = Math.min(x1, this.stage.x[1]);
        y0 = Math.max(y0, this.stage.y[0]); y1 = Math.min(y1, this.stage.y[1]);
      }
      const step = this.gridStep();
      for (const major of [false, true]) {
        g.strokeStyle = major ? '#dde0e5' : '#eef0f3';
        g.lineWidth = 1;
        g.beginPath();
        for (let i = Math.ceil(x0 / step); i <= Math.floor(x1 / step); i++) {
          if ((i % 5 === 0) !== major) continue;
          const y = Math.round(this.w2s([i * step, 0])[1]) + 0.5;
          g.moveTo(0, y); g.lineTo(this.W, y);
        }
        for (let i = Math.ceil(y0 / step); i <= Math.floor(y1 / step); i++) {
          if ((i % 5 === 0) !== major) continue;
          const x = Math.round(this.w2s([0, i * step])[0]) + 0.5;
          g.moveTo(x, 0); g.lineTo(x, this.H);
        }
        g.stroke();
      }
      g.restore();
      g.strokeStyle = '#8a8f98';
      g.lineWidth = 1;
      if (design) {
        const o = this.w2s([0, 0]);
        g.beginPath(); g.moveTo(Math.round(o[0]) + 0.5, 0); g.lineTo(Math.round(o[0]) + 0.5, this.H); g.moveTo(0, Math.round(o[1]) + 0.5); g.lineTo(this.W, Math.round(o[1]) + 0.5); g.stroke();
      } else {
        const a = this.w2s([this.stage.x[0], this.stage.y[0]]), b = this.w2s([this.stage.x[1], this.stage.y[1]]);
        g.strokeRect(Math.min(a[0], b[0]) + 0.5, Math.min(a[1], b[1]) + 0.5, Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));
      }
    }

    draw() {
      this.drawGrid();
      const accent = css('--accent') || '#f5b800';
      const out = [];
      const path = (d, stroke, w, extra) => out.push(`<path d="${d}" fill="none" stroke="${stroke}" stroke-width="${w}" ${extra || ''}/>`);
      const design = this.mode === 'design';

      if (design) {
        this.drawFill(out, accent);
        const dim = this.editing ? 0.35 : 1;
        for (const sh of this.shapes) {
          const sub = sh.op === 'subtract';
          const d = this.shapeD(sh);
          const opacity = this.editing && sh !== this.editing ? dim : 1;
          path(d, sub ? RED : INK, 1.2, `${sub ? 'stroke-dasharray="6 4"' : ''} opacity="${opacity}" stroke-linejoin="round"`);
          if (this.sel.has(sh)) path(d, BLUE, 2.2, 'stroke-linejoin="round"');
        }
        if (this.draft) {
          const c = this.draft.contours[0];
          path(this.contourD(c, false), this.draft.pendingOp === 'subtract' ? RED : INK, 1.2, 'stroke-dasharray="5 3"');
          c.pts.forEach((p, i) => { const q = this.w2s(p); if (i < c.pts.length - 1) out.push(`<rect x="${q[0] - 3}" y="${q[1] - 3}" width="6" height="6" fill="#fff" stroke="${BLUE}" stroke-width="1.5"/>`); });
        }
        if (this.editing) this.drawEdit(out);
        if (this.indicator && this.tool === 'pen') { const q = this.w2s(this.indicator); out.push(`<circle cx="${q[0]}" cy="${q[1]}" r="6" fill="none" stroke="${INK}" stroke-width="2"/>`); }
      } else if (this.preview) {
        const pv = this.preview;
        if (pv.region.length) out.push(`<path d="${pv.region.map((r) => this.ringD(r)).join('')}" fill="${accent}" fill-opacity="0.2" fill-rule="evenodd" stroke="none"/>`);
        if (pv.transit.length) path(pv.transit.map((t) => this.polyD(t)).join(''), '#8a8f98', 1, 'stroke-dasharray="2 3"');
        const good = pv.plan.filter((s) => !s.bad), bad = pv.plan.filter((s) => s.bad);
        if (good.length) path(good.map((s) => this.polyD(s.pts)).join(''), INK, 1.2);
        if (bad.length) path(bad.map((s) => this.polyD(s.pts)).join(''), RED, 2);
        if (this.progress.length) path(this.progress.map((s) => this.polyD(s)).join(''), accent, 3, 'stroke-linejoin="round" stroke-linecap="round"');
        const o = this.w2s(pv.origin);
        out.push(`<circle cx="${o[0]}" cy="${o[1]}" r="7" fill="none" stroke="${INK}" stroke-width="2"/>`);
      }
      if (!design && this.marker) {
        const q = this.w2s(this.marker);
        out.push(`<path d="M${q[0] - 9},${q[1]}H${q[0] + 9}M${q[0]},${q[1] - 9}V${q[1] + 9}" stroke="${BLUE}" stroke-width="3" fill="none"/>`);
      }
      if (this.rubber) {
        const r = this.rubber;
        out.push(`<rect x="${Math.min(r.a[0], r.b[0])}" y="${Math.min(r.a[1], r.b[1])}" width="${Math.abs(r.a[0] - r.b[0])}" height="${Math.abs(r.a[1] - r.b[1])}" fill="${BLUE}" fill-opacity="0.08" stroke="${BLUE}" stroke-width="1" stroke-dasharray="4 3"/>`);
      }
      this.svg.innerHTML = out.join('');
    }

    /**
     * The yellow scan region: added shapes minus subtracted ones. Drawn here from the shapes (a mask cuts out the
     * subtract shapes), so it follows a drag live; planning.py computes the same region for the scan itself.
     */
    drawFill(out, accent) {
      const adds = this.shapes.filter((s) => s.kind === 'polygon' && s.op !== 'subtract');
      if (!adds.length) return;
      const subs = this.shapes.filter((s) => s.kind === 'polygon' && s.op === 'subtract');
      const mask = subs.length
        ? `<mask id="cut" maskUnits="userSpaceOnUse" x="0" y="0" width="${this.W}" height="${this.H}"><rect width="${this.W}" height="${this.H}" fill="#fff"/>` +
          subs.map((s) => `<path d="${this.shapeD(s)}" fill="#000" fill-rule="evenodd"/>`).join('') + '</mask>'
        : '';
      out.push(mask + `<g opacity="0.28" ${subs.length ? 'mask="url(#cut)"' : ''}>` +
        adds.map((s) => `<path d="${this.shapeD(s)}" fill="${accent}" fill-rule="evenodd"/>`).join('') + '</g>');
    }

    drawEdit(out) {
      const c = this.contour, sh = this.editing;
      if (sh.active > 0 || sh.contours.length > 1) {
        // The contour being edited is drawn thicker so a hole can be told from the outline.
        out.push(`<path d="${this.contourD(c, sh.active > 0 || sh.kind === 'polygon')}" fill="none" stroke="${BLUE}" stroke-width="2" opacity="0.8"/>`);
      }
      const ctl = this.controlPoints();
      for (const k of ctl) {
        const a = this.w2s(c.pts[k.i]), b = this.w2s(k.p);
        out.push(`<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${BLUE}" stroke-width="1"/>`);
      }
      c.pts.forEach((p, i) => {
        const q = this.w2s(p), on = this.selNodes.has(i);
        out.push(`<rect x="${q[0] - 4}" y="${q[1] - 4}" width="8" height="8" fill="${on ? BLUE : '#fff'}" stroke="${BLUE}" stroke-width="1.5"/>`);
      });
      for (const k of ctl) {
        const q = this.w2s(k.p);
        out.push(`<circle cx="${q[0]}" cy="${q[1]}" r="4.5" fill="${k.ghost ? '#fff' : BLUE}" stroke="${BLUE}" stroke-width="1.5"/>`);
      }
    }

    // ---- results of async operations ------------------------------------------------------

    /** Replace all shapes with a result from Python and select the shapes at `selected`. */
    replaceShapes(dicts, selected) {
      this.cancelDraft();
      this.exitEdit(true);
      this.shapes = dicts.map(G.shapeFromDict).filter(Boolean);
      this.sel = new Set((selected || []).map((i) => this.shapes[i]).filter(Boolean));
      this.hooks.selectionChanged();
      this.commit();
    }
  }

  function bounds(pts) {
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    return [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  }

  root.Canvas = Canvas;
})(window);
