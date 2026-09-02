// ─── core/_tests/video-fit.test.js ─────────────────────────────────────────
// containRect is the one contain-fit solver every overlay in the app
// sits on: bboxes, trails, zone/mask polygons and the player stage all
// map source pixels through it. A silent change here moves every
// overlay off its picture at once, so the numbers are pinned rather
// than merely exercised.
//
// fittedRect and fitScale are asserted through a fake element because
// their only job now is to read dimensions off the DOM and delegate —
// these cases exist to prove the delegation kept their old contract,
// including the deliberate "return the full box, not a zero rect"
// degradation before the first frame decodes.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { containRect, fittedRect, fitScale } from '../video-fit.js';

/** Minimal stand-in for a <video>/<img> — only what video-fit reads. */
function fakeMedia({ videoWidth = 0, naturalWidth = 0, videoHeight = 0, naturalHeight = 0, box }) {
  return {
    videoWidth,
    videoHeight,
    naturalWidth,
    naturalHeight,
    getBoundingClientRect: () => box,
  };
}

test('a 2560x1440 source in a 390x220 box letterboxes to the pinned rect', () => {
  const r = containRect(2560, 1440, 390, 220);
  // 390/2560 = 0.15234375 is the binding ratio (220/1440 is larger),
  // so the picture fills the width and gutters split vertically.
  assert.equal(r.scale, 0.15234375);
  assert.equal(r.w, 390);
  assert.equal(r.h, 219.375);
  assert.equal(r.x, 0);
  assert.equal(r.y, 0.3125);
});

test('a source taller than its box gutters horizontally instead', () => {
  const r = containRect(1080, 1920, 400, 400);
  assert.equal(r.scale, 400 / 1920);
  assert.equal(r.h, 400);
  assert.equal(r.w, 225);
  assert.equal(r.x, 87.5);
  assert.equal(r.y, 0);
});

test('an exact aspect match leaves no gutter and scale 1', () => {
  const r = containRect(1920, 1080, 1920, 1080);
  assert.deepEqual(r, { x: 0, y: 0, w: 1920, h: 1080, scale: 1 });
});

test('unknown source dimensions yield the full box at scale 1, never NaN', () => {
  // The pre-first-frame case. Overlays mount against this and redraw
  // once loadedmetadata lands, so it must be the box, not a zero rect.
  const r = containRect(0, 0, 390, 220);
  assert.deepEqual(r, { x: 0, y: 0, w: 390, h: 220, scale: 1 });
});

test('an unmeasured box collapses to zero without dividing by it', () => {
  const r = containRect(1920, 1080, 0, 0);
  assert.deepEqual(r, { x: 0, y: 0, w: 0, h: 0, scale: 1 });
  assert.ok(Number.isFinite(r.scale));
});

test('negative dimensions are treated as unmeasured, not mirrored', () => {
  const r = containRect(1920, 1080, -50, 220);
  assert.deepEqual(r, { x: 0, y: 0, w: 0, h: 220, scale: 1 });
});

test('fittedRect delegates and returns only the four rect fields', () => {
  const el = fakeMedia({
    videoWidth: 2560,
    videoHeight: 1440,
    box: { width: 390, height: 220 },
  });
  assert.deepEqual(fittedRect(el), { x: 0, y: 0.3125, w: 390, h: 219.375 });
});

test('fittedRect falls back to the content box before metadata loads', () => {
  const el = fakeMedia({ box: { width: 390, height: 220 } });
  assert.deepEqual(fittedRect(el), { x: 0, y: 0, w: 390, h: 220 });
});

test('fittedRect on no element is a zero rect', () => {
  assert.deepEqual(fittedRect(null), { x: 0, y: 0, w: 0, h: 0 });
});

test('fitScale reads an <img> through naturalWidth/naturalHeight', () => {
  const el = fakeMedia({
    naturalWidth: 2560,
    naturalHeight: 1440,
    box: { width: 390, height: 220 },
  });
  assert.equal(fitScale(el), 0.15234375);
});

test('fitScale is 1 for no element and for an unmeasured one', () => {
  assert.equal(fitScale(null), 1);
  assert.equal(fitScale(fakeMedia({ box: { width: 0, height: 0 } })), 1);
});
