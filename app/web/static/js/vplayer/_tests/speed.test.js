// ─── vplayer/_tests/speed.test.js ──────────────────────────────────────────
// The playback-speed ladder. „bitte integriere ein 1,5 2x 3x
// geschwindikgiet button!"
//
// The arithmetic is worth pinning because the button has no other state:
// one tap moves one rung, the label IS the rung, and an off-ladder rate
// arriving from somewhere else (a system-player handoff, a browser that
// clamped one) must not be able to strand the control on a value it can
// never leave.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { VP_SPEEDS, nextSpeed, speedLabel } from '../_speed.js';

test('the ladder is the one that was asked for', () => {
  assert.deepEqual(VP_SPEEDS, [1, 1.5, 2, 3]);
});

test('one tap moves one rung, and the top wraps back to normal', () => {
  assert.equal(nextSpeed(1), 1.5);
  assert.equal(nextSpeed(1.5), 2);
  assert.equal(nextSpeed(2), 3);
  // The only way back to 1× from a single button.
  assert.equal(nextSpeed(3), 1);
});

test('a rate between two rungs advances to the next one up', () => {
  // Not "snap to nearest, then step" — that can move the clip BACKWARDS
  // on a tap, which from a control whose whole job is "faster" is a bug
  // the operator would read as a dead button.
  assert.equal(nextSpeed(1.2), 1.5);
  assert.equal(nextSpeed(1.75), 2);
  assert.equal(nextSpeed(2.5), 3);
});

test('a rate above the ladder still comes home', () => {
  assert.equal(nextSpeed(4), 1);
  assert.equal(nextSpeed(16), 1);
});

test('a rung is recognised as itself despite float noise', () => {
  // 1.5 does not always come back out of a media element as exactly 1.5,
  // and a hair either side of a rung still means "I am on that rung" —
  // so the next tap is the one AFTER it, never the rung itself again.
  // Without the slack, 1.4999999 would step to 1.5 and the button would
  // look like it did nothing.
  assert.equal(nextSpeed(1.5000001), 2);
  assert.equal(nextSpeed(1.4999999), 2);
  assert.equal(nextSpeed(0.9999999), 1.5);
});

test('a missing or nonsensical rate is treated as normal speed', () => {
  for (const bad of [undefined, null, 0, -2, NaN, Infinity, 'fast']) {
    assert.equal(nextSpeed(bad), 1.5, String(bad));
  }
});

test('every rung is reachable from every other in at most four taps', () => {
  let rate = 1;
  const seen = new Set();
  for (let i = 0; i < VP_SPEEDS.length; i++) {
    seen.add(rate);
    rate = nextSpeed(rate);
  }
  const visited = [...seen].sort((a, b) => a - b);
  assert.deepEqual(visited, VP_SPEEDS);
  assert.equal(rate, 1, 'and the cycle closes');
});

// ── the label ──────────────────────────────────────────────────────────

test('the label uses the German decimal comma', () => {
  assert.equal(speedLabel(1.5), '1,5×');
  assert.doesNotMatch(speedLabel(1.5), /\./);
});

test('a whole rung carries no decimals at all', () => {
  assert.equal(speedLabel(1), '1×');
  assert.equal(speedLabel(2), '2×');
  assert.equal(speedLabel(3), '3×');
});

test('the label never reads NaN, undefined or 0×', () => {
  for (const bad of [undefined, null, 0, NaN, 'fast']) {
    assert.equal(speedLabel(bad), '1×', String(bad));
  }
});
