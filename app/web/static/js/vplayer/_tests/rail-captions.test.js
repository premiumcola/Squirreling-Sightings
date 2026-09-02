// ─── vplayer/_tests/rail-captions.test.js ──────────────────────────────────
// The words that make the rail's bands mean something.
//
// The bug they close is not a crash: the pre- and post-roll hatching was
// on screen the whole time and said nothing, which the operator reported
// as "der Vorlauf ist auch nicht ersichtlich". So the cases worth pinning
// are the ones about SILENCE — a caption that appears when there is
// nothing to report is the same failure in the other direction, and a
// clip recorded before the pre-roll buffer existed is the common case.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { railCaptionsHtml } from '../timeline/_rail.js';

const model = (over = {}) => ({
  duration: 30,
  preRoll: 0,
  postRoll: 0,
  postRollT0: 30,
  firstEventT: null,
  ...over,
});

test('a clip with no pre- or post-roll gets no caption row at all', () => {
  assert.equal(railCaptionsHtml(model()), '');
});

test('the pre-roll is named in seconds', () => {
  const html = railCaptionsHtml(model({ preRoll: 4 }));
  assert.match(html, /Vorlauf 4 s/);
});

test('a fractional pre-roll reads with a German decimal comma', () => {
  assert.match(railCaptionsHtml(model({ preRoll: 2.5 })), /Vorlauf 2,5 s/);
});

test('a whole number never grows a decimal place', () => {
  const html = railCaptionsHtml(model({ preRoll: 4.0 }));
  assert.match(html, /Vorlauf 4 s/);
  assert.doesNotMatch(html, /4,0/);
});

test('the post-roll is named independently of the pre-roll', () => {
  const html = railCaptionsHtml(model({ postRoll: 5, postRollT0: 25 }));
  assert.match(html, /Nachlauf 5 s/);
  assert.doesNotMatch(html, /Vorlauf/);
});

test('the first-event caption needs a pre-roll to point past', () => {
  // With no pre-roll the clip starts AT the event, so "erstes Ereignis"
  // would label the left edge and say nothing the operator did not
  // already know.
  assert.doesNotMatch(railCaptionsHtml(model({ firstEventT: 0 })), /erstes Ereignis/);
  assert.match(railCaptionsHtml(model({ preRoll: 4, firstEventT: 4 })), /erstes Ereignis/);
});

test('the row is hidden from screen readers, which already have the slider', () => {
  assert.match(railCaptionsHtml(model({ preRoll: 4 })), /aria-hidden="true"/);
});
