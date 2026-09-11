// ─── mediathek/_tests/nav-list.test.js ─────────────────────────────────────
// What the player pages through, and what happens when the clip it was
// handed is not in that list.
//
// „Der media player blättert nicht so die videos hin und her wie sie
// dahinter durch die filter in der mediathek ausgewählt sind." Three
// grids can open the same player and each has its own ordered set; the
// player read only ONE of them (the per-camera drilldown's pool) and,
// when the clip was not in it, silently started at index 0 — so „next"
// walked a list that had nothing to do with what was on screen.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { setMediaNavList, mediaNavList, navIndexOf } from '../_nav-list.js';

const item = (id) => ({ event_id: id });

test('the list is empty until a grid declares one', () => {
  setMediaNavList(null);
  assert.deepEqual(mediaNavList(), []);
});

test('whichever grid painted last owns the list', () => {
  setMediaNavList([item('a'), item('b')]);
  assert.deepEqual(
    mediaNavList().map((x) => x.event_id),
    ['a', 'b'],
  );
  // The merged feed paints over the drilldown: exactly one of the four
  // Mediathek states is ever visible, so last paint wins is the truth.
  setMediaNavList([item('x')]);
  assert.deepEqual(
    mediaNavList().map((x) => x.event_id),
    ['x'],
  );
});

test('junk never becomes a list', () => {
  setMediaNavList('nope');
  assert.deepEqual(mediaNavList(), []);
  setMediaNavList(undefined);
  assert.deepEqual(mediaNavList(), []);
});

test('an item in the list knows its neighbours', () => {
  const list = [item('a'), item('b'), item('c')];
  assert.equal(navIndexOf(list, 'a'), 0);
  assert.equal(navIndexOf(list, 'c'), 2);
});

test('an item that is NOT in the list has no neighbours', () => {
  // THE BUG. This used to resolve to 0, which is how a clip opened from
  // the merged feed began paging through the drilldown's pool.
  assert.equal(navIndexOf([item('a'), item('b')], 'fremd'), -1);
  assert.equal(navIndexOf([], 'a'), -1);
  assert.equal(navIndexOf(null, 'a'), -1);
  assert.equal(navIndexOf([item('a')], ''), -1);
  assert.equal(navIndexOf([item('a')], undefined), -1);
});

test('a list holding holes does not throw', () => {
  assert.equal(navIndexOf([null, undefined, item('b')], 'b'), 2);
});
