/*
 * Drawing canvas: a Paper.js scene (shapes, scan preview, editing overlay) over a 2D canvas with the grid.
 *
 * Paper owns the geometry, hit tests, transforms, zoom / pan and drawing; this file adds the editor around it:
 * tools, selection, node editing, modal transforms (G / R / S), snapping, undo, and the preview / monitor display.
 * Everything is kept in Paper's frame (see shapes.js): world (X, Y) microns are drawn as (Y, -X), so screen up is
 * +X and screen right is +Y, like the microscope camera.
 */
(function (root) {
  'use strict';
  const S = root.Shapes;
  const { Point, Path, CompoundPath, Rectangle, Matrix, Group, Layer, Size, Color } = root.paper;
  const PICK_PX = 8, GRID_PX = 12, GHOST_PX = 16, ZOOM = [1e-4, 200];
  const INK = '#0b0b0b', RED = '#c0392b', BLUE = '#8b5a2b';

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const pt = (p) => (p instanceof Point ? p : new Point(p[0], p[1]));

  class Canvas {
    /**
     * @param {HTMLElement} wrap Container for the two canvases.
     * @param {object} hooks Callbacks: changed, message, cursor, editChanged, toolChanged, selectionChanged, merge.
     */
    constructor(wrap, hooks) {
      this.wrap = wrap;
      this.hooks = hooks;
      this.grid = document.createElement('canvas');
      this.el = document.createElement('canvas');
      this.el.tabIndex = 0;
      wrap.append(this.grid, this.el);

      root.paper.setup(this.el);
      this.view = root.paper.view;
      root.paper.project.clear();
      this.layers = {};
      for (const name of ['fill', 'shapes', 'draft', 'plan', 'overlay']) this.layers[name] = new Layer({ name });

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
      this.preview = null;
      this.progressItem = null;
      this.planStrokes = [];
      this.strokeZoom = 0;
      this.progressAt = [0, -1];
      this.marker = null;
      this.pointer = [0, 0];
      this.indicator = null;
      this.views = {};
      this.history = ['[]'];
      this.hidx = 0;
      this.locked = false;
      this.fillDirty = true;
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
      this.view.viewSize = new Size(this.W, this.H);
    }

    get zoom() { return this.view.zoom; }

    /** A length in screen pixels as a length in the Paper frame. Strokes are sized with this, on every zoom change:
     * Paper's own `strokeScaling: false` transforms every point by hand and costs ~100 us per path. */
    px(n) { return n / this.zoom; }

    /** World point -> screen pixels. */
    w2s(p) { const q = this.view.projectToView(S.toPaper(p)); return [q.x, q.y]; }
    /** Screen pixels -> world point. */
    s2w(x, y) { return S.toWorld(this.view.viewToProject(new Point(x, y))); }
    /** Screen pixels -> Paper frame (where all items live). */
    s2p(sp) { return this.view.viewToProject(pt(sp)); }

    gridStep() {
      const target = GRID_PX / this.zoom;
      const exp = Math.floor(Math.log10(target));
      for (const f of [1, 2, 5, 10]) if (f * 10 ** exp >= target) return Math.max(1, f * 10 ** exp);
      return 1;
    }

    /** Show the world box [x0, x1] x [y0, y1]. */
    fitRect(x0, x1, y0, y1) {
      const w = Math.max(y1 - y0, 20), h = Math.max(x1 - x0, 20);
      const z = Math.min(Math.max(0.88 * Math.min(this.W / w, this.H / h), ZOOM[0]), ZOOM[1]);
      this.view.zoom = z;
      this.view.center = S.toPaper([(x0 + x1) / 2, (y0 + y1) / 2]);
      this.render();
    }

    /** World box [x0, x1, y0, y1] of a rectangle in the Paper frame. */
    static worldBox(r) { return [-r.bottom, -r.top, r.left, r.right]; }

    fit() {
      let box;
      if (this.mode === 'design') {
        const r = this.shapes.reduce((acc, s) => (acc ? acc.unite(s.bounds) : s.bounds), null);
        box = r ? Canvas.worldBox(r) : [-325, 325, -500, 500];
      } else if (this.preview && this.preview.bounds) {
        box = this.preview.bounds.slice();
        if (this.preview.exceeds) box = [Math.min(box[0], this.stage.x[0]), Math.max(box[1], this.stage.x[1]), Math.min(box[2], this.stage.y[0]), Math.max(box[3], this.stage.y[1])];
      } else box = [this.stage.x[0], this.stage.x[1], this.stage.y[0], this.stage.y[1]];
      this.fitRect(...box);
    }

    fitStage() { this.fitRect(this.stage.x[0], this.stage.x[1], this.stage.y[0], this.stage.y[1]); }

    setMode(mode) {
      if (mode === this.mode) return;
      this.views[this.mode] = { zoom: this.zoom, center: this.view.center.clone() };
      this.mode = mode;
      if (mode !== 'design') { this.exitEdit(true); this.cancelDraft(); this.xform = null; }
      const saved = mode === 'design' ? this.views.design : mode === 'monitor' ? this.views.preview : null;
      if (saved) { this.view.zoom = saved.zoom; this.view.center = saved.center; this.render(); } else this.fit();
    }

    setStage(x0, x1, y0, y1) { this.stage = { x: [x0, x1], y: [y0, y1] }; this.render(); }

    /** Zoom by `factor` about the screen point `sp`. */
    zoomAt(sp, factor) {
      const before = this.s2p(sp);
      this.view.zoom = Math.min(Math.max(this.zoom * factor, ZOOM[0]), ZOOM[1]);
      this.view.center = this.view.center.add(before.subtract(this.s2p(sp)));
      this.render();
    }

    /** Trackpad pinch: `value` is the relative size change, (x, y) the pinch centre in page pixels. */
    pinch(value, x, y) {
      const r = this.el.getBoundingClientRect();
      this.zoomAt([x - r.left, y - r.top], Math.max(0.2, 1 + value));
    }

    // ---- model ------------------------------------------------------------

    dicts() { return this.shapes.map(S.shapeToDict); }

    /** Replace all shapes by the ones described in `dicts`. */
    load(dicts) {
      this.cancelDraft();
      this.exitEdit(true);
      this.shapes.forEach((s) => s.remove());
      this.shapes = dicts.map(S.shapeFromDict).filter(Boolean);
      this.shapes.forEach((s) => this.layers.shapes.addChild(s));
      this.sel.clear();
      this.selNodes.clear();
    }

    setShapes(dicts, record) {
      this.load(dicts);
      if (record) this.commit();
      else this.touch();
    }

    commit() {
      const now = JSON.stringify(this.dicts());
      if (now !== this.history[this.hidx]) {
        this.history = this.history.slice(0, this.hidx + 1).concat(now);
        this.hidx++;
      }
      this.hooks.changed();
      this.touch();
    }

    restoreHistory() {
      this.load(JSON.parse(this.history[this.hidx]));
      this.hooks.changed();
      this.touch();
    }

    undo() { if (this.mode === 'design' && !this.locked && this.hidx > 0) { this.hidx--; this.restoreHistory(); } }
    redo() { if (this.mode === 'design' && !this.locked && this.hidx < this.history.length - 1) { this.hidx++; this.restoreHistory(); } }

    /** The geometry changed: the yellow fill must be rebuilt. */
    touch() { this.fillDirty = true; this.render(); }

    /** Show the scan plan. `data.plan` is [{pts, laser, bad}] in absolute microns; `region` rings and `transit` too. */
    setPreview(data) {
      this.preview = data;
      const layer = this.layers.plan;
      layer.removeChildren();
      const accent = css('--accent') || '#f5b800';
      const lines = (list) => list.map((pts) => new Path({ segments: pts.map(S.toPaper), insert: false }));
      this.planStrokes = [];
      const compound = (children, style, width = 0, dash = []) => {
        const item = new CompoundPath({ children, fillColor: null, ...style, parent: layer });
        this.planStrokes.push({ item, width, dash });
        return item;
      };
      if (data.region.length) {
        const c = compound(data.region.map(S.ringPath), { strokeColor: null, fillRule: 'evenodd' });
        c.fillColor = new Color(accent); c.fillColor.alpha = 0.2;
      }
      if (data.transit.length) compound(lines(data.transit), { strokeColor: '#8a8f98' }, 1, [2, 3]);
      const good = data.plan.filter((s) => !s.bad).map((s) => s.pts), bad = data.plan.filter((s) => s.bad).map((s) => s.pts);
      if (good.length) compound(lines(good), { strokeColor: INK }, 1.2);
      if (bad.length) compound(lines(bad), { strokeColor: RED }, 2);
      this.progressItem = compound([], { strokeColor: accent, strokeJoin: 'round', strokeCap: 'round' }, 3);
      this.progressAt = [0, -1];
      this.strokeZoom = 0; // sizes the strokes at the next draw
      this.render();
    }

    clearProgress() {
      if (this.progressItem) this.progressItem.removeChildren();
      this.progressAt = [0, -1];
      this.render();
    }

    setProgress(seg, pt2) {
      const plan = this.preview && this.preview.plan;
      if (!plan || !this.progressItem) return;
      const item = this.progressItem;
      let [i, j] = this.progressAt;
      while ((i !== seg || j !== pt2) && i < plan.length) {
        if (j + 1 < plan[i].pts.length) {
          j++;
          const p = S.toPaper(plan[i].pts[j]);
          if (j > 0 && plan[i].laser && item.children.length) item.lastChild.add(p);
          else item.addChild(new Path({ segments: [p], insert: false }));
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
      for (const s of this.selectedShapes()) if (s.data.kind === 'polygon') s.data.op = op;
      this.commit();
    }

    setTool(tool) {
      if (tool !== 'select') this.exitEdit();
      this.cancelDraft();
      this.tool = tool;
      this.hooks.toolChanged(tool);
      this.el.style.cursor = tool === 'pen' && this.mode === 'design' ? 'crosshair' : 'default';
      this.render();
    }

    pickTool() { if (this.mode === 'design') this.setTool(this.tool === 'select' ? 'pen' : 'select'); }

    selectAll() {
      if (this.mode !== 'design') return;
      if (this.editing) this.selNodes = new Set(this.contour.segments.map((_, i) => i));
      else this.sel = new Set(this.shapes);
      this.hooks.selectionChanged();
      this.render();
    }

    deselectAll() { this.sel.clear(); this.selNodes.clear(); this.hooks.selectionChanged(); this.render(); }

    invertSelection() {
      if (this.mode !== 'design') return;
      if (this.editing) this.selNodes = new Set(this.contour.segments.map((_, i) => i).filter((i) => !this.selNodes.has(i)));
      else this.sel = new Set(this.shapes.filter((s) => !this.sel.has(s)));
      this.hooks.selectionChanged();
      this.render();
    }

    deleteSelected() {
      if (this.mode !== 'design' || this.xform || this.locked) return;
      if (this.editing) {
        const sh = this.editing;
        if (this.selNodes.size) {
          if (S.deleteNodes(this.contour, [...this.selNodes], S.MIN_NODES[sh.data.kind])) this.selNodes.clear();
          else this.hooks.message(`A ${sh.data.kind} needs at least ${S.MIN_NODES[sh.data.kind]} nodes. Leave Edit mode (Tab) to delete the whole shape.`, true);
        }
        this.commit();
        return;
      }
      this.shapes = this.shapes.filter((s) => { if (!this.sel.has(s)) return true; s.remove(); return false; });
      this.sel.clear();
      this.hooks.selectionChanged();
      this.commit();
    }

    duplicate() {
      const chosen = this.selectedShapes();
      if (this.mode !== 'design' || this.editing || this.xform || !chosen.length) return;
      const copies = chosen.map((s) => { const c = S.copyShape(s); this.layers.shapes.addChild(c); this.shapes.push(c); return c; });
      this.sel = new Set(copies);
      this.hooks.selectionChanged();
      this.commit();
      this.startTransform('grab');
    }

    invertOp() {
      const sel = this.selectedShapes();
      if (this.mode === 'design' && sel.length) this.applyOp(sel[0].data.op === 'subtract' ? 'add' : 'subtract');
    }

    // ---- edit mode -------------------------------------------------------------

    enterEdit() {
      if (this.mode !== 'design' || this.draft || this.xform || this.locked) return false;
      if (this.editing) return true;
      const chosen = this.selectedShapes();
      if (chosen.length !== 1) { this.hooks.message('Select one shape first, then press Tab to edit its nodes.', false); return false; }
      this.setTool('select');
      this.editing = chosen[0];
      this.editing.data.active = 0;
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
      sh.data.active = 0;
      if (!silent) { this.sel = new Set([sh]); this.commit(); }
      this.hooks.editChanged(false);
      this.hooks.selectionChanged();
      this.render();
    }

    toggleEdit() { if (this.editing) this.exitEdit(); else this.enterEdit(); }

    /** The path whose nodes are being edited. */
    get contour() { return this.editing && this.editing.children[this.editing.data.active]; }

    setNodeType(kind) {
      if (!this.editing) return;
      if (!this.selNodes.size) { this.hooks.message('Select one or more nodes first.', false); return; }
      S.setNodeType(this.contour, [...this.selNodes], kind);
      this.commit();
    }

    extrude() {
      if (!this.editing || this.xform) return;
      if (!this.selNodes.size) { this.hooks.message('Select one or more nodes to extrude.', false); return; }
      this.selNodes = new Set(S.extrudeNodes(this.contour, this.selNodes));
      this.startTransform('grab', true);
    }

    // ---- modal transforms (G / R / S) ------------------------------------------

    get transforming() { return !!this.xform; }

    /** What a transform or flip acts on: the selected nodes in Edit mode, else every node of the selected shapes. */
    transformItems() {
      const targets = this.editing
        ? (this.selNodes.size ? [[this.contour, [...this.selNodes]]] : [])
        : this.selectedShapes().flatMap((s) => s.children.map((c) => [c, c.segments.map((_, i) => i)]));
      return targets.map(([path, idx]) => ({ path, saved: S.snapshot(path, idx) }));
    }

    static anchorsOf(items) { return items.flatMap((it) => it.saved.map((n) => n.point)); }

    /**
     * Mirror the selection (shapes, or nodes in Edit mode) about the centre of its bounding box.
     * 'h' swaps left and right on the screen, 'v' swaps top and bottom.
     */
    flip(direction) {
      if (this.mode !== 'design' || this.xform || this.draft || this.locked) return;
      const items = this.transformItems();
      if (!items.length) { this.hooks.message('Select something first.', false); return; }
      const box = Canvas.anchorsOf(items).reduce((r, p) => (r ? r.include(p) : new Rectangle(p, p)), null);
      const m = new Matrix().scale(direction === 'h' ? -1 : 1, direction === 'v' ? -1 : 1, box.center);
      for (const { path, saved } of items) S.applySnapshot(path, saved, (p) => m.transform(p));
      this.commit();
    }

    startTransform(mode, extrude) {
      if (this.mode !== 'design' || this.xform || this.draft || this.locked) return;
      const items = this.transformItems();
      if (!items.length) { this.hooks.message('Select something first.', false); return; }
      const anchors = Canvas.anchorsOf(items);
      const pivot = anchors.reduce((a, p) => a.add(p), new Point(0, 0)).divide(anchors.length);
      this.xform = { mode, items, pivot, start: this.s2p(this.pointer), probe: anchors[0], axis: null, extrude: !!extrude };
    }

    /** Lock to a world axis: 'x' is screen-vertical, 'y' screen-horizontal. */
    setAxis(axis) {
      if (!this.xform) return;
      this.xform.axis = this.xform.axis === axis ? null : axis;
      this.updateTransform(this.s2p(this.pointer));
    }

    updateTransform(cursor) {
      const x = this.xform, { pivot, start, axis } = x;
      let m;
      if (x.mode === 'grab') {
        let delta = cursor.subtract(start);
        if (this.snapOn) {
          const moving = new Set(x.items.map((it) => it.path.parent));
          delta = this.snap(x.probe.add(delta), moving).subtract(x.probe);
        }
        if (axis === 'x') delta = new Point(0, delta.y); else if (axis === 'y') delta = new Point(delta.x, 0);
        m = new Matrix().translate(delta);
      } else if (x.mode === 'scale') {
        const r0 = start.getDistance(pivot), k = r0 > 1e-9 ? cursor.getDistance(pivot) / r0 : 1;
        m = new Matrix().scale(axis === 'x' ? 1 : k, axis === 'y' ? 1 : k, pivot);
      } else {
        const turn = cursor.subtract(pivot).angle - start.subtract(pivot).angle;
        m = new Matrix().rotate(turn, pivot);
      }
      for (const { path, saved } of x.items) S.applySnapshot(path, saved, (p) => m.transform(p));
      this.touch();
    }

    finishTransform(confirm) {
      const x = this.xform;
      this.xform = null;
      if (!x) return;
      if (!confirm && x.extrude) { this.restoreHistory(); return; }
      if (!confirm) for (const { path, saved } of x.items) S.restoreSnapshot(path, saved);
      this.commit();
    }

    // ---- snapping --------------------------------------------------------------

    /** Snap a Paper-frame point to the nearest vertex of another shape, else to the grid. */
    snap(p, exclude) {
      if (!this.snapOn) return p.clone();
      const reach = (PICK_PX * 2) / this.zoom;
      let best = null, bd = Infinity;
      for (const s of this.shapes) {
        if (exclude && exclude.has(s)) continue;
        for (const c of s.children) for (const seg of c.segments) { const d = seg.point.getDistance(p); if (d < bd) { bd = d; best = seg.point; } }
      }
      if (best && bd <= reach) return best.clone();
      const step = this.gridStep();
      return new Point(Math.round(p.x / step) * step, Math.round(p.y / step) * step);
    }

    // ---- hit testing -------------------------------------------------------------

    hitShape(sp) {
      const p = this.s2p(sp), tolerance = PICK_PX / this.zoom;
      for (let n = this.shapes.length - 1; n >= 0; n--) {
        const sh = this.shapes[n];
        // The outline within a few pixels, or the inside of a polygon (holes excluded: its fill rule is even-odd).
        if (sh.hitTest(p, { stroke: true, fill: false, tolerance }) || (sh.data.kind === 'polygon' && sh.contains(p))) return sh;
      }
      return null;
    }

    hitNode(sp) {
      const c = this.contour;
      if (!c) return null;
      let best = null, bd = PICK_PX + 2;
      c.segments.forEach((s, i) => { const d = this.view.projectToView(s.point).getDistance(pt(sp)); if (d <= bd) { bd = d; best = i; } });
      return best;
    }

    /** Handles of the selected nodes; a node without a handle gets a "ghost" pointing at its neighbour. */
    controlPoints() {
      const c = this.contour;
      if (!c) return [];
      const n = c.segments.length, closed = c.closed, out = [];
      for (const i of this.selNodes) {
        const s = c.segments[i];
        for (const [side, handle, j, exists] of [['in', s.handleIn, i - 1, closed || i > 0], ['out', s.handleOut, i + 1, closed || i < n - 1]]) {
          if (!exists) continue;
          if (S.hasHandle(handle)) { out.push({ i, side, p: s.point.add(handle), ghost: false }); continue; }
          const toward = c.segments[(j + n) % n].point.subtract(s.point);
          out.push({ i, side, p: s.point.add(toward.length ? toward.normalize(GHOST_PX / this.zoom) : toward), ghost: true });
        }
      }
      return out;
    }

    hitControl(sp) {
      return this.controlPoints().find((k) => this.view.projectToView(k.p).getDistance(pt(sp)) <= PICK_PX) || null;
    }

    /** Index of another contour of the edited shape near the screen point, if any. */
    contourAt(sp) {
      const sh = this.editing, p = this.s2p(sp), tolerance = PICK_PX / this.zoom;
      const k = sh.children.findIndex((c, i) => i !== sh.data.active && c.hitTest(p, { stroke: true, fill: false, tolerance }));
      return k < 0 ? null : k;
    }

    // ---- pen tool -----------------------------------------------------------------

    cancelDraft() {
      if (this.draft) this.draft.path.remove();
      this.draft = null;
      this.penDrag = null;
    }

    finishDraft(trailing) {
      const d = this.draft;
      this.draft = null;
      this.penDrag = null;
      if (!d) return;
      const path = d.path;
      path.remove();
      const polygon = d.kind === 'polygon';
      if (trailing && !polygon) { path.removeSegment(path.segments.length - 1); d.types.pop(); }
      if (path.segments.length < S.MIN_NODES[polygon ? 'polygon' : 'polyline']) { this.render(); return; }
      // A clean path: the draft's dashed style must not leak into the shape.
      const clean = new Path({ segments: path.segments.map((s) => s.clone()), insert: false });
      clean.data = { types: d.types.slice(0, clean.segments.length) };
      const shape = S.makeShape(d.kind, [clean], d.op);
      this.layers.shapes.addChild(shape);
      this.shapes.push(shape);
      const merge = this.newOp === 'merge' && polygon;
      this.setTool('select');
      this.sel = new Set([shape]);
      this.commit();
      if (merge) this.hooks.merge(this.dicts(), this.shapes.length - 1);
      else if (this.shapes.includes(shape)) this.enterEdit();
    }

    penPress(p) {
      const op = this.newOp === 'merge' ? 'add' : this.newOp;
      const point = this.snap(p);
      if (this.draft) {
        const d = this.draft, c = d.path, segs = c.segments;
        if (segs.length >= 4 && segs[0].point.getDistance(point) <= (PICK_PX * 2) / this.zoom) {
          c.removeSegment(segs.length - 1);
          d.types.pop();
          d.kind = 'polygon';
          d.op = op;
          this.finishDraft(false);
          return;
        }
        segs[segs.length - 1].point = point;
        c.add(point.clone());
        d.types.push('sharp');
        this.penDrag = c.segments.length - 2;
      } else {
        const path = new Path({ segments: [point, point.clone()], strokeColor: op === 'subtract' ? RED : INK, parent: this.layers.draft });
        this.draft = { path, kind: 'polyline', op, types: ['sharp', 'sharp'] };
        this.penDrag = 0;
      }
      this.render();
    }

    // ---- rubber band -----------------------------------------------------------------

    finishRubber(add) {
      const r = this.rubber;
      this.rubber = null;
      if (!r) return;
      const rect = new Rectangle(pt(r.a), pt(r.b));
      if (rect.width < 3 && rect.height < 3) { if (!add) this.deselectAll(); this.render(); return; }
      if (this.editing) {
        const hit = [];
        this.contour.segments.forEach((s, i) => { if (rect.contains(this.view.projectToView(s.point))) hit.push(i); });
        this.selNodes = add ? new Set([...this.selNodes, ...hit]) : new Set(hit);
      } else {
        const area = new Rectangle(this.s2p(rect.topLeft), this.s2p(rect.bottomRight));
        const frame = new Path.Rectangle({ rectangle: area, insert: false });
        const touches = (sh) => sh.bounds.intersects(area)
          && sh.children.some((c) => area.contains(c.firstSegment.point) || c.getIntersections(frame).length > 0);
        const hit = this.shapes.filter(touches);
        this.sel = add ? new Set([...this.sel, ...hit]) : new Set(hit);
      }
      this.hooks.selectionChanged();
      this.render();
    }

    // ---- events -----------------------------------------------------------------------

    _bind() {
      const el = this.el;
      const local = (e) => { const r = el.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
      el.addEventListener('contextmenu', (e) => e.preventDefault());
      el.addEventListener('pointerenter', () => { const a = document.activeElement; if (!a || !/INPUT|TEXTAREA|SELECT/.test(a.tagName)) el.focus({ preventScroll: true }); });

      el.addEventListener('pointerdown', (e) => {
        el.focus({ preventScroll: true });
        try { el.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events have no active pointer */ }
        const sp = local(e), p = this.s2p(sp);
        this.pointer = sp;
        if (this.xform) { if (e.button === 0 || e.button === 2) this.finishTransform(e.button === 0); return; }
        if (e.button === 1 || (this.mode !== 'design' && e.button === 0)) { this.pan = { from: sp, center: this.view.center.clone() }; el.style.cursor = 'grabbing'; return; }
        if (this.mode !== 'design' || this.locked) return;
        if (e.button === 2) { if (this.draft) this.finishDraft(true); return; }
        if (e.button !== 0) return;
        if (this.tool === 'pen') { this.penPress(p); return; }
        if (this.editing) {
          const c = this.contour, types = S.typesOf(c);
          const ctl = this.hitControl(sp);
          if (ctl) {
            if (e.altKey && ['smooth', 'symmetric'].includes(types[ctl.i])) types[ctl.i] = 'free';
            this.drag = { kind: 'control', i: ctl.i, side: ctl.side, paired: ['smooth', 'symmetric'].includes(types[ctl.i]), offset: ctl.p.subtract(p) };
            return;
          }
          const node = this.hitNode(sp);
          if (node !== null) {
            if (e.shiftKey) { this.selNodes.has(node) ? this.selNodes.delete(node) : this.selNodes.add(node); }
            else if (!this.selNodes.has(node)) this.selNodes = new Set([node]);
            this.drag = { kind: 'nodes', start: p, saved: S.snapshot(c, [...this.selNodes]), moved: false };
            this.hooks.selectionChanged();
            this.render();
            return;
          }
          const other = this.contourAt(sp);
          if (other !== null) { this.editing.data.active = other; this.selNodes.clear(); this.hooks.selectionChanged(); this.render(); return; }
          this.rubber = { a: sp, b: sp, add: e.shiftKey };
          return;
        }
        const hit = this.hitShape(sp);
        if (hit) {
          if (e.shiftKey) { this.sel.has(hit) ? this.sel.delete(hit) : this.sel.add(hit); }
          else if (!this.sel.has(hit)) this.sel = new Set([hit]);
          this.drag = { kind: 'shapes', start: p, moved: false, items: this.transformItems() };
          this.hooks.selectionChanged();
          this.render();
        } else this.rubber = { a: sp, b: sp, add: e.shiftKey };
      });

      el.addEventListener('pointermove', (e) => {
        const sp = local(e), p = this.s2p(sp);
        this.pointer = sp;
        const w = S.toWorld(p);
        this.hooks.cursor(w[0], w[1]);
        if (this.pan) {
          this.view.center = this.pan.center.subtract(new Point(sp[0] - this.pan.from[0], sp[1] - this.pan.from[1]).divide(this.zoom));
          this.render();
          return;
        }
        if (this.xform) { this.updateTransform(p); return; }
        if (this.drag) { this.dragTo(p); return; }
        if (this.rubber) { this.rubber.b = sp; this.render(); return; }
        if (this.mode === 'design' && this.tool === 'pen') {
          const point = this.snap(p);
          this.indicator = this.snapOn ? point : null;
          const d = this.draft;
          if (d) {
            const c = d.path, segs = c.segments;
            if (this.penDrag !== null && (e.buttons & 1)) {
              const i = this.penDrag;
              if (this.penType !== 'sharp' && i < segs.length - 1 && segs[i].point.getDistance(p) > 3 / this.zoom) {
                segs[i].handleOut = p.subtract(segs[i].point);
                segs[i].handleIn = this.penType === 'free' ? new Point(0, 0) : segs[i].point.subtract(p);
                d.types[i] = this.penType;
              }
            } else segs[segs.length - 1].point = point;
          }
          this.render();
        }
      });

      el.addEventListener('pointerup', () => {
        this.penDrag = null;
        if (this.pan) { this.pan = null; el.style.cursor = this.tool === 'pen' && this.mode === 'design' ? 'crosshair' : 'default'; return; }
        if (this.xform) return;
        if (this.drag) {
          const d = this.drag;
          this.drag = null;
          if (d.moved) this.commit(); else this.render();
          return;
        }
        if (this.rubber) this.finishRubber(this.rubber.add);
      });

      el.addEventListener('dblclick', (e) => {
        if (this.draft) { this.finishDraft(true); return; }
        if (this.editing && this.tool === 'select' && this.mode === 'design') {
          const sp = local(e), c = this.contour;
          if (c.segments.every((s) => this.view.projectToView(s.point).getDistance(pt(sp)) > PICK_PX * 1.5)) {
            const added = S.insertNode(c, this.s2p(sp), PICK_PX / this.zoom);
            if (added !== null) { this.selNodes = new Set([added]); this.commit(); this.hooks.selectionChanged(); }
          }
        }
      });

      // The wheel always zooms about the cursor, with no modifier; panning is a middle-button drag.
      el.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY || e.deltaX;
        if (!delta) return;
        const rate = e.ctrlKey ? 0.01 : e.deltaMode === 0 ? 0.0015 : 0.05; // ctrl + wheel is a Chromium / WebView2 pinch
        // Plain wheel: scroll down zooms in, up zooms out. A ctrl + wheel pinch keeps its natural direction.
        this.zoomAt(local(e), Math.exp((e.ctrlKey ? -delta : delta) * rate));
      }, { passive: false });

      // WebKit (macOS) reports a trackpad pinch as gesture events whose scale is relative to the gesture's start.
      let last = 1;
      el.addEventListener('gesturestart', (e) => { e.preventDefault(); last = 1; });
      el.addEventListener('gesturechange', (e) => { e.preventDefault(); this.zoomAt(local(e), e.scale / last); last = e.scale; });
      el.addEventListener('gestureend', (e) => e.preventDefault());
    }

    dragTo(p) {
      const d = this.drag;
      if (d.kind === 'control') {
        S.moveControl(this.contour, d.i, d.side, p.add(d.offset), d.paired);
        d.moved = true;
      } else if (d.kind === 'nodes') {
        let delta = p.subtract(d.start);
        if (d.saved.length === 1) delta = this.snap(d.saved[0].point.add(delta), new Set([this.editing])).subtract(d.saved[0].point);
        S.applySnapshot(this.contour, d.saved, (q) => q.add(delta));
        d.moved = d.moved || p.getDistance(d.start) * this.zoom > 2;
      } else if (d.kind === 'shapes') {
        if (!d.moved && p.getDistance(d.start) * this.zoom < 3) return;
        d.moved = true;
        let delta = p.subtract(d.start);
        const first = d.items[0].saved[0].point;
        if (this.snapOn) delta = this.snap(first.add(delta), new Set(d.items.map((it) => it.path.parent))).subtract(first);
        for (const { path, saved } of d.items) S.applySnapshot(path, saved, (q) => q.add(delta));
      }
      this.touch();
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
      if (this.hooks.scale) this.hooks.scale(step);
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
      const design = this.mode === 'design';
      const L = this.layers;
      L.fill.visible = L.shapes.visible = L.draft.visible = design;
      L.plan.visible = !design;
      if (design) {
        this.restyle();
        if (this.fillDirty) this.rebuildFill();
        if (this.draft) { this.draft.path.strokeWidth = this.px(1.2); this.draft.path.dashArray = [this.px(5), this.px(3)]; }
      } else if (this.strokeZoom !== this.zoom) {
        this.strokeZoom = this.zoom;
        for (const { item, width, dash } of this.planStrokes) { item.strokeWidth = this.px(width); item.dashArray = dash.map((d) => this.px(d)); }
      }
      this.rebuildOverlay();
      this.view.update();
    }

    /** Stroke of every shape: black, red dashed when it subtracts, brown when selected, faded behind an edited shape. */
    restyle() {
      for (const sh of this.shapes) {
        const sub = sh.data.op === 'subtract', sel = this.sel.has(sh) || sh === this.editing;
        const dim = this.editing && sh !== this.editing;
        const key = `${sub}|${sel}|${dim}|${sh.data.kind}|${this.zoom}`;
        if (sh.data.sig === key) continue;
        sh.data.sig = key;
        sh.style = {
          strokeColor: sel ? BLUE : sub ? RED : INK,
          strokeWidth: this.px(sel ? 2.2 : 1.2),
          strokeJoin: 'round',
          dashArray: sub ? [this.px(6), this.px(4)] : [],
          opacity: dim ? 0.35 : 1,
          fillColor: null,
        };
      }
    }

    /**
     * The yellow scan region: added shapes minus subtracted ones. Built from copies of the shapes, the subtracted
     * ones cutting a hole (destination-out), so it follows a drag live; planning.py computes the same region for
     * the scan itself.
     */
    rebuildFill() {
      this.fillDirty = false;
      const layer = this.layers.fill;
      layer.removeChildren();
      const polygons = this.shapes.filter((s) => s.data.kind === 'polygon');
      if (!polygons.length) return;
      const accent = css('--accent') || '#f5b800';
      const group = new Group({ opacity: 0.28, parent: layer });
      const copy = (s) => { const c = s.clone({ insert: false }); c.style = { strokeColor: null, fillRule: 'evenodd' }; return c; };
      for (const s of polygons) {
        if (s.data.op === 'subtract') continue;
        const c = copy(s);
        c.fillColor = accent;
        group.addChild(c);
      }
      for (const s of polygons) {
        if (s.data.op !== 'subtract') continue;
        const c = copy(s);
        c.fillColor = '#000000';
        c.blendMode = 'destination-out';
        group.addChild(c);
      }
    }

    /** Everything that is drawn at a fixed pixel size: nodes, handles, markers, the rubber band. Rebuilt per frame. */
    rebuildOverlay() {
      const layer = this.layers.overlay;
      layer.removeChildren();
      const px = 1 / this.zoom;
      const stroke = { strokeColor: BLUE, strokeWidth: 1.5 * px, parent: layer };
      const box = (p, size, fill) => new Path.Rectangle({ center: p, size: [size * px, size * px], fillColor: fill, ...stroke });
      const dot = (p, r, fill) => new Path.Circle({ center: p, radius: r * px, fillColor: fill, ...stroke });
      const line = (a, b, style) => new Path.Line({ from: a, to: b, parent: layer, ...style, strokeWidth: style.strokeWidth * px });

      if (this.mode === 'design') {
        if (this.editing) {
          const sh = this.editing, c = this.contour;
          if (sh.children.length > 1) { // the contour being edited is drawn thicker so a hole can be told from the outline
            const hl = c.clone({ insert: false });
            hl.style = { strokeColor: BLUE, strokeWidth: 2 * px, opacity: 0.8, fillColor: null, dashArray: [] };
            layer.addChild(hl);
          }
          const ctl = this.controlPoints();
          for (const k of ctl) line(c.segments[k.i].point, k.p, { strokeColor: BLUE, strokeWidth: 1 });
          c.segments.forEach((s, i) => box(s.point, 8, this.selNodes.has(i) ? BLUE : '#fff'));
          for (const k of ctl) dot(k.p, 4.5, k.ghost ? '#fff' : BLUE);
        }
        if (this.draft) {
          const segs = this.draft.path.segments;
          segs.forEach((s, i) => { if (i < segs.length - 1) box(s.point, 6, '#fff'); });
        }
        if (this.indicator && this.tool === 'pen') new Path.Circle({ center: this.indicator, radius: 6 * px, strokeColor: INK, strokeWidth: 2 * px, parent: layer });
      } else if (this.preview) {
        new Path.Circle({ center: S.toPaper(this.preview.origin), radius: 7 * px, strokeColor: INK, strokeWidth: 2 * px, parent: layer });
      }
      if (this.mode !== 'design' && this.marker) {
        const q = S.toPaper(this.marker), r = 9 * px;
        const style = { strokeColor: BLUE, strokeWidth: 3 };
        line(q.add([-r, 0]), q.add([r, 0]), style);
        line(q.add([0, -r]), q.add([0, r]), style);
      }
      if (this.rubber) {
        const r = new Rectangle(this.s2p(this.rubber.a), this.s2p(this.rubber.b));
        const rect = new Path.Rectangle({ rectangle: r, strokeColor: BLUE, strokeWidth: px, dashArray: [4 * px, 3 * px], fillColor: BLUE, parent: layer });
        rect.fillColor.alpha = 0.08;
      }
    }

    // ---- results of async operations ------------------------------------------------------

    /** Replace all shapes with a result from Python and select the shapes at `selected`. */
    replaceShapes(dicts, selected) {
      this.load(dicts);
      this.sel = new Set((selected || []).map((i) => this.shapes[i]).filter(Boolean));
      this.hooks.selectionChanged();
      this.commit();
    }
  }

  root.Canvas = Canvas;
})(window);
