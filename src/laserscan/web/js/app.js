/* LaserScan front end: panels, toolbar, shortcuts and the bridge to the Python side. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const G = window.Geom;

  /** pywebview injects `window.pywebview.api` (the Python `Api` object) and then fires `pywebviewready`. */
  function connectApi() {
    return new Promise((resolve) => {
      if (window.pywebview && window.pywebview.api) resolve(window.pywebview.api);
      else window.addEventListener('pywebviewready', () => resolve(window.pywebview.api), { once: true });
    });
  }

  async function main() {
    const api = await connectApi();
    const call = (name, ...args) => api[name](...args);
    const cfg = await call('init');
    const app = { mode: 'design', running: false, wasRunning: false, origin: [0, 0], profileKey: '', connected: false, lastTraffic: 0 };

    $('version').textContent = 'v' + cfg.version;

    // ---- platform-specific key names: ⌘ ⌥ ⇧ on macOS, Ctrl Alt Shift elsewhere -----------------
    const MAC = cfg.mac;
    const SYMBOL = { Mod: MAC ? '⌘' : 'Ctrl', Ctrl: MAC ? '⌃' : 'Ctrl', Alt: MAC ? '⌥' : 'Alt', Shift: MAC ? '⇧' : 'Shift' };
    const GLYPH = MAC ? { Tab: '⇥', Delete: '⌦', Backspace: '⌫', Enter: '↩', Esc: '⎋' } : {};
    const NAMED = new Set(['Tab', 'Home', 'Delete', 'Esc', 'Enter', 'Backspace']);
    /** 'Mod+Shift+Z' -> '⌘⇧Z' (macOS) or 'Ctrl+Shift+Z'. Parts that are not keys, like 'drag', keep a '+'. */
    function combo(text) {
      const parts = text.split('+');
      const names = parts.map((p) => SYMBOL[p] || GLYPH[p] || p);
      const keyLike = parts.every((p) => SYMBOL[p] || p.length === 1 || NAMED.has(p));
      return names.join(MAC && keyLike ? '' : '+');
    }
    /** Rewrite every modifier combination inside a sentence, e.g. a tooltip "(Ctrl+Shift+Z)". */
    const platformText = (s) => s.replace(/\b(?:(?:Ctrl|Mod|Alt|Shift)\+)+(?:[A-Za-z0-9]|Tab|Home|Delete)\b/g, (m) => combo(m.replace(/^Ctrl\+|(?<=\+)Ctrl\+/g, 'Mod+')));

    // ---- notices -----------------------------------------------------------------
    const show = (el, text, error) => {
      el.textContent = text || '';
      if (error !== undefined) el.classList.toggle('alert-error', !!error);
    };
    /** Report a message in the Terminal panel (not above the canvas, whose size must not change). */
    const notice = (text, error) => {
      if (text) appendTraffic([[Date.now() / 1000, error ? '!' : '•', text, false]]);
    };

    // ---- toolbar -----------------------------------------------------------------
    let canvas;
    const buttons = {};
    const designOnly = [];
    function pill(key, text, tip, onClick, opts = {}) {
      const b = document.createElement('button');
      b.className = 'pill' + (opts.on ? ' on' : '');
      b.textContent = text;
      b.title = tip || '';
      b.addEventListener('click', onClick);
      buttons[key] = b;
      if (opts.design !== false) designOnly.push(b);
      return b;
    }
    function group(caption, list) {
      const g = document.createElement('div');
      g.className = 'group';
      g.innerHTML = `<span class="caption">${caption.toUpperCase()}</span>`;
      g.append(...list);
      $('toolbar').append(g);
      return g;
    }
    const radio = (keys, current) => keys.forEach((k) => buttons[k].classList.toggle('on', k === current));

    group('View', [
      pill('design', 'Design', 'Design (Ctrl+1)', () => setView('design'), { on: true, design: false }),
      pill('preview', 'Preview', 'Preview (Ctrl+2)', () => setView('preview'), { design: false }),
      pill('fit', 'Fit', 'Fit the view (Home)', () => canvas.fit(), { design: false }),
      pill('fitStage', 'Fit stage', 'Fit the whole stage range (Shift+Home)', () => canvas.fitStage(), { design: false }),
    ]);
    group('Draw', [
      pill('select', 'Select', 'Select (W)', () => canvas.setTool('select'), { on: true }),
      pill('pen', 'Bézier pen', 'Bézier pen (Shift+A or W): click to place nodes, click the first node to close, Enter or right-click to finish. Then set node types and handles in Edit mode.', () => canvas.setTool('pen')),
    ]);
    const nodeTips = {
      sharp: 'Sharp: no handles, straight segments. With the pen: next nodes are corners',
      free: 'Free: the two handles move independently. With the pen: dragging pulls only the outgoing handle',
      smooth: 'Smooth: handles stay on one line. With the pen: dragging pulls both handles. Alt-drag a handle to break it',
      symmetric: 'Symmetric: handles on one line, equal length. With the pen: dragging pulls both handles equally',
    };
    const nodeKeys = ['sharp', 'free', 'smooth', 'symmetric'];
    group('Mode', [
      pill('object', 'Object', 'Select and move whole shapes (Tab)', () => canvas.exitEdit(), { on: true }),
      pill('edit', 'Edit', 'Edit the nodes of the selected shape (Tab). Double-click an edge to add a node.', () => { if (!canvas.enterEdit()) radio(['object', 'edit'], 'object'); }),
    ]);
    group('Node', nodeKeys.map((k, i) => pill('node_' + k, k[0].toUpperCase() + k.slice(1), `${nodeTips[k]} (${i + 1})`, () => pickNodeType(k))));
    group('Region', [
      pill('add', 'Add', 'New closed shapes add area (Alt+1)', () => chooseOp('add'), { on: true }),
      pill('subtract', 'Subtract', 'New closed shapes remove area (Alt+2)', () => chooseOp('subtract')),
      pill('merge', 'Merge', 'With two or more shapes selected: fuse them now. Otherwise new closed shapes add area and fuse with every shape they touch (Alt+3)', () => mergeAction()),
      pill('invert', 'Invert', 'Toggle Add / Subtract of the selected shapes (Shift+X)', () => canvas.invertOp()),
    ]);
    group('Edit', [
      pill('snap', 'Snap', 'Snap to the grid and to vertices (Shift+Tab)', () => toggleSnap(), { on: true }),
      pill('undo', 'Undo', 'Undo (Ctrl+Z)', () => canvas.undo()),
      pill('redo', 'Redo', 'Redo (Ctrl+Shift+Z)', () => canvas.redo()),
      pill('flipH', 'Flip H', 'Mirror the selection left-right on the screen; selected nodes in Edit mode (Shift+H)', () => canvas.flip('h')),
      pill('flipV', 'Flip V', 'Mirror the selection top-bottom on the screen; selected nodes in Edit mode (Shift+V)', () => canvas.flip('v')),
      pill('delete', 'Delete', 'Delete selected shapes (Delete)', () => canvas.deleteSelected()),
    ]);
    const chooseOp = (op) => { if (app.mode === 'design') { canvas.setNewOp(op); radio(['add', 'subtract', 'merge'], op); } };
    const toggleSnap = () => { canvas.snapOn = !canvas.snapOn; buttons.snap.classList.toggle('on', canvas.snapOn); canvas.render(); };

    // ---- canvas ------------------------------------------------------------------
    const frame = () => (app.mode === 'design' ? 'relative to start' : 'absolute');
    canvas = new window.Canvas($('stage-wrap'), {
      changed: () => scheduleReplan(),
      message: (text, error) => notice(text, error),
      cursor: (x, y) => { $('cursor').textContent = `X ${x.toFixed(1)} µm   Y ${y.toFixed(1)} µm  (${frame()})`; },
      editChanged: (on) => { radio(['object', 'edit'], on ? 'edit' : 'object'); syncNodeButtons(); },
      toolChanged: (tool) => { radio(['select', 'pen'], tool); syncNodeButtons(); },
      selectionChanged: () => syncNodeButtons(),
      merge: async (dicts, index) => {
        const r = await call('merge', dicts, index);
        if (r.message) notice(r.message, false);
        if (r.merged) canvas.replaceShapes(r.shapes, r.selected);
        else canvas.enterEdit();
      },
    });
    // With the pen tool the node buttons choose the type of the next nodes; in Edit mode they retype the selected nodes.
    const syncNodeButtons = () => nodeKeys.forEach((k) => {
      const b = buttons['node_' + k];
      b.disabled = !(canvas.editing || canvas.tool === 'pen');
      b.classList.toggle('on', canvas.tool === 'pen' && canvas.penType === k);
    });
    const pickNodeType = (k) => (canvas.tool === 'pen' ? canvas.setPenType(k) : canvas.setNodeType(k));
    syncNodeButtons();
    window.__canvas = canvas; // for the self-test

    /** Merge button: fuse the selected shapes now, or (nothing to fuse) make new shapes merge as they are drawn. */
    async function mergeAction() {
      if (app.mode !== 'design' || canvas.locked) return;
      if (canvas.sel.size < 2 || canvas.editing) { chooseOp('merge'); return; }
      const picked = canvas.shapes.map((s, i) => [s, i]).filter(([s]) => canvas.sel.has(s)).map(([, i]) => i);
      const r = await call('merge_selected', canvas.dicts(), picked);
      if (r.message) notice(r.message, !r.merged);
      if (r.merged) canvas.replaceShapes(r.shapes, r.selected);
    }

    // ---- scan parameters ---------------------------------------------------------
    const patternButtons = {};
    for (const p of cfg.patterns) {
      const b = document.createElement('button');
      b.className = 'pill' + (p === cfg.params.pattern ? ' on' : '');
      b.textContent = p[0].toUpperCase() + p.slice(1);
      b.addEventListener('click', () => { Object.values(patternButtons).forEach((x) => x.classList.remove('on')); b.classList.add('on'); scheduleReplan(); });
      patternButtons[p] = b;
      $('patterns').append(b);
    }
    const fields = ['step', 'angle', 'speed', 'margin', 'passes'];
    const params = () => ({
      pattern: Object.keys(patternButtons).find((k) => patternButtons[k].classList.contains('on')),
      ...Object.fromEntries(fields.map((f) => [f, Number($(f).value) || 0])),
      passes: Math.max(1, Math.round(Number($('passes').value) || 1)),
    });
    const setParams = (p) => {
      Object.entries(patternButtons).forEach(([k, b]) => b.classList.toggle('on', k === p.pattern));
      fields.forEach((f) => { $(f).value = p[f]; });
    };
    setParams(cfg.params);
    fields.forEach((f) => $(f).addEventListener('input', () => scheduleReplan()));

    // ---- planning ----------------------------------------------------------------
    let timer = 0, token = 0;
    function scheduleReplan() { clearTimeout(timer); timer = setTimeout(replan, 120); }

    function applyPlan(r) {
      app.origin = r.origin;
      show($('estimate'), r.estimate);
      show($('alerts'), r.problems.join('\n'));
      const o = r.origin;
      const plan = r.plan.map((s) => ({ pts: s.p.map((p) => [p[0] + o[0], p[1] + o[1]]), laser: s.l, bad: s.bad }));
      const transit = [];
      let here = o;
      for (const s of plan) { transit.push([here, s.pts[0]]); here = s.pts[s.pts.length - 1]; }
      const all = plan.flatMap((s) => s.pts).concat([o]);
      const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
      canvas.setPreview({
        plan, transit, origin: o, exceeds: plan.some((s) => s.bad),
        region: r.region.map((ring) => ring.map((p) => [p[0] + o[0], p[1] + o[1]])),
        bounds: [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)],
      });
    }

    async function replan() {
      const mine = ++token;
      const r = await call('replan', canvas.dicts(), params());
      if (mine === token) applyPlan(r);
    }

    // ---- views ---------------------------------------------------------------------
    async function setView(mode) {
      if (app.running || mode === app.mode) return;
      radio(['design', 'preview'], mode);
      app.mode = mode;
      if (mode === 'preview') await call('set_view', mode);
      await replan();
      canvas.setMode(mode);
      lockDesign(mode !== 'design');
    }

    function lockDesign(locked) {
      designOnly.forEach((b) => { b.disabled = locked; });
      if (!locked) syncNodeButtons();
      else nodeKeys.forEach((k) => { buttons['node_' + k].disabled = true; });
    }

    // ---- devices ---------------------------------------------------------------------
    const stagePort = new UI.Dropdown($('stage-port'), { options: [], value: null });
    const shutterPort = new UI.Dropdown($('shutter-port'), { options: [], value: null });
    const fillPorts = (ports, simulate) => {
      const opts = (list) => list.map((p) => ({ label: p, value: p }));
      if (simulate) {
        stagePort.setOptions(opts(['Simulated']), 'Simulated');
        shutterPort.setOptions(opts(['Simulated']), 'Simulated');
        stagePort.setDisabled(true);
        shutterPort.setDisabled(true);
        return;
      }
      const list = (def) => (ports.includes(def) ? ports : ports.concat(def));
      stagePort.setOptions(opts(list(cfg.defaultPorts[0])), cfg.defaultPorts[0]);
      shutterPort.setOptions(opts(['None'].concat(list(cfg.defaultPorts[1]))), cfg.defaultPorts[1]);
    };
    fillPorts(cfg.ports, cfg.simulate);

    $('connect').addEventListener('click', async () => {
      if (app.running) { show($('device-msg'), 'Abort the run first.'); return; }
      show($('device-msg'), '');
      $('connect').disabled = true;
      const r = await call(app.connected ? 'disconnect_devices' : 'connect_devices', stagePort.value || '', shutterPort.value || '');
      $('connect').disabled = false;
      if (r.error) show($('device-msg'), r.error);
      else if (r.note) show($('device-msg'), r.note);
      replan();
    });

    // ---- run controls ----------------------------------------------------------------
    $('start').addEventListener('click', async () => {
      notice('', false);
      const r = await call('start', canvas.dicts(), params(), app.mode);
      if (r.plan) applyPlan(r);
      if (r.error) notice(r.error, true);
    });
    $('pause').addEventListener('click', () => call('toggle_pause'));
    $('abort').addEventListener('click', () => call('abort'));

    function onRunStart() {
      app.mode = 'monitor';
      radio(['design', 'preview'], '');
      canvas.clearProgress();
      canvas.setMode('monitor');
      canvas.locked = true;
      lockDesign(true);
      fields.forEach((f) => { $(f).disabled = true; });
      Object.values(patternButtons).forEach((b) => { b.disabled = true; });
      $('monitor-badge').hidden = false;
    }

    function onRunEnd(message) {
      canvas.clearProgress();
      app.mode = 'preview';
      radio(['design', 'preview'], 'preview');
      canvas.setMode('preview');
      canvas.locked = false;
      lockDesign(true);
      fields.forEach((f) => { $(f).disabled = false; });
      Object.values(patternButtons).forEach((b) => { b.disabled = false; });
      $('monitor-badge').hidden = true;
      if (message) notice('Run stopped: ' + message, true);
    }

    // ---- state pushed from Python ------------------------------------------------------
    const pad = (n, w = 2) => String(n).padStart(w, '0');
    const stamp = (t) => { const d = new Date(t * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`; };
    function appendTraffic(rows) {
      const mon = $('monitor'), hide = !!buttons.hidePoll && buttons.hidePoll.classList.contains('on');
      const lines = rows.filter((r) => !(r[3] && hide));
      if (!lines.length) return;
      const atEnd = mon.scrollTop + mon.clientHeight >= mon.scrollHeight - 4;
      for (const [t, dir, text] of lines) {
        const div = document.createElement('div');
        div.className = dir === '→' ? 'out' : dir === '!' ? 'err' : dir === '•' ? 'ev' : '';
        div.textContent = `${stamp(t)} ${dir} ${text}`;
        mon.append(div);
      }
      while (mon.childElementCount > 500) mon.firstChild.remove();
      if (atEnd) mon.scrollTop = mon.scrollHeight;
    }
    buttons.hidePoll = $('hide-poll');
    buttons.hidePoll.addEventListener('click', () => buttons.hidePoll.classList.toggle('on'));
    $('clear-monitor').addEventListener('click', () => { $('monitor').textContent = ''; });

    function onState(s) {
      app.connected = s.connected;
      app.running = s.running;
      $('connect').textContent = s.connected ? 'Disconnect' : 'Connect';
      $('connect').disabled = false;
      const status = s.connected ? (s.simulated ? 'Simulated devices connected' : 'Hardware devices connected') : 'Not connected';
      $('device-led').classList.toggle('on', s.connected);
      $('device-led').title = status;
      if (!cfg.simulate) { stagePort.setDisabled(s.connected); shutterPort.setDisabled(s.connected); }

      const key = JSON.stringify(s.profile);
      if (key !== app.profileKey) {
        app.profileKey = key;
        canvas.setStage(s.profile.x_range_um[0], s.profile.x_range_um[1], s.profile.y_range_um[0], s.profile.y_range_um[1]);
        replan();
      }
      if (s.running && !app.wasRunning) onRunStart();
      if (!s.running && app.wasRunning) onRunEnd(s.message);
      app.wasRunning = s.running;

      $('start').disabled = s.running || !s.connected || !s.canStart;
      $('pause').disabled = !s.running;
      $('pause').textContent = s.paused ? 'Resume' : 'Pause';
      $('abort').disabled = !s.running;
      $('led').classList.toggle('on', !!s.shutter);
      $('status').textContent = s.running ? `${s.paused ? 'Paused' : 'Running'} · ${s.done}/${s.total} points` : (s.message || 'Idle');
      $('progress').style.width = (s.total ? (100 * s.done) / s.total : 0) + '%';
      if (s.running && s.done) canvas.setProgress(s.seg, s.pt);
      if (app.mode !== 'design') canvas.setMarker(s.position);
      if (s.traffic.length) appendTraffic(s.traffic);
      if (s.deviceMsg !== undefined && s.deviceMsg !== app.deviceMsg) { app.deviceMsg = s.deviceMsg; show($('device-msg'), s.deviceMsg); }
    }
    /** The page polls the state (10 Hz): it is thread-safe, and a slow page never piles up events. */
    async function pollState() {
      for (;;) {
        try { onState(await call('state')); } catch (err) { console.error(err); }
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }

    // ---- files -----------------------------------------------------------------------
    async function openProject() {
      if (app.running) return;
      const r = await call('open_project');
      if (r.cancelled) return;
      if (r.error) { notice('Cannot open project: ' + r.error, true); return; }
      await setView('design');
      setParams(r.params);
      canvas.setShapes(r.shapes, true);
      canvas.fit();
      notice(r.differs ? 'The project was drawn for a different stage range than the connected stage.' : '', true);
    }
    async function saveProject(saveAs) {
      const r = await call('save_project', canvas.dicts(), params(), !!saveAs);
      if (r.error) notice(r.error, true);
      else if (r.name) notice('Saved ' + r.name + '.', false);
    }
    async function importDrawing() {
      if (app.running || app.mode !== 'design') { notice('Switch to Design (and stop any run) to import.', true); return; }
      const r = await call('import_drawing');
      if (r.cancelled) return;
      if (r.error) { notice(r.error, true); return; }
      canvas.setShapes(canvas.dicts().concat(r.shapes), true);
      canvas.fit();
      notice(r.message + ' Move or scale with G / S.', false);
    }
    async function importBitmap() {
      if (app.running || app.mode !== 'design') { notice('Switch to Design (and stop any run) to import.', true); return; }
      if (document.querySelector('.modal-back')) return;
      const r = await call('open_bitmap');
      if (r.cancelled) return;
      if (r.error) { notice(r.error, true); return; }
      // Grey values for the live preview (the same pixels Python traces).
      const img = new Image();
      await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = r.png; });
      const view = document.createElement('canvas');
      view.width = r.w; view.height = r.h;
      const vctx = view.getContext('2d', { willReadFrequently: true });
      vctx.drawImage(img, 0, 0);
      const grey = vctx.getImageData(0, 0, r.w, r.h);
      const out = vctx.createImageData(r.w, r.h);

      const back = document.createElement('div');
      back.className = 'modal-back bitmap';
      back.innerHTML = `<div class="modal bitmap-dialog" role="dialog" aria-label="Import bitmap">
        <div class="card-head"><h2>Import bitmap</h2><span class="muted small" id="bm-name"></span></div>
        <div class="bitmap-body">
          <div class="bitmap-preview"></div>
          <div class="bitmap-controls">
            <div class="field"><label class="field-label">Threshold <span class="muted" id="bm-th-val"></span></label>
              <div class="row"><input id="bm-th" type="range" min="1" max="255" step="1"><button class="btn compact" id="bm-auto" type="button">Auto</button></div></div>
            <label class="check"><input id="bm-invert" type="checkbox"> Scan the bright parts</label>
            <div class="field"><label class="field-label">Width on stage (µm)</label><input class="input" id="bm-width" type="number" min="1" step="any" value="1000"><div class="muted small" id="bm-size"></div></div>
            <div class="field"><label class="field-label">Remove specks up to (px)</label><input class="input" id="bm-speck" type="number" min="0" step="1" value="4"></div>
            <div class="field"><label class="field-label">Smoothness <span class="muted" id="bm-sm-val"></span></label><input id="bm-smooth" type="range" min="0" max="1.33" step="0.01" value="1"></div>
            <div class="muted small">The preview shows the threshold only; specks and smoothness apply when importing.</div>
          </div>
        </div>
        <div class="alert alert-error" id="bm-error"></div>
        <div class="actions"><button class="btn" id="bm-cancel" type="button">Cancel</button><button class="btn btn-primary" id="bm-ok" type="button">Import</button></div>
      </div>`;
      document.body.append(back);
      const q = (id) => back.querySelector('#' + id);
      back.querySelector('.bitmap-preview').append(view);
      q('bm-name').textContent = r.name;
      q('bm-th').value = r.otsu;

      const [onR, onG, onB] = [245, 184, 0];
      function draw() {
        const th = +q('bm-th').value, invert = q('bm-invert').checked;
        q('bm-th-val').textContent = th;
        q('bm-sm-val').textContent = (+q('bm-smooth').value).toFixed(2);
        const src = grey.data, dst = out.data;
        for (let i = 0; i < src.length; i += 4) {
          const on = invert ? src[i] >= th : src[i] < th;
          dst[i] = on ? onR : 236; dst[i + 1] = on ? onG : 238; dst[i + 2] = on ? onB : 241; dst[i + 3] = 255;
        }
        vctx.putImageData(out, 0, 0);
        const w = +q('bm-width').value;
        q('bm-size').textContent = w > 0 ? `${w} × ${(w * r.h / r.w).toFixed(1)} µm · ${(w / r.w).toFixed(3)} µm/px` : '';
      }
      const close = () => { back.remove(); call('close_bitmap'); };
      ['bm-th', 'bm-invert', 'bm-width', 'bm-smooth'].forEach((id) => q(id).addEventListener('input', draw));
      q('bm-auto').addEventListener('click', () => { q('bm-th').value = r.otsu; draw(); });
      q('bm-cancel').addEventListener('click', close);
      back.addEventListener('pointerdown', (e) => { if (e.target === back) close(); });
      back.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } });
      q('bm-ok').addEventListener('click', async () => {
        q('bm-ok').disabled = true;
        q('bm-ok').textContent = 'Tracing…';
        await new Promise((resolve) => setTimeout(resolve, 30)); // let the button repaint before the blocking call
        const t = await call('trace_bitmap', {
          threshold: +q('bm-th').value, invert: q('bm-invert').checked, width: +q('bm-width').value,
          speckle: +q('bm-speck').value, smooth: +q('bm-smooth').value,
        });
        if (t.error) { show(q('bm-error'), t.error, true); q('bm-ok').disabled = false; q('bm-ok').textContent = 'Import'; return; }
        close();
        canvas.setShapes(canvas.dicts().concat(t.shapes), true);
        canvas.fit();
        notice(t.message + ' Move or scale with G / S.', false);
      });
      draw();
      q('bm-ok').focus();
    }
    async function exportPlan() {
      const r = await call('export_plan', canvas.dicts(), params());
      if (r.error) notice(r.error, true);
      else if (r.name) notice('Exported ' + r.name + ' (coordinates relative to the start position).', false);
    }
    const FILE_ACTIONS = { open: openProject, import: importDrawing, bitmap: importBitmap, save: () => saveProject(false), saveas: () => saveProject(true), export: exportPlan };
    new UI.Dropdown($('files-menu'), {
      menu: true, label: 'Files',
      options: [
        { label: 'Open project…', value: 'open', kbd: combo('Mod+O') },
        { label: 'Import drawing…', value: 'import', kbd: combo('Mod+Shift+I') },
        { label: 'Import bitmap…', value: 'bitmap', kbd: combo('Mod+Shift+B') },
        { sep: true },
        { label: 'Save', value: 'save', kbd: combo('Mod+S') },
        { label: 'Save as…', value: 'saveas', kbd: combo('Mod+Shift+S') },
        { sep: true },
        { label: 'Export path…', value: 'export', kbd: combo('Mod+Shift+E') },
      ],
      onChange: (v) => FILE_ACTIONS[v](),
    });

    // ---- shortcut guide --------------------------------------------------------------------
    const GUIDE = [
      ['View', [['Mod+1 / Mod+2', 'Design / Preview'], ['Home', 'Fit the view'], ['Shift+Home', 'Fit the stage']]],
      ['Draw', [['W', 'Switch Select / Bézier pen'], ['Shift+A', 'Bézier pen'], ['Click, drag', 'Place a node, pull its handles'], ['Click first node', 'Close the path'], ['Enter, double-click, right-click', 'Finish the path'], ['Esc', 'Cancel']]],
      ['Mode and nodes', [['Tab', 'Object / Edit mode'], ['1 / 2 / 3 / 4', 'Node type: Sharp, Free, Smooth, Symmetric (pen and Edit)'], ['Double-click edge', 'Add a node (Edit)'], ['Alt+drag handle', 'Break a Smooth node (Edit)'], ['E', 'Extrude the selected nodes (Edit)']]],
      ['Region', [['Alt+1 / Alt+2', 'New shapes add / subtract area'], ['Alt+3', 'Merge: fuse the selected shapes, or merge new shapes as drawn'], ['Shift+X', 'Invert Add / Subtract']]],
      ['Selection and edit', [['A / Alt+A', 'Select all / none'], ['Shift+H / Shift+V', 'Flip left-right / top-bottom (nodes in Edit)'], ['Mod+I', 'Invert the selection'], ['Shift+D', 'Duplicate'], ['Delete / X / Backspace', 'Delete'], ['Mod+Z / Mod+Shift+Z', 'Undo / redo'], ['Shift+Tab', 'Snap on / off']]],
      ['Transform', [['G / R / S', 'Grab / rotate / scale'], ['X / Y', 'Lock to an axis'], ['Click, Enter', 'Confirm'], ['Right-click, Esc', 'Cancel']]],
      ['Mouse and trackpad', [['Wheel', 'Zoom about the cursor'], ['Middle-drag', 'Pan'], ['Pinch', 'Zoom'], ['Press and drag', 'Box select']]],
      ['Files', [['Mod+O / Mod+S', 'Open / save'], ['Mod+Shift+S', 'Save as'], ['Mod+Shift+I', 'Import drawing: SVG, DXF, GDSII or CSV'], ['Mod+Shift+B', 'Import bitmap: PNG, JPEG, TIFF or WebP'], ['Mod+Shift+E', 'Export path: CSV, G-code or NPZ'], ['Mod+/', 'This guide']]],
    ];
    function closeGuide() { const g = document.querySelector('.modal-back'); if (g) g.remove(); }
    function toggleGuide() {
      if (document.querySelector('.modal-back.bitmap')) return;
      if (document.querySelector('.modal-back')) { closeGuide(); return; }
      const back = document.createElement('div');
      back.className = 'modal-back';
      back.innerHTML = `<div class="modal guide" role="dialog" aria-label="Keyboard shortcuts"><div class="card-head"><h2>Keyboard shortcuts</h2><button class="btn" id="guide-close">Close</button></div><div class="guide-body">${
        GUIDE.map(([title, rows]) => `<section><h3>${title}</h3>${rows.map(([k, d]) => `<div class="row"><span class="keys">${k.split(/ \/ /).map((part) => `<kbd>${combo(part)}</kbd>`).join('')}</span><span>${d}</span></div>`).join('')}</section>`).join('')
      }</div></div>`;
      back.addEventListener('pointerdown', (e) => { if (e.target === back) closeGuide(); });
      document.body.append(back);
      back.querySelector('#guide-close').addEventListener('click', closeGuide);
    }
    $('guide-link').innerHTML = `Shortcuts <kbd>${combo('Mod+/')}</kbd>`;
    $('guide-link').title = `Keyboard shortcuts (${combo('Mod+/')})`;
    $('guide-link').addEventListener('click', toggleGuide);

    // ---- keyboard ----------------------------------------------------------------------
    window.addEventListener('keydown', (e) => {
      if (/INPUT|TEXTAREA/.test(e.target.tagName)) return;
      if (e.key === 'Escape' && document.querySelector('.modal-back')) { closeGuide(); return; }
      const mod = e.ctrlKey || e.metaKey, code = e.code;
      if (mod && !e.shiftKey && !e.altKey && (code === 'Slash' || e.key === '/')) { e.preventDefault(); toggleGuide(); return; }
      if (document.querySelector('.modal-back')) return;
      if (mod && code === 'KeyO') { e.preventDefault(); openProject(); return; }
      if (mod && code === 'KeyS') { e.preventDefault(); saveProject(e.shiftKey); return; }
      if (mod && e.shiftKey && code === 'KeyI') { e.preventDefault(); importDrawing(); return; }
      if (mod && e.shiftKey && code === 'KeyB') { e.preventDefault(); importBitmap(); return; }
      if (mod && e.shiftKey && code === 'KeyE') { e.preventDefault(); exportPlan(); return; }
      if (mod && code === 'Digit1') { e.preventDefault(); setView('design'); return; }
      if (mod && code === 'Digit2') { e.preventDefault(); setView('preview'); return; }
      if (mod && code === 'KeyZ') { e.preventDefault(); e.shiftKey ? canvas.redo() : canvas.undo(); return; }
      if (mod && code === 'KeyY') { e.preventDefault(); canvas.redo(); return; }
      if (document.activeElement !== canvas.el) return;
      if (canvas.key(e)) { e.preventDefault(); return; }
      if (code === 'Home') { e.preventDefault(); e.shiftKey ? canvas.fitStage() : canvas.fit(); return; }
      if (app.mode !== 'design' || canvas.locked) return;
      const done = (fn) => { e.preventDefault(); fn(); };
      if (code === 'Tab') return done(() => (e.shiftKey ? toggleSnap() : canvas.toggleEdit()));
      if (e.altKey && code === 'KeyA') return done(() => canvas.deselectAll());
      if (e.altKey && ['Digit1', 'Digit2', 'Digit3'].includes(code)) return done(() => (code === 'Digit3' ? mergeAction() : chooseOp(['add', 'subtract'][+code.slice(5) - 1])));
      if (mod && code === 'KeyI') return done(() => canvas.invertSelection());
      if (mod || e.altKey) return;
      if (!e.shiftKey && ['Digit1', 'Digit2', 'Digit3', 'Digit4'].includes(code)) {
        if (canvas.editing || canvas.tool === 'pen') done(() => pickNodeType(nodeKeys[+code.slice(5) - 1]));
        return;
      }
      if (e.shiftKey && code === 'KeyA') return done(() => buttons.pen.click());
      if (e.shiftKey && code === 'KeyD') return done(() => canvas.duplicate());
      if (e.shiftKey && (code === 'KeyH' || code === 'KeyV')) return done(() => canvas.flip(code === 'KeyH' ? 'h' : 'v'));
      if (e.shiftKey && code === 'KeyX') return done(() => canvas.invertOp());
      switch (code) {
        case 'KeyW': return done(() => canvas.pickTool());
        case 'KeyA': return done(() => canvas.selectAll());
        case 'KeyG': return done(() => canvas.startTransform('grab'));
        case 'KeyR': return done(() => canvas.startTransform('rotate'));
        case 'KeyS': return done(() => canvas.startTransform('scale'));
        case 'KeyE': return done(() => canvas.extrude());
        case 'KeyX': case 'Delete': case 'Backspace': return done(() => canvas.deleteSelected());
        default:
      }
    });

    // ---- start -----------------------------------------------------------------------------
    document.querySelectorAll('[title]').forEach((el) => { el.title = platformText(el.title); });
    lockDesign(false);
    /** Checks run inside the real web view by `laserscan --selftest`: Paper.js drawing, hit tests, undo, transforms. */
    window.__selftest = () => {
      const failures = [];
      let passed = 0;
      const check = (name, ok, extra) => { if (ok) passed++; else failures.push(name + (extra ? ` (${extra})` : '')); };
      const before = canvas.dicts(), mode = canvas.mode;
      try {
        check('paper is loaded', typeof paper === 'object' && !!paper.version, String(window.paper));
        check('design view', canvas.mode === 'design', canvas.mode);
        const outer = { type: 'path', path: 'M-500,-500L500,-500L500,500L-500,500Z', op: 'add' };
        const hole = { type: 'path', path: 'M-100,-100L100,-100L100,100L-100,100Z', op: 'subtract' };
        canvas.setShapes([outer, hole], true);
        canvas.fitRect(-600, 600, -600, 600);
        canvas.draw();
        const alphaAt = (world) => {
          const [x, y] = canvas.w2s(world), dpr = window.devicePixelRatio || 1;
          return canvas.el.getContext('2d').getImageData(Math.round(x * dpr), Math.round(y * dpr), 1, 1).data[3];
        };
        check('fill is drawn', alphaAt([300, 300]) > 0, String(alphaAt([300, 300])));
        check('subtract cuts a hole', alphaAt([0, 0]) === 0, String(alphaAt([0, 0])));
        check('hit test finds the outer shape', canvas.hitShape(canvas.w2s([300, 300])) === canvas.shapes[0]);
        check('hit test finds the topmost shape', canvas.hitShape(canvas.w2s([0, 0])) === canvas.shapes[1]);
        check('nothing outside', canvas.hitShape(canvas.w2s([900, 900])) === null);
        canvas.selectAll();
        canvas.deleteSelected();
        check('delete', canvas.shapes.length === 0);
        canvas.undo();
        check('undo', canvas.shapes.length === 2 && JSON.stringify(canvas.dicts()) === JSON.stringify([outer, hole].map((d) => Shapes.shapeToDict(Shapes.shapeFromDict(d)))));
        canvas.setShapes([{ type: 'path', path: 'M0,0L100,0L0,50Z', op: 'add' }], true);
        const start = JSON.stringify(canvas.dicts());
        canvas.selectAll();
        canvas.flip('h');
        check('flip changes the shape', JSON.stringify(canvas.dicts()) !== start);
        canvas.flip('h');
        check('flip twice restores it', JSON.stringify(canvas.dicts()) === start);
      } catch (err) {
        failures.push('exception: ' + (err && err.stack || err));
      } finally {
        canvas.setShapes(before, false);
        canvas.history = [JSON.stringify(before)];
        canvas.hidx = 0;
        if (canvas.mode !== mode) canvas.setMode(mode);
      }
      return { passed, failures };
    };

    await call('ready');
    replan();
    pollState();
    window.__ready = true;
  }

  window.addEventListener('DOMContentLoaded', main);
})();
