// Node tests for weather/_range-slider.js — the continuous time zoom.
//
// It began as five fixed range pills, became a slider that still snapped
// to those five, and is now free of them entirely: „Flüssiger slider
// nicht mit festen marken!". What survived the change is the rule the
// pills already had — the control may only reach as far as the buffer
// can actually fill — and what replaced them is a log scale, because the
// useful range spans 1 h to 720 h and on a linear track the whole first
// day would be unhittable with a thumb.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  archiveSpanHours,
  rangeBounds,
  hoursAtTick,
  tickAtHours,
  glyphOpacity,
} from '../_range-slider.js';

const ext = (oldest, newest, count = 99) => ({ oldest, newest, count });

// ── the archive's own reach ─────────────────────────────────────────────

test('archiveSpanHours reads the buffer extent', () => {
  assert.equal(archiveSpanHours(ext('2026-08-30T00:00:00', '2026-08-30T06:00:00')), 6);
  assert.equal(archiveSpanHours(ext('2026-08-23T12:00:00', '2026-08-30T12:00:00')), 168);
});

test('an extent that cannot say anything reads as unknown', () => {
  assert.equal(archiveSpanHours(null), null);
  assert.equal(archiveSpanHours(ext('2026-08-30T00:00:00', '2026-08-30T06:00:00', 1)), null);
  assert.equal(archiveSpanHours(ext('nonsense', 'also nonsense')), null);
  assert.equal(archiveSpanHours(ext('2026-08-30T06:00:00', '2026-08-30T00:00:00')), null);
});

// ── the reachable window ────────────────────────────────────────────────

test('a young archive stops the track short instead of offering empty months', () => {
  const b = rangeBounds(3, 1, 720);
  assert.equal(b.min, 1);
  assert.ok(b.max < 24, `a 3 h archive must not reach a day, got ${b.max}`);
});

test('the far end always covers everything the archive holds', () => {
  const b = rangeBounds(100, 1, 720);
  assert.ok(b.max >= 100, `the widest window must include all 100 h, got ${b.max}`);
});

test('an archive longer than the configured maximum stops at that maximum', () => {
  assert.equal(rangeBounds(5000, 1, 720).max, 720);
});

test('an unknown span is not treated as an empty archive', () => {
  assert.deepEqual(rangeBounds(null, 1, 720), { min: 1, max: 720 });
});

test('junk bounds still produce a usable, non-inverted range', () => {
  const b = rangeBounds(NaN, 'x', 'y');
  assert.ok(b.max >= b.min && b.min >= 1);
});

// ── the log scale ───────────────────────────────────────────────────────

test('the ends of the track are the ends of the range', () => {
  const b = rangeBounds(null, 1, 720);
  assert.equal(hoursAtTick(0, b), 1);
  assert.equal(hoursAtTick(1000, b), 720);
});

test('every doubling gets equal travel — that is the point of the log scale', () => {
  const b = rangeBounds(null, 1, 1024); // ten doublings
  const travel = (h) => tickAtHours(h, b);
  const first = travel(2) - travel(1);
  const last = travel(1024) - travel(512);
  assert.ok(
    Math.abs(first - last) <= 2,
    `1→2 h and 512→1024 h must cost the same travel, got ${first} vs ${last}`,
  );
});

test('a linear scale would have buried the first day; this one does not', () => {
  const b = rangeBounds(null, 1, 720);
  // 24 h sits past a third of the track rather than in the leftmost 3 %.
  assert.ok(tickAtHours(24, b) > 300, `24 h landed at ${tickAtHours(24, b)}`);
});

test('hours → tick → hours is exact: the handle never drifts off a window', () => {
  // The round trip is pinned on HOURS, not on ticks. Hours are whole
  // numbers, and low on a log track many ticks share one hour — so
  // tick→hours→tick legitimately moves the handle to that hour's own
  // position. What must not happen is the reverse: re-rendering a panel
  // showing 24 h must come back as 24 h, not 23 h.
  const b = rangeBounds(null, 1, 720);
  for (const hours of [1, 2, 6, 24, 72, 168, 336, 720]) {
    const back = hoursAtTick(tickAtHours(hours, b), b);
    assert.equal(back, hours, `${hours} h came back as ${back} h`);
  }
});

test('hours outside the range are clamped, never extrapolated', () => {
  const b = rangeBounds(null, 6, 48);
  assert.equal(tickAtHours(1, b), 0);
  assert.equal(tickAtHours(9999, b), 1000);
  assert.equal(hoursAtTick(-50, b), 6);
  assert.equal(hoursAtTick(99999, b), 48);
});

test('a range with nothing to choose between never divides by zero', () => {
  const b = { min: 24, max: 24 };
  assert.equal(hoursAtTick(500, b), 24);
  assert.equal(tickAtHours(24, b), 0);
});

test('junk positions resolve to the near end rather than NaN', () => {
  const b = rangeBounds(null, 1, 720);
  assert.equal(hoursAtTick('nonsense', b), 1);
  assert.equal(hoursAtTick(undefined, b), 1);
});

// ── the two end glyphs, which are the whole readout ─────────────────────
// „ohne text elemente nur symbole" — so the only thing that can say
// where the handle stands is how strongly each end is drawn.

test('the near end is brightest at the near end, and vice versa', () => {
  const near = glyphOpacity(0);
  const far = glyphOpacity(1000);
  assert.ok(near.near > near.far, 'a closed-in window must light the near glyph');
  assert.ok(far.far > far.near, 'a wide window must light the far glyph');
});

test('neither end ever disappears — the scale would lose its shape', () => {
  for (const tick of [0, 250, 500, 750, 1000]) {
    const o = glyphOpacity(tick);
    assert.ok(o.near >= 0.25 && o.far >= 0.25, `tick ${tick} hid an end: ${JSON.stringify(o)}`);
    assert.ok(o.near <= 1 && o.far <= 1);
  }
});

test('the midpoint reads as balanced', () => {
  const o = glyphOpacity(500);
  assert.ok(Math.abs(o.near - o.far) < 0.02);
});

test('junk positions still produce drawable opacities', () => {
  const o = glyphOpacity('nope');
  assert.ok(Number.isFinite(o.near) && Number.isFinite(o.far));
});
