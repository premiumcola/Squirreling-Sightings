// ─── vplayer/_tests/geometry.test.js ───────────────────────────────────────
// The two bbox schemas, folded into one.
//
// The case that earns this file is the first one: the SAME box, written
// in the two shapes the backend actually emits, must produce identical
// output. Every painter, interpolator, centroid and mask test in the old
// code was written twice because that was not true.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  boxCenter,
  maskProbePoint,
  normalizeBox,
  overlayRectFor,
  pointInAnyMask,
  pointInBox,
} from '../_geometry.js';

/** A 0..50 square, in the shape settings.json stores masks in. */
const SQUARE = [
  { x: 0, y: 0 },
  { x: 50, y: 0 },
  { x: 50, y: 50 },
  { x: 0, y: 50 },
];

test('both schemas describe the same box identically', () => {
  // tracks.json (recorded) stores corners; the live endpoint reports
  // origin + size. Same 40x30 box at (10, 20).
  const corners = normalizeBox({ x1: 10, y1: 20, x2: 50, y2: 50 });
  const originSize = normalizeBox([10, 20, 40, 30]);
  assert.deepEqual(corners, { x: 10, y: 20, w: 40, h: 30 });
  assert.deepEqual(corners, originSize);
});

test('a corner box stored the other way round is still that box', () => {
  const flipped = normalizeBox({ x1: 50, y1: 50, x2: 10, y2: 20 });
  assert.deepEqual(flipped, { x: 10, y: 20, w: 40, h: 30 });
});

test('a zero-area box is refused rather than painted as a dot', () => {
  assert.equal(normalizeBox({ x1: 10, y1: 20, x2: 10, y2: 50 }), null);
  assert.equal(normalizeBox({ x1: 10, y1: 20, x2: 50, y2: 20 }), null);
  assert.equal(normalizeBox([10, 20, 0, 30]), null);
  assert.equal(normalizeBox([10, 20, 40, 0]), null);
});

test('malformed and absent boxes return null, never a partial box', () => {
  assert.equal(normalizeBox(null), null);
  assert.equal(normalizeBox(undefined), null);
  assert.equal(normalizeBox([10, 20]), null);
  assert.equal(normalizeBox({ x1: 10, y1: 20 }), null);
  assert.equal(normalizeBox({ x1: 10, y1: 20, x2: NaN, y2: 50 }), null);
  assert.equal(normalizeBox([10, 20, NaN, 30]), null);
  assert.equal(normalizeBox('10,20,40,30'), null);
});

test('overlayRectFor scales a box onto the letterboxed picture', () => {
  // A 1920x1080 source in a 960x1080 box: width binds, k = 0.5, and the
  // picture is centred vertically with a (1080-540)/2 = 270 gutter.
  const box = normalizeBox([100, 200, 400, 300]);
  const r = overlayRectFor(box, 1920, 1080, 960, 1080);
  assert.deepEqual(r, { x: 50, y: 270 + 100, w: 200, h: 150 });
});

test('overlayRectFor at scale 1 is a pure translation by the gutter', () => {
  const box = normalizeBox([10, 20, 40, 30]);
  const r = overlayRectFor(box, 100, 100, 100, 100);
  assert.deepEqual(r, { x: 10, y: 20, w: 40, h: 30 });
});

test('overlayRectFor refuses to guess without source dimensions', () => {
  const box = normalizeBox([10, 20, 40, 30]);
  assert.equal(overlayRectFor(box, 0, 0, 390, 220), null);
  assert.equal(overlayRectFor(box, 1920, 0, 390, 220), null);
  assert.equal(overlayRectFor(null, 1920, 1080, 390, 220), null);
});

test('overlayRectFor returns null for an unmeasured destination box', () => {
  // Before first layout. A caller drawing into this would place every
  // box at the origin; null makes it skip the paint instead.
  const box = normalizeBox([10, 20, 40, 30]);
  assert.equal(overlayRectFor(box, 1920, 1080, 0, 0), null);
});

test('boxCenter is the middle of the box, in the box own space', () => {
  assert.deepEqual(boxCenter(normalizeBox([10, 20, 40, 30])), { x: 30, y: 35 });
  assert.equal(boxCenter(null), null);
});

test('the mask probe point is the bottom centre — where the feet are', () => {
  // A mask marks ground the operator does not care about, so what
  // decides exclusion is where the subject stands, not its centroid.
  const box = normalizeBox([10, 20, 40, 30]);
  assert.deepEqual(maskProbePoint(box), { x: 30, y: 50 });
  assert.equal(maskProbePoint(null), null);
});

test('a point inside a mask polygon is masked, outside is not', () => {
  assert.equal(pointInAnyMask(25, 25, 100, 100, [{ points: SQUARE }]), true);
  assert.equal(pointInAnyMask(75, 75, 100, 100, [{ points: SQUARE }]), false);
});

test('no masks, empty masks and short polygons all mean "not masked"', () => {
  assert.equal(pointInAnyMask(25, 25, 100, 100, null), false);
  assert.equal(pointInAnyMask(25, 25, 100, 100, []), false);
  assert.equal(pointInAnyMask(25, 25, 100, 100, [{ points: SQUARE.slice(0, 2) }]), false);
});

test('a mask drawn at a different resolution is scaled, not shifted', () => {
  // The polygon was outlined against a 200x200 source; the clip is
  // 100x100. Its 0..50 square therefore covers 0..25 of this frame.
  const mask = [{ points: SQUARE, source_w: 200, source_h: 200 }];
  assert.equal(pointInAnyMask(12, 12, 100, 100, mask), true);
  assert.equal(pointInAnyMask(40, 40, 100, 100, mask), false, 'without the scale this would hit');
});

test('pointInBox is half-open so neighbours cannot share a pixel', () => {
  const box = normalizeBox([10, 20, 40, 30]);
  assert.equal(pointInBox(box, 10, 20), true, 'the near corner is inside');
  assert.equal(pointInBox(box, 49.9, 49.9), true);
  assert.equal(pointInBox(box, 50, 50), false, 'the far corner belongs to the neighbour');
  assert.equal(pointInBox(box, 9.9, 30), false);
  assert.equal(pointInBox(null, 10, 20), false);
});
