// ─── vplayer/_tests/back-gesture.test.js ───────────────────────────────────
// „Zudem will ich aus dem player mit der iphone typischen am bildschirm
// seitlich zurück-wisch-bewegung raus gehen können."
//
// Only from the EDGE. Anywhere else on the picture a horizontal drag
// already means prev/next, and a gesture that stole those would be a
// worse bug than the one it fixed.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { isBackSwipe } from '../_back-gesture.js';

test('a firm drag from the left edge is "back"', () => {
  assert.equal(isBackSwipe(8, 90, 10), true);
  assert.equal(isBackSwipe(0, 64, 0), true);
});

test('the same drag from the middle of the picture is not', () => {
  // That one belongs to prev/next — see mediaview/keyboard.js.
  assert.equal(isBackSwipe(180, 120, 5), false);
  assert.equal(isBackSwipe(25, 120, 5), false);
});

test('a short tug is not a gesture', () => {
  assert.equal(isBackSwipe(5, 30, 2), false);
});

test('a leftward drag from the left edge is not "back"', () => {
  assert.equal(isBackSwipe(5, -90, 4), false);
});

test('a diagonal is someone scrolling, not going back', () => {
  assert.equal(isBackSwipe(5, 80, 70), false);
  assert.equal(isBackSwipe(5, 80, 200), false);
});
