// ─── vplayer/_tests/overlay-svg.test.js ────────────────────────────────────
// The two things that have actually broken overlays in this codebase:
//
//   1. THE `inset` SHORTHAND. Assigning el.style.inset after the four
//      longhands resets left and top to `auto`; the layer drops to its
//      static position below the picture and the host's overflow:hidden
//      clips it away. That is the "no bboxes in the simulation view"
//      bug. It has been written twice and is still live in one place,
//      which is why the ban is a test here and not a comment.
//
//   2. A SECOND LETTERBOX SOLVE. Covered in geometry.test.js.
//
// Plus the trail's scoreScale, which has had a parameter and no caller
// since it was written — it is what dims a filtered track relative to a
// passing one.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildBoxSvg, buildTrail, overlayScale, placeOverlay } from '../_overlay-svg.js';

/** Minimal style-object stand-in: records what was assigned. */
function fakeEl() {
  return { style: {} };
}

test('placeOverlay writes the four longhands and never the shorthand', () => {
  const el = fakeEl();
  placeOverlay(el, { x: 12, y: 34, w: 200, h: 100 });
  const written = Object.keys(el.style);
  for (const prop of ['left', 'top', 'right', 'bottom', 'width', 'height']) {
    assert.ok(written.includes(prop), `${prop} not written`);
  }
  assert.equal(
    written.includes('inset'),
    false,
    'the inset shorthand resets left/top to auto — never write it',
  );
});

test('placeOverlay pins the near edges and releases the far ones', () => {
  const el = fakeEl();
  placeOverlay(el, { x: 12, y: 34, w: 200, h: 100 });
  assert.equal(el.style.left, '12px');
  assert.equal(el.style.top, '34px');
  assert.equal(el.style.right, 'auto');
  assert.equal(el.style.bottom, 'auto');
  assert.equal(el.style.width, '200px');
  assert.equal(el.style.height, '100px');
});

test('placeOverlay is a no-op on a missing element or rect', () => {
  const el = fakeEl();
  placeOverlay(null, { x: 0, y: 0, w: 1, h: 1 });
  placeOverlay(el, null);
  assert.deepEqual(el.style, {});
});

test('overlayScale converts CSS pixels into viewBox units', () => {
  // A 2560-wide source rendered 390 px wide: a 12 px font must be
  // authored at 12 * 6.56 viewBox units to render at 12 px.
  assert.equal(overlayScale(2560, 390), 2560 / 390);
  assert.equal(overlayScale(960, 960), 1);
});

test('overlayScale degrades to 1 rather than dividing by zero', () => {
  assert.equal(overlayScale(0, 390), 1);
  assert.equal(overlayScale(2560, 0), 1);
  assert.equal(overlayScale(NaN, 390), 1);
});

test('a box renders its rect, its stroke and its plate', () => {
  const svg = buildBoxSvg(
    { verdict: 'pass', score: 0.87, label: 'person', track_num: 2, bbox: [10, 20, 40, 30] },
    { k: 2, frameW: 960 },
  );
  assert.ok(svg.includes('<rect x="10" y="20" width="40" height="30"'));
  assert.ok(svg.includes('vector-effect="non-scaling-stroke"'), 'strokes must not scale');
  assert.ok(svg.includes('#2 · Person · 87 %'), 'the plate text belongs on the box');
});

test('both bbox schemas paint the same rect', () => {
  const opts = { k: 1, frameW: 960 };
  const det = { verdict: 'pass', score: 0.5, label: 'cat', track_num: 1 };
  const fromArray = buildBoxSvg({ ...det, bbox: [10, 20, 40, 30] }, opts);
  const fromCorners = buildBoxSvg({ ...det, bbox: { x1: 10, y1: 20, x2: 50, y2: 50 } }, opts);
  assert.equal(fromArray, fromCorners);
});

test('a weak box carries the dash array from MV_STATUS_STYLE', () => {
  const svg = buildBoxSvg({ status: 'weak', score: 0.3, bbox: [0, 0, 10, 10] }, { k: 1 });
  assert.ok(svg.includes('stroke-dasharray="6 4"'));
});

test('a confirmed box carries no dash attribute at all', () => {
  const svg = buildBoxSvg({ status: 'confirmed', score: 0.9, bbox: [0, 0, 10, 10] }, { k: 1 });
  assert.equal(svg.includes('stroke-dasharray'), false);
});

test('an undrawable box renders nothing rather than a malformed rect', () => {
  assert.equal(buildBoxSvg({ bbox: null }, {}), '');
  assert.equal(buildBoxSvg({ bbox: [10, 20, 0, 30] }, {}), '');
  assert.equal(buildBoxSvg({}, {}), '');
});

test('the plate flips below the box when the box hugs the top edge', () => {
  const atTop = buildBoxSvg(
    { verdict: 'pass', score: 0.5, label: 'cat', track_num: 1, bbox: [10, 0, 40, 30] },
    { k: 1, frameW: 960 },
  );
  // Plate y must be positive — below the box — not a negative offscreen
  // coordinate above it.
  const y = Number(/<rect [^>]*y="([-\d.]+)"[^>]*fill="rgba\(8,12,18/.exec(atTop)?.[1]);
  assert.ok(y >= 0, `plate placed offscreen at y=${y}`);
});

test('the label is escaped, so a crafted class name cannot inject markup', () => {
  const svg = buildBoxSvg(
    { verdict: 'pass', score: 0.5, label: '<script>x</script>', bbox: [0, 0, 10, 10] },
    { k: 1 },
  );
  assert.equal(svg.includes('<script>'), false);
});

test('a trail fades along its length and ends in a head dot', () => {
  const points = [
    { x: 0, y: 0 },
    { x: 10, y: 10 },
    { x: 20, y: 20 },
  ];
  const svg = buildTrail(points, '#22c55e');
  assert.ok(svg.includes('<line'), 'segments');
  assert.ok(svg.includes('<circle'), 'leading-edge head dot');
  const alphas = [...svg.matchAll(/stroke-opacity="([\d.]+)"/g)].map((m) => Number(m[1]));
  assert.ok(alphas.length >= 2);
  assert.ok(alphas[0] < alphas[alphas.length - 1], 'the ramp must brighten toward the head');
});

test('scoreScale dims a filtered track uniformly against a passing one', () => {
  const points = [
    { x: 0, y: 0 },
    { x: 10, y: 10 },
    { x: 20, y: 20 },
  ];
  const full = buildTrail(points, '#22c55e');
  const dimmed = buildTrail(points, '#22c55e', { scoreScale: 0.5 });
  const first = (s) => Number(/stroke-opacity="([\d.]+)"/.exec(s)[1]);
  assert.ok(dimmed !== full, 'scoreScale must actually reach the builder');
  assert.ok(first(dimmed) < first(full));
});

test('a trail of fewer than two points renders nothing', () => {
  assert.equal(buildTrail([], '#fff'), '');
  assert.equal(buildTrail([{ x: 1, y: 1 }], '#fff'), '');
});
