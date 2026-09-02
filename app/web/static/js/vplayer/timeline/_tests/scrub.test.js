// ─── vplayer/timeline/_tests/scrub.test.js ─────────────────────────────────
// The numeric core of drag-to-seek. The failure these guard against is
// not a wrong seek but a CONFIDENT one: an unlaid-out rail resolving
// every drag to 0, which looks like a working scrubber that always
// jumps to the start.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { pctFromRect, timeFromRect } from '../_scrub.js';

const RAIL = { left: 100, width: 200 };

test('pctFromRect maps a position across the rail', () => {
  assert.equal(pctFromRect(100, RAIL), 0);
  assert.equal(pctFromRect(200, RAIL), 0.5);
  assert.equal(pctFromRect(300, RAIL), 1);
});

test('pctFromRect clamps at both ends rather than running past them', () => {
  // A pointer-captured drag keeps reporting positions well outside the
  // rail — that is what capture is for.
  assert.equal(pctFromRect(-500, RAIL), 0);
  assert.equal(pctFromRect(5000, RAIL), 1);
});

test('a zero-width rect returns null instead of resolving to the start', () => {
  assert.equal(pctFromRect(150, { left: 100, width: 0 }), null);
  assert.equal(pctFromRect(150, { left: 100, width: -10 }), null);
  assert.equal(pctFromRect(150, null), null);
});

test('a non-finite pointer position returns null', () => {
  assert.equal(pctFromRect(NaN, RAIL), null);
  assert.equal(pctFromRect(undefined, RAIL), null);
});

test('timeFromRect scales the fraction onto the duration', () => {
  assert.equal(timeFromRect(100, RAIL, 60), 0);
  assert.equal(timeFromRect(200, RAIL, 60), 30);
  assert.equal(timeFromRect(300, RAIL, 60), 60);
});

test('duration 0 returns null — a live strip has nothing to seek', () => {
  assert.equal(timeFromRect(200, RAIL, 0), null);
  assert.equal(timeFromRect(200, RAIL, undefined), null);
  assert.equal(timeFromRect(200, RAIL, NaN), null);
  assert.equal(timeFromRect(200, RAIL, -1), null);
});

test('a zero-width rail returns null even with a real duration', () => {
  assert.equal(timeFromRect(150, { left: 100, width: 0 }, 60), null);
});

test('the seek time never leaves [0, duration]', () => {
  for (const x of [-1000, -1, 0, 150, 299, 300, 99999]) {
    const t = timeFromRect(x, RAIL, 60);
    assert.ok(t >= 0 && t <= 60, `t=${t} for clientX=${x}`);
  }
});
