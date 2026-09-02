// ─── core/_tests/clock-format.test.js ──────────────────────────────────────
// The playhead readout. These cases mirror the ones
// app/tests/test_recorded_player_chrome.py already pins through the DOM
// stub — kept here as well because this module is now the shared home
// and a second player reads it, so the contract should be provable
// without booting a stubbed DOM.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { clockLabel, remainingLabel } from '../clock-format.js';

test('clockLabel renders m:ss with a zero-padded seconds field', () => {
  assert.equal(clockLabel(0), '0:00');
  assert.equal(clockLabel(3), '0:03');
  assert.equal(clockLabel(61), '1:01');
  assert.equal(clockLabel(3599), '59:59');
});

test('clockLabel counts minutes past 60 rather than rolling to hours', () => {
  assert.equal(clockLabel(3600), '60:00');
  assert.equal(clockLabel(4325), '72:05');
});

test('clockLabel floors, so a playhead never ticks over early', () => {
  // The whole reason this is not mediathek's rounding _fmtDur: at 5.6 s
  // a rounded clock would already read 0:06.
  assert.equal(clockLabel(5.6), '0:05');
  assert.equal(clockLabel(0.9), '0:00');
  assert.equal(clockLabel(59.999), '0:59');
});

test('clockLabel degrades to 0:00 rather than NaN:NaN', () => {
  assert.equal(clockLabel(NaN), '0:00');
  assert.equal(clockLabel(Infinity), '0:00');
  assert.equal(clockLabel(-12), '0:00');
  assert.equal(clockLabel(undefined), '0:00');
  assert.equal(clockLabel(null), '0:00');
});

test('remainingLabel prefixes U+2212 MINUS SIGN, not an ASCII hyphen', () => {
  const out = remainingLabel(1, 6);
  assert.equal(out, '−0:05');
  assert.equal(out.charCodeAt(0), 0x2212);
  assert.notEqual(out.charCodeAt(0), 0x2d);
});

test('remainingLabel reads −0:00 at the end, never a positive value', () => {
  assert.equal(remainingLabel(6, 6), '−0:00');
  // A playhead reported past the duration (a seek race, a rounding
  // difference between currentTime and duration) must not flip sign.
  assert.equal(remainingLabel(9, 6), '−0:00');
});

test('remainingLabel treats a missing duration as zero remaining', () => {
  assert.equal(remainingLabel(3, NaN), '−0:00');
  assert.equal(remainingLabel(3, 0), '−0:00');
  assert.equal(remainingLabel(NaN, 6), '−0:06');
});
