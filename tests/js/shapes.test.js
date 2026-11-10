// Run: cd tests/js && npm install && npm test
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const web = path.join(__dirname, '..', '..', 'src', 'laserscan', 'web');
// Same Paper version as the vendored browser build; in Node it needs no DOM.
globalThis.paper = require('paper/dist/paper-core');
new paper.PaperScope().activate();
new paper.Project();
const S = require(path.join(web, 'js', 'shapes.js'));

const near = (a, b, eps = 1e-3) => assert.ok(Math.abs(a - b) <= eps, `${a} != ${b}`);

test('frame maps world (X, Y) to Paper (Y, -X) and back', () => {
  const p = S.toPaper([3, 5]);
  assert.deepEqual([p.x, p.y], [5, -3]);
  assert.deepEqual(S.toWorld(p), [3, 5]);
});

test('polygon with a hole round-trips through the project-file format', () => {
  const d = { type: 'path', path: 'M0,0L100,0L100,50L0,50ZM10,10L20,10L20,20L10,20Z', op: 'add' };
  const s = S.shapeFromDict(d);
  assert.equal(s.data.kind, 'polygon');
  assert.equal(s.children.length, 2);
  const out = S.shapeToDict(s);
  assert.equal(out.op, 'add');
  const again = S.shapeFromDict(out);
  assert.equal(again.children.length, 2);
  near(again.bounds.width, 50); // world X extent 0..50 becomes the Paper height; width is world Y: 100
});

test('bounds follow the frame: world X is Paper height', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0L100,0L100,50L0,50Z', op: 'add' });
  near(s.bounds.height, 100); // world X spans 0..100
  near(s.bounds.width, 50); // world Y spans 0..50
});

test('curve with handles keeps them and writes absolute C commands', () => {
  const d = { type: 'path', path: 'M0,0C0,20 30,20 30,0L15,-30Z', op: 'subtract' };
  const s = S.shapeFromDict(d);
  assert.equal(s.data.kind, 'polygon');
  assert.equal(s.children[0].segments.length, 3);
  const text = S.shapeToDict(s).path;
  assert.match(text, /^M0\.0000,0\.0000C/);
  assert.ok(text.endsWith('Z'));
  assert.equal(S.shapeToDict(s).op, 'subtract');
});

test('a closing curve that ends on the first node folds into it', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0C0,20 30,20 30,0C30,-20 15,-30 15,-10C10,-5 0,-5 0,0Z', op: 'add' });
  assert.equal(s.children[0].segments.length, 3);
});

test('open path is a polyline without op', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0L10,10L20,0' });
  assert.equal(s.data.kind, 'polyline');
  assert.equal('op' in S.shapeToDict(s), false);
});

test('older rect / circle / line dictionaries still load', () => {
  assert.equal(S.shapeFromDict({ type: 'rect', x0: 0, y0: 0, x1: 10, y1: 5, op: 'add' }).data.kind, 'polygon');
  const c = S.shapeFromDict({ type: 'circle', x0: -5, y0: -5, x1: 5, y1: 5, op: 'add' });
  assert.equal(c.children[0].segments.length, 4);
  assert.equal(c.children[0].data.types[0], 'symmetric');
  assert.equal(S.shapeFromDict({ type: 'line', x0: 0, y0: 0, x1: 4, y1: 4 }).data.kind, 'polyline');
});

test('garbage input gives no shape', () => {
  assert.equal(S.shapeFromDict({ type: 'path', path: 'M1,1' }), null);
  assert.equal(S.shapeFromDict({ type: 'nope' }), null);
});

test('node types are read from the handles', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0L10,0L10,10Z' });
  assert.deepEqual(s.children[0].data.types, ['sharp', 'sharp', 'sharp']);
});

test('set type smooth aligns the handles, symmetric equalises them', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0L100,0L100,100L0,100Z', op: 'add' });
  const p = s.children[0];
  S.setNodeType(p, [1], 'smooth');
  assert.equal(p.data.types[1], 'smooth');
  const seg = p.segments[1];
  near(seg.handleIn.cross(seg.handleOut), 0);
  assert.ok(seg.handleIn.dot(seg.handleOut) < 0);
  S.setNodeType(p, [1], 'symmetric');
  near(seg.handleIn.length, seg.handleOut.length);
  S.setNodeType(p, [1], 'sharp');
  assert.equal(S.hasHandle(seg.handleIn) || S.hasHandle(seg.handleOut), false);
});

test('moving a handle of a symmetric node mirrors the other one', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0L100,0L100,100L0,100Z', op: 'add' });
  const p = s.children[0];
  S.setNodeType(p, [1], 'symmetric');
  const seg = p.segments[1];
  S.moveControl(p, 1, 'out', seg.point.add(new paper.Point(30, 40)), true);
  near(seg.handleOut.length, 50);
  near(seg.handleIn.length, 50);
  near(seg.handleIn.x, -30);
});

test('inserting a node splits the curve and keeps the shape', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0L0,100L100,100L100,0Z', op: 'add' });
  const p = s.children[0];
  const before = p.length;
  const at = p.getPointAt(before / 8);
  const i = S.insertNode(p, at, 1);
  assert.equal(p.segments.length, 5);
  assert.equal(p.data.types.length, 5);
  near(p.length, before);
  assert.ok(i >= 1);
  assert.equal(S.insertNode(p, new paper.Point(1e6, 1e6), 1), null);
});

test('delete refuses to leave too few nodes; extrude adds sharp twins', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0L10,0L10,10L0,10Z', op: 'add' });
  const p = s.children[0];
  assert.equal(S.deleteNodes(p, [0, 1], S.MIN_NODES.polygon), false);
  assert.equal(S.deleteNodes(p, [0], S.MIN_NODES.polygon), true);
  assert.equal(p.segments.length, 3);
  assert.equal(p.data.types.length, 3);
  const made = S.extrudeNodes(p, new Set([1]));
  assert.equal(p.segments.length, 4);
  assert.deepEqual(made, [2]);
  assert.equal(p.data.types[2], 'sharp');
});

test('snapshot replay moves nodes with their handles and restores exactly', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0C0,20 30,20 30,0C30,-20 0,-20 0,0Z', op: 'add' });
  const p = s.children[0];
  const saved = S.snapshot(p, [0, 1]);
  const before = S.shapeToDict(s).path;
  S.applySnapshot(p, saved, (pt) => pt.add(new paper.Point(7, 3)));
  assert.notEqual(S.shapeToDict(s).path, before);
  S.restoreSnapshot(p, saved);
  assert.equal(S.shapeToDict(s).path, before);
});

test('copy keeps node types and is independent', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0L100,0L100,100L0,100Z', op: 'subtract' });
  S.setNodeType(s.children[0], [1], 'smooth');
  const c = S.copyShape(s);
  assert.equal(c.data.op, 'subtract');
  assert.equal(c.children[0].data.types[1], 'smooth');
  c.translate(new paper.Point(5, 5));
  assert.notEqual(S.shapeToDict(c).path, S.shapeToDict(s).path);
});

test('rounding noise after a rotation never prints as -0.0000', () => {
  const s = S.shapeFromDict({ type: 'path', path: 'M0,0L100,0L100,100L0,100Z', op: 'add' });
  s.rotate(90, s.bounds.center);
  assert.ok(!S.shapeToDict(s).path.includes('-0.0000'));
});
