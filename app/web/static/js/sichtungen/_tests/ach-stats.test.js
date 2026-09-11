// ─── sichtungen/_tests/ach-stats.test.js ───────────────────────────────────
// The line under the medal.
//
// „trage je Dossier: wie oft gesehen, wann das erste Mal und wie oft je
// Tag ca?!" — the first of the three was already on the tile TWICE (the
// medal badge says „12×" and the footline said „12× gesehen"), so the
// line now carries the two facts the tile could not say instead.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { sightingStatsLine } from '../_ach-defs.js';

test('both halves, German decimal comma', () => {
  assert.equal(
    sightingStatsLine({ date: '2026-09-09T07:06:31', per_day: 1.5 }),
    'seit 09.09. · ⌀ 1,5/Tag',
  );
});

test('a whole number keeps no trailing comma-zero', () => {
  assert.equal(
    sightingStatsLine({ date: '2026-08-01T00:00:00', per_day: 3 }),
    'seit 01.08. · ⌀ 3/Tag',
  );
});

test('a rate of zero is left out, not printed as a lie', () => {
  // „⌀ 0/Tag" beside an unlocked medal would say the species is never
  // there, next to the proof that it was.
  assert.equal(sightingStatsLine({ date: '2026-09-09T07:06:31', per_day: 0 }), 'seit 09.09.');
});

test('an entry from before this shipped simply says nothing', () => {
  assert.equal(sightingStatsLine({ count: 4 }), '');
  assert.equal(sightingStatsLine(null), '');
  assert.equal(sightingStatsLine(undefined), '');
});

test('an unreadable date is not half a sentence', () => {
  assert.equal(sightingStatsLine({ date: 'irgendwann', per_day: 2 }), '⌀ 2/Tag');
});
