// Node tests for weather/_time-binding.js — the auto-release rule.
//
// The Wetterdaten time chooser sits at the FOOT of the Mediathek
// section; the class / species / camera filters sit at the TOP. A
// narrowing set down there and still in force after the operator has
// moved on to a filter up here is invisible until it bites. So: it
// survives for as long as time is the only thing being touched, and
// releases itself the moment anything else is used.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { setZoomRange, clearZoomRange, isZoomActive } from '../_zoom.js';
import {
  TIME_SOURCE,
  releasesTimeBinding,
  onTimeBindingRelease,
  noteFilterUse,
} from '../_time-binding.js';

const bind = () => setZoomRange('2026-08-30T00:00:00', '2026-08-30T06:00:00');

// ── the rule on its own ─────────────────────────────────────────────────

test('any filter that is not the time chooser releases a bound range', () => {
  for (const source of ['label', 'species', 'camera', 'cam', 'category', 'library-chip', 'all']) {
    assert.equal(releasesTimeBinding(source, true), true, `${source} should release`);
  }
});

test('the time chooser itself does not release — last touch wins', () => {
  // „Wenn ich den Time Filter zuletzt verwendet hab und danach keine
  // anderen Filter, dann kann er stehen bleiben."
  assert.equal(releasesTimeBinding(TIME_SOURCE, true), false);
});

test('nothing bound is nothing to release', () => {
  assert.equal(releasesTimeBinding('label', false), false);
  assert.equal(releasesTimeBinding(TIME_SOURCE, false), false);
});

// ── the rule against the real zoom state ────────────────────────────────

test('a class pill click clears the chart range', () => {
  bind();
  assert.equal(isZoomActive(), true);
  assert.equal(noteFilterUse('label'), true);
  assert.equal(isZoomActive(), false, 'the binding must be gone, not merely hidden');
});

test('a species pill and a camera drilldown release it just the same', () => {
  for (const source of ['species', 'cam']) {
    bind();
    assert.equal(noteFilterUse(source), true, `${source} should release`);
    assert.equal(isZoomActive(), false);
  }
});

test('a library filter chip releases it too', () => {
  bind();
  assert.equal(noteFilterUse('library-chip'), true);
  assert.equal(isZoomActive(), false);
});

test('touching only the time chooser leaves the range standing', () => {
  bind();
  assert.equal(noteFilterUse(TIME_SOURCE), false);
  assert.equal(isZoomActive(), true, 'time may keep its own narrowing');
  clearZoomRange();
});

test('a filter click with no range bound is a no-op, not a phantom release', () => {
  clearZoomRange();
  assert.equal(noteFilterUse('label'), false);
  assert.equal(isZoomActive(), false);
});

test('a second filter click does not release twice', () => {
  bind();
  assert.equal(noteFilterUse('label'), true);
  assert.equal(noteFilterUse('label'), false, 'already released');
});

// ── subscribers (the chart redraws off these) ───────────────────────────

test('subscribers are told which filter released the binding, once', () => {
  const seen = [];
  const off = onTimeBindingRelease((source) => seen.push(source));
  try {
    bind();
    noteFilterUse('species');
    noteFilterUse('species'); // nothing bound any more
    noteFilterUse(TIME_SOURCE);
    assert.deepEqual(seen, ['species']);
  } finally {
    off();
  }
});

test('an unsubscribed listener stops hearing about releases', () => {
  let calls = 0;
  const off = onTimeBindingRelease(() => (calls += 1));
  bind();
  noteFilterUse('label');
  off();
  bind();
  noteFilterUse('label');
  assert.equal(calls, 1);
});

test('a subscriber may unsubscribe itself from inside its own callback', () => {
  let calls = 0;
  const off = onTimeBindingRelease(() => {
    calls += 1;
    off();
  });
  bind();
  assert.doesNotThrow(() => noteFilterUse('label'));
  bind();
  noteFilterUse('label');
  assert.equal(calls, 1);
  clearZoomRange();
});
