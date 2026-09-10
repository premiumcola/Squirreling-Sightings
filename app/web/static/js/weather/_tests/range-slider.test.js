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
  formatRangeHours,
  zoneOpacity,
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

// ── the readout, which rides on the bar ────────────────────────────────
// „in der mitte irgendwo schon der aktuell gewählte zeitraum! In h day
// months!" — so the one label this control has must pick the unit that
// fits, at every point of a scale spanning three orders of magnitude.

test('hours below two days, days above, months above two', () => {
  assert.equal(formatRangeHours(1), '1 h');
  assert.equal(formatRangeHours(6), '6 h');
  assert.equal(formatRangeHours(47), '47 h');
  assert.equal(formatRangeHours(48), '2 d');
  assert.equal(formatRangeHours(168), '7 d');
  assert.equal(formatRangeHours(720), '30 d');
});

test('a month is a real month, so twelve of them are a year', () => {
  assert.equal(formatRangeHours(24 * 61), '2 Mon.');
  assert.equal(formatRangeHours(24 * 365.25), '12 Mon.');
});

test('an unusable range reads as a dash, never as "NaN h"', () => {
  assert.equal(formatRangeHours(0), '—');
  assert.equal(formatRangeHours(-5), '—');
  assert.equal(formatRangeHours(null), '—');
  assert.equal(formatRangeHours('nonsense'), '—');
});

test('every position on the scale produces a readable label', () => {
  const b = rangeBounds(null, 1, 720);
  for (let tick = 0; tick <= 1000; tick += 50) {
    const text = formatRangeHours(hoursAtTick(tick, b));
    assert.match(text, /^\d+ (h|d|Mon\.)$/, `tick ${tick} read as "${text}"`);
  }
});

// ── The two end markers ─────────────────────────────────────────────────
// „wenn ich links schiebe, dann will ich auf der Rechtsseite [...] irgend
// 'n Symbol haben, was für klein sein steht und langsam kräftiger wird
// [...] und wenn ich's nach rechts schiebe, verschwindet das Symbol
// rechts [...] und links taucht dann das große Symbol auf."
//
// So each marker lives in the half of the track the handle is NOT in,
// and fades as the handle comes toward it.

test('a handle at the near end lights the SMALL mark, on the right', () => {
  const o = zoneOpacity(0);
  assert.equal(o.near, 1);
  assert.equal(o.far, 0);
});

test('a handle at the far end lights the LARGE mark, on the left', () => {
  const o = zoneOpacity(1000);
  assert.equal(o.far, 1);
  assert.equal(o.near, 0);
});

test('the two always sum to one — never both solid, never both gone', () => {
  for (let tick = 0; tick <= 1000; tick += 50) {
    const o = zoneOpacity(tick);
    assert.ok(Math.abs(o.near + o.far - 1) < 1e-9, `tick ${tick}: ${JSON.stringify(o)}`);
  }
});

test('the change is gradual, not a switch', () => {
  const a = zoneOpacity(400);
  const b = zoneOpacity(500);
  const c = zoneOpacity(600);
  assert.ok(a.far > 0 && a.far < 1, 'mid-band must be part-way, not snapped');
  assert.ok(b.far > a.far && c.far > b.far, 'it has to move in one direction');
});

test('outside the crossfade band exactly one marker is up', () => {
  assert.equal(zoneOpacity(200).near, 1);
  assert.equal(zoneOpacity(800).far, 1);
});

test('junk positions still produce drawable opacities', () => {
  const o = zoneOpacity('nope');
  assert.ok(Number.isFinite(o.near) && Number.isFinite(o.far));
});
