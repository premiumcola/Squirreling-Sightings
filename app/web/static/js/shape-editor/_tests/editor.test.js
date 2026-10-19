// ─── shape-editor/_tests/editor.test.js ────────────────────────────────────
// „Die Punkte am Rand kann man nicht greifen … man kann die Punkte aus dem
// Rahmen herausziehen … bei den Biegungen bleibt der Endpunkt der Tangente
// am Rand hängen."
//
// The editor's arithmetic: frame ↔ screen, clamping, edge snapping, the
// touch hit radius, and the bend handle that stays under the finger. The
// numbers are a 640 × 360 snapshot on an iPhone SE (≈ 300 CSS px wide)
// and on a desktop (≈ 1000 CSS px), the two places it was reported.

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.document = globalThis.document || { getElementById: () => null };

const {
  HIT_CSS,
  frameLayout,
  toCss,
  toFrameRaw,
  clampToFrame,
  hitRadius,
  controlForMidpoint,
  clampPolyToSource,
  fallbackFrame,
} = await import('../view.js');
const { segmentMidpoint } = await import('../geometry.js');
const { grabAt, applyDrag, straightenAt } = await import('../drag.js');
const { fitText } = await import('../draw-poly.js');
const { shapeState } = await import('../../core/state.js');

const FRAME = { w: 640, h: 360 };
// Canvas at (0,0); stage inset by the 12-px gutter.
const phone = frameLayout(
  { left: 0, top: 0 },
  { left: 12, top: 12, width: 300, height: 168.75 },
  FRAME,
);
const desk = frameLayout(
  { left: 0, top: 0 },
  { left: 12, top: 12, width: 1000, height: 562.5 },
  FRAME,
);

// ── frame ↔ screen ─────────────────────────────────────────────────────

test('frame and screen map onto each other through the gutter', () => {
  assert.deepEqual(toCss(phone, { x: 0, y: 0 }), { x: 12, y: 12 });
  assert.deepEqual(toCss(phone, { x: 640, y: 360 }), { x: 312, y: 180.75 });
  const back = toFrameRaw(phone, 162, 96.375);
  assert.ok(Math.abs(back.x - 320) < 1e-9 && Math.abs(back.y - 180) < 1e-9);
});

test('a tap in the gutter maps to a point outside the frame, before clamping', () => {
  // Raw is what hit tests see — a tap 8 px left of an edge vertex still
  // has to reach that vertex.
  assert.ok(toFrameRaw(phone, 4, 50).x < 0);
});

// ── keeping points inside the frame ────────────────────────────────────

test('a point dragged past the frame stops on its edge', () => {
  // Live data, 2026-10-19: x = 648 and y = −19 in a 640 × 360 zone.
  assert.deepEqual(clampToFrame(desk, { x: 648, y: -19 }), { x: 640, y: 0 });
});

test('a point near an edge lands on it, so a full-frame zone leaves no sliver', () => {
  // The live zones top out at x = 636 / y = 356: the editor never let
  // anyone reach the edge exactly.
  assert.deepEqual(clampToFrame(desk, { x: 636, y: 356 }), { x: 640, y: 360 });
  assert.deepEqual(clampToFrame(desk, { x: 2, y: 1 }), { x: 0, y: 0 });
});

test('the snap distance is in screen px, so it is not wider on a phone', () => {
  // 8 CSS px ≈ 17 frame units at phone scale, ≈ 5 at desktop scale.
  assert.equal(clampToFrame(phone, { x: 10, y: 100 }).x, 0);
  assert.equal(clampToFrame(desk, { x: 10, y: 100 }).x, 10);
});

test('away from the edges a point stays where it was put', () => {
  assert.deepEqual(clampToFrame(desk, { x: 320.4, y: 99.6 }), { x: 320, y: 100 });
});

test('snapping can be switched off for the bend handle', () => {
  assert.equal(clampToFrame(desk, { x: 638, y: 100 }, { snap: false }).x, 638);
  assert.equal(clampToFrame(desk, { x: 700, y: 100 }, { snap: false }).x, 640);
});

// ── the hit radius ─────────────────────────────────────────────────────

test('a finger gets a 44-px target, measured on screen, not in frame pixels', () => {
  // The old radius was 9 FRAME units ≈ 4 CSS px on a phone.
  assert.ok(HIT_CSS.touch * 2 >= 44);
  assert.ok(Math.abs(hitRadius(phone, 'touch') * phone.scale - HIT_CSS.touch) < 1e-9);
  assert.ok(hitRadius(phone, 'touch') > hitRadius(desk, 'touch'));
});

test('a mouse gets a tighter radius than a finger', () => {
  assert.ok(hitRadius(desk, 'mouse') < hitRadius(desk, 'touch'));
  assert.equal(hitRadius(desk, 'unknown'), hitRadius(desk, 'mouse'));
});

// ── the bend handle ────────────────────────────────────────────────────

test('the control point puts the curve middle exactly where the handle is', () => {
  const p0 = { x: 100, y: 300 };
  const p1 = { x: 500, y: 300 };
  const m = { x: 300, y: 200 };
  const cp = controlForMidpoint(p0, p1, m);
  assert.deepEqual(segmentMidpoint(p0, p1, cp), m);
});

test('a segment can be bent flush to the frame edge with the finger inside it', () => {
  // Before: the control point followed the finger, the curve middle only
  // went half-way, and reaching the edge meant dragging off the canvas.
  const cp = controlForMidpoint({ x: 100, y: 300 }, { x: 500, y: 300 }, { x: 300, y: 360 });
  assert.equal(segmentMidpoint({ x: 100, y: 300 }, { x: 500, y: 300 }, cp).y, 360);
  assert.ok(cp.y > 360, 'the control point itself may lie past the frame');
});

// ── repairing what is already stored ───────────────────────────────────

test('stored points outside their own frame are pulled onto the edge', () => {
  const poly = {
    source_w: 640,
    source_h: 360,
    points: [
      { x: 648, y: 10 },
      { x: 72, y: -19 },
    ],
  };
  assert.equal(clampPolyToSource(poly), true);
  assert.deepEqual(poly.points, [
    { x: 640, y: 10 },
    { x: 72, y: 0 },
  ]);
});

test('a polygon without a stamp is left alone — its frame is unknown', () => {
  const poly = { points: [{ x: 900, y: 10 }] };
  assert.equal(clampPolyToSource(poly), false);
  assert.equal(poly.points[0].x, 900);
});

test('without a snapshot the frame comes from the polygons themselves', () => {
  assert.deepEqual(fallbackFrame([{ points: [] }, { source_w: 640, source_h: 360 }]), FRAME);
  assert.deepEqual(fallbackFrame([]), { w: 1280, h: 720 });
});

// ── dragging ───────────────────────────────────────────────────────────

function _square() {
  shapeState.points = [];
  shapeState.masks = [];
  shapeState.zones = [
    {
      source_w: 640,
      source_h: 360,
      points: [
        { x: 100, y: 100 },
        { x: 500, y: 100 },
        { x: 500, y: 300 },
        { x: 100, y: 300 },
      ],
    },
  ];
  return shapeState.zones[0];
}

test('a vertex cannot be dragged out of the frame', () => {
  const z = _square();
  const d = grabAt({ x: 500, y: 300 }, 10);
  applyDrag(d, desk, { x: 900, y: 500 });
  assert.deepEqual(z.points[2], { x: 640, y: 360 });
});

test('grabbing off-centre does not make the vertex jump to the finger', () => {
  const z = _square();
  const d = grabAt({ x: 108, y: 104 }, 22);
  assert.equal(d.mode, 'vertex');
  applyDrag(d, desk, { x: 118, y: 104 });
  assert.deepEqual(z.points[0], { x: 110, y: 100 });
});

test('dragging a bend handle keeps it under the finger', () => {
  const z = _square();
  const d = grabAt({ x: 300, y: 300 }, 10);
  assert.equal(d.mode, 'midpoint');
  applyDrag(d, desk, { x: 300, y: 340 });
  const m = segmentMidpoint(z.points[2], z.points[3], z.curves[2]);
  assert.deepEqual(m, { x: 300, y: 340 });
});

test('a bend handle stops at the frame edge, and the curve reaches it', () => {
  const z = _square();
  const d = grabAt({ x: 300, y: 300 }, 10);
  applyDrag(d, desk, { x: 300, y: 900 });
  assert.equal(segmentMidpoint(z.points[2], z.points[3], z.curves[2]).y, 360);
});

test('while a new polygon is placed, bend handles do not answer', () => {
  _square();
  shapeState.points = [{ x: 10, y: 10 }];
  assert.equal(grabAt({ x: 300, y: 300 }, 10), null);
  shapeState.points = [];
});

test('straightening the last curve removes the key from the polygon', () => {
  const z = _square();
  const d = grabAt({ x: 300, y: 300 }, 10);
  applyDrag(d, desk, { x: 300, y: 340 });
  assert.equal(straightenAt({ x: 300, y: 340 }, 10), true);
  assert.equal('curves' in z, false);
});

// ── labels on the canvas ───────────────────────────────────────────────

test('a label that does not fit its polygon is shortened, not spilled', () => {
  const measure = (t) => t.length * 6;
  assert.equal(fitText('Person', 100, measure), 'Person');
  assert.equal(fitText('Person, Vogel, Eichhörnchen', 60, measure), 'Person, V…');
  assert.ok(measure(fitText('Person, Vogel, Eichhörnchen', 60, measure)) <= 60);
});
