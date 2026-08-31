// ─── player/_tests/speed.test.js ────────────────────────────────────────
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SPEED_STEPS, applySpeedChange, formatSpeed, nextSpeed } from '../_speed.js';

test('nextSpeed cycles up through the full step list and wraps', () => {
  assert.equal(nextSpeed(0.5, 1), 1);
  assert.equal(nextSpeed(1, 1), 1.5);
  assert.equal(nextSpeed(1.5, 1), 2);
  assert.equal(nextSpeed(2, 1), 0.5); // wraps back to the start
});

test('nextSpeed cycles down and wraps the other way', () => {
  assert.equal(nextSpeed(1, -1), 0.5);
  assert.equal(nextSpeed(0.5, -1), 2); // wraps back to the end
});

test('nextSpeed snaps an off-step value (stale playbackRate) to the nearest step first', () => {
  // 1.3 is closest to 1.5 in SPEED_STEPS (dist 0.2 vs 0.3 to 1) — cycling
  // up from there lands on 2, not on 1.5 itself.
  assert.equal(nextSpeed(1.3, 1), 2);
});

test('SPEED_STEPS is the single source of truth the button and the label both read', () => {
  assert.deepEqual(SPEED_STEPS, [0.5, 1, 1.5, 2]);
});

test('formatSpeed renders the multiplier glyph', () => {
  assert.equal(formatSpeed(1), '1×');
  assert.equal(formatSpeed(1.5), '1.5×');
  assert.equal(formatSpeed(undefined), '1×'); // defaults rather than "undefined×"
});

test('applySpeedChange sets video.playbackRate and returns the new rate', () => {
  const video = { playbackRate: 1 };
  const rate = applySpeedChange(video, 1);
  assert.equal(rate, 1.5);
  assert.equal(video.playbackRate, 1.5);
});

test('applySpeedChange on a null video is a no-op, not a throw', () => {
  assert.equal(applySpeedChange(null, 1), null);
});
