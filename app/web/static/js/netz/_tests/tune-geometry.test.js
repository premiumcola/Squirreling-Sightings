// ─── netz/_tests/tune-geometry.test.js ──────────────────────────────────
// The settings radar is drawn at its chart box's own px size — these pin
// that the ring actually grows with the box, and that it never grows into
// the label rails or off the edge. Pure module, no DOM: the size the
// panel measures is just two numbers here.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  eFromEllipse,
  LABEL_OFF_X,
  LABEL_W,
  PAD_Y,
  radarGeometry,
  TUNE_H,
  TUNE_W,
  tunePolar,
} from '../_tune_geometry.js';

const RAIL = LABEL_W + LABEL_OFF_X;

// ── fallback ─────────────────────────────────────────────────────────

test('no size at all falls back to the 560 x 300 viewBox the panel shipped with', () => {
  const geo = radarGeometry();
  assert.equal(geo.w, TUNE_W);
  assert.equal(geo.h, TUNE_H);
  assert.equal(geo.cx, TUNE_W / 2);
  assert.equal(geo.cy, TUNE_H / 2);
});

test('a zero or negative dimension falls back per axis, not for both', () => {
  const geo = radarGeometry({ width: 0, height: 400 });
  assert.equal(geo.w, TUNE_W);
  assert.equal(geo.h, 400);
  assert.equal(radarGeometry({ width: 700, height: -1 }).h, TUNE_H);
});

test('the fallback is wider than it is tall — the rails need horizontal room', () => {
  assert.ok(TUNE_W > TUNE_H);
});

// ── the ring fills the box ───────────────────────────────────────────

test('the viewBox is the measured size, 1 unit = 1 px, rounded to whole px', () => {
  const geo = radarGeometry({ width: 669.6, height: 327.4 });
  assert.equal(geo.w, 670);
  assert.equal(geo.h, 327);
  assert.equal(geo.cx, 335);
  assert.equal(geo.cy, 163.5);
});

test('the ring reaches the label rail on both sides and the pad top and bottom', () => {
  const geo = radarGeometry({ width: 700, height: 340 });
  // Left edge of the ring sits exactly one rail + gap in from the box
  // edge, and mirrors on the right.
  const gap = geo.cx - geo.rx - RAIL;
  assert.ok(gap > 0 && gap <= 8, `ring-to-rail gap ${gap}`);
  assert.equal(geo.cx + geo.rx + RAIL + gap, geo.w);
  assert.equal(geo.cy - geo.ry, PAD_Y);
  assert.equal(geo.cy + geo.ry, geo.h - PAD_Y);
});

test('a bigger box means a bigger ring — nothing is letterboxed away', () => {
  const small = radarGeometry({ width: 560, height: 300 });
  const big = radarGeometry({ width: 840, height: 420 });
  assert.ok(big.rx > small.rx);
  assert.ok(big.ry > small.ry);
  // The whole gain in width goes to the ring: the rails are fixed-width.
  assert.equal(big.rx - small.rx, (840 - 560) / 2);
  assert.equal(big.ry - small.ry, (420 - 300) / 2);
});

test('the vertical pad clears the 44 px hit disc of a top or bottom vertex at E 100', () => {
  assert.ok(PAD_Y >= 22, `PAD_Y ${PAD_Y} < hit-disc radius 22`);
});

test('a box narrower than its two rails still yields a drawable ring', () => {
  const geo = radarGeometry({ width: 200, height: 120 });
  assert.ok(geo.rx > 0);
  assert.ok(geo.ry > 0);
});

// ── the label rails stay inside the box ───────────────────────────────

test('the right rail box ends inside the viewBox at every size', () => {
  [
    { width: 331, height: 260 },
    { width: 560, height: 300 },
    { width: 700, height: 340 },
    { width: 1100, height: 520 },
  ].forEach((size) => {
    const geo = radarGeometry(size);
    const right = geo.cx + geo.rx + LABEL_OFF_X + LABEL_W;
    const left = geo.cx - geo.rx - LABEL_OFF_X - LABEL_W;
    assert.ok(right <= geo.w, `${JSON.stringify(size)}: right rail ends at ${right} > ${geo.w}`);
    assert.ok(left >= 0, `${JSON.stringify(size)}: left rail starts at ${left} < 0`);
  });
});

// ── polar + inverse agree on whichever ring they are given ───────────

test('tunePolar and eFromEllipse round-trip on a non-default ring', () => {
  const geo = radarGeometry({ width: 900, height: 500 });
  [0, 1, 4, 7].forEach((i) => {
    [0.25, 0.6, 1].forEach((frac) => {
      const p = tunePolar(i, 10, frac, geo);
      assert.equal(eFromEllipse(p.x - geo.cx, p.y - geo.cy, geo), Math.round(frac * 100));
    });
  });
});

test('index 0 points straight up on the ring, whatever the box', () => {
  const geo = radarGeometry({ width: 777, height: 333 });
  const p = tunePolar(0, 13, 1, geo);
  assert.ok(Math.abs(p.x - geo.cx) < 1e-9);
  assert.ok(Math.abs(p.y - (geo.cy - geo.ry)) < 1e-9);
});
