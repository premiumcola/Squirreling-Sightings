// ─── netz/_tests/tune-geometry.test.js ──────────────────────────────────
// The settings radar is drawn at its chart box's own px size — these pin
// that the ring actually grows with the box, that it never grows into the
// label rails or off the edge, and that the rail keeps giving ground back
// to the ring as the box shrinks (the phone case, where the old flat
// 112 px reservation left an rx of 65). Pure module, no DOM: the size the
// panel measures is just two numbers here.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  eFromEllipse,
  labelWidthFor,
  PAD_Y,
  radarGeometry,
  RING_GAP,
  ringHalfWidthAt,
  TUNE_H,
  TUNE_W,
  tunePolar,
} from '../_tune_geometry.js';

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
  assert.equal(geo.cx - geo.rx, geo.labelW + RING_GAP);
  assert.equal(geo.cx + geo.rx + geo.labelW + RING_GAP, geo.w);
  assert.equal(geo.cy - geo.ry, PAD_Y);
  assert.equal(geo.cy + geo.ry, geo.h - PAD_Y);
});

test('a bigger box means a bigger ring — nothing is letterboxed away', () => {
  const small = radarGeometry({ width: 560, height: 300 });
  const big = radarGeometry({ width: 840, height: 420 });
  assert.ok(big.rx > small.rx);
  assert.ok(big.ry > small.ry);
  // Height goes to the ring one-for-one; width too, once the rail has hit
  // its cap and stops taking a share of the extra.
  assert.equal(big.ry - small.ry, (420 - 300) / 2);
  assert.equal(big.rx - small.rx, (840 - 560) / 2);
});

test('the vertical pad is exactly the 44 px hit disc of a top or bottom vertex', () => {
  assert.equal(PAD_Y, 22, 'the disc must stay whole, and not one px more may be spent');
  const geo = radarGeometry({ width: 700, height: 340 });
  const top = tunePolar(0, 12, 1, geo);
  assert.ok(top.y - 22 >= 0, 'the top vertex hit disc is clipped by the viewBox');
});

test('a box narrower than its two rails still yields a drawable ring', () => {
  const geo = radarGeometry({ width: 200, height: 120 });
  assert.ok(geo.rx > 0);
  assert.ok(geo.ry > 0);
});

// ── the rail gives ground back on a small box ─────────────────────────

test('the label rail scales with the box, between the two text-derived bounds', () => {
  assert.equal(labelWidthFor(355), 78); // a 375 px phone panel
  assert.equal(labelWidthFor(200), 68); // floor
  assert.equal(labelWidthFor(1200), 92); // cap
  assert.ok(labelWidthFor(500) > labelWidthFor(355));
});

test('the phone-sized ring is far bigger than the flat 112 px rail allowed', () => {
  // 375 px screen: the panel is ~355 px wide, the chart clamp 320 px tall.
  const geo = radarGeometry({ width: 355, height: 320 });
  const before = { rx: 355 / 2 - 112, ry: 260 / 2 - 24 };
  assert.ok(geo.rx > before.rx * 1.3, `rx ${geo.rx} vs ${before.rx}`);
  assert.ok(geo.ry > before.ry * 1.25, `ry ${geo.ry} vs ${before.ry}`);
});

// ── the label rails stay inside the box ───────────────────────────────

test('the right rail box ends inside the viewBox at every size', () => {
  [
    { width: 355, height: 320 },
    { width: 373, height: 330 },
    { width: 560, height: 300 },
    { width: 700, height: 340 },
    { width: 1100, height: 520 },
  ].forEach((size) => {
    const geo = radarGeometry(size);
    const right = geo.cx + geo.rx + RING_GAP + geo.labelW;
    const left = geo.cx - geo.rx - RING_GAP - geo.labelW;
    assert.ok(right <= geo.w, `${JSON.stringify(size)}: right rail ends at ${right} > ${geo.w}`);
    assert.ok(left >= 0, `${JSON.stringify(size)}: left rail starts at ${left} < 0`);
  });
});

// ── the ring's own width at a given height ───────────────────────────

test('ringHalfWidthAt is rx on the centre line and 0 at the poles', () => {
  const geo = radarGeometry({ width: 700, height: 340 });
  assert.equal(ringHalfWidthAt(geo, geo.cy), geo.rx);
  assert.equal(ringHalfWidthAt(geo, geo.cy - geo.ry), 0);
  assert.equal(ringHalfWidthAt(geo, geo.cy + geo.ry), 0);
  assert.equal(ringHalfWidthAt(geo, 0), 0, 'above the ring is not a negative width');
});

test('a row nearer the top clears the ring sooner than one at the centre', () => {
  const geo = radarGeometry({ width: 700, height: 340 });
  const near = ringHalfWidthAt(geo, geo.cy - geo.ry * 0.8);
  assert.ok(near < geo.rx * 0.62, `label at 80 % height still needs ${near} of ${geo.rx}`);
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
