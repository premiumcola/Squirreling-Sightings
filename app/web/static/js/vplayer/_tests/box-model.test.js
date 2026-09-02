// ─── vplayer/_tests/box-model.test.js ──────────────────────────────────────
// PARITY FIXTURES, lifted from BOTH existing painters, so every point
// where they disagreed is explicit and reviewable here rather than
// discovered later in a browser.
//
// The three unifications this file pins:
//   · one pill convention — the class name is on the box, in both
//     modes, with the German "87 %" spacing;
//   · one plate design — a dark slab with coloured text;
//   · one masked grey — #64748b, the value status-legend.js paints its
//     own "⊘ Maskiert" swatch with. Recorded strokes #94a3b8 today, so
//     its box has never matched the legend row explaining it.
//
// What is NOT decided here and must never be: dash, alpha and the
// status marker. Those come from MV_STATUS_STYLE, and these tests
// assert the values match that table rather than restating them.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { MV_STATUS_STYLE } from '../../mediaview/status-legend.js';
import { liveTrackColor } from '../../core/track-color.js';
import { VP_MASKED_STROKE, VP_PLATE_BG, plateText, resolveBox } from '../_box-model.js';

// A recorded tracks.json sample and a live detection describing the
// SAME thing: track 2, a person, 87 %, confirmed.
const RECORDED_SAMPLE = { status: 'confirmed', score: 0.87, label: 'person', track_num: 2 };
const LIVE_DETECTION = { verdict: 'pass', score: 0.87, label: 'person', track_num: 2 };

test('both surfaces yield one identical plate for equivalent input', () => {
  // The unification, stated as one assertion.
  assert.equal(resolveBox(RECORDED_SAMPLE).plateText, resolveBox(LIVE_DETECTION).plateText);
});

test('the plate names the class, the track and the score', () => {
  const out = resolveBox(LIVE_DETECTION).plateText;
  assert.equal(out, '#2 · Person · 87 %');
  assert.ok(out.includes('Person'), 'the picture must name the class');
  assert.ok(out.includes(' %'), 'German spacing before the percent sign');
});

test('recorded status and live verdict fold through one categoriser', () => {
  assert.equal(resolveBox(RECORDED_SAMPLE).cat, 'confirmed');
  assert.equal(resolveBox(LIVE_DETECTION).cat, 'confirmed');
});

test('the four status line styles come from MV_STATUS_STYLE unchanged', () => {
  const cases = [
    ['confirmed', { status: 'confirmed' }],
    ['weak', { status: 'weak' }],
    ['ghost', { status: 'ghost' }],
    ['masked', { status: 'masked' }],
  ];
  for (const [cat, det] of cases) {
    const style = resolveBox({ ...det, score: 0.5, track_num: 1 });
    assert.equal(style.cat, cat);
    assert.deepEqual(style.dash, MV_STATUS_STYLE[cat].dash, `${cat} dash drifted`);
    assert.equal(style.alpha, MV_STATUS_STYLE[cat].alpha, `${cat} alpha drifted`);
    assert.equal(style.marker, MV_STATUS_STYLE[cat].marker, `${cat} marker drifted`);
  }
});

test('the status marker is prefixed onto the plate for a weak box', () => {
  const out = resolveBox({ status: 'weak', score: 0.24, label: 'person', track_num: 1 });
  assert.equal(out.plateText, `${MV_STATUS_STYLE.weak.marker} #1 · Person · 24 %`);
});

test('a masked box strokes the legend grey and says so in words', () => {
  const out = resolveBox({ status: 'masked', score: 0.9, label: 'cat', track_num: 3 });
  assert.equal(out.stroke, VP_MASKED_STROKE);
  assert.equal(VP_MASKED_STROKE, '#64748b', 'must equal the legend swatch colour');
  assert.ok(out.plateText.endsWith('· gefiltert'), 'grey alone has been read as low confidence');
});

test('an unmasked box strokes its track colour, not a status colour', () => {
  // Colour encodes the TRACK; status is the line style. Two tracks with
  // the same status must be told apart by hue.
  const one = resolveBox({ status: 'confirmed', score: 0.9, track_num: 1 });
  const two = resolveBox({ status: 'confirmed', score: 0.9, track_num: 2 });
  assert.equal(one.stroke, liveTrackColor(1));
  assert.equal(two.stroke, liveTrackColor(2));
  assert.notEqual(one.stroke, two.stroke);
  assert.deepEqual(one.dash, two.dash, 'same status, same line style');
});

test('an explicit colour overrides the track hue but never the mask', () => {
  assert.equal(resolveBox(LIVE_DETECTION, { colour: '#ff0000' }).stroke, '#ff0000');
  const masked = resolveBox({ status: 'masked', score: 0.5 }, { colour: '#ff0000' });
  assert.equal(masked.stroke, VP_MASKED_STROKE);
});

test('one plate design: a dark slab with the stroke colour as its text', () => {
  const out = resolveBox(LIVE_DETECTION);
  assert.equal(out.plateBg, VP_PLATE_BG);
  assert.equal(out.plateFg, out.stroke);
});

test('holdMul dims the whole box during the live hold-time fade', () => {
  const full = resolveBox(LIVE_DETECTION);
  const fading = resolveBox(LIVE_DETECTION, { holdMul: 0.5 });
  assert.equal(fading.alpha, full.alpha * 0.5);
});

test('selection thickens the stroke and changes nothing else', () => {
  const plain = resolveBox(LIVE_DETECTION);
  const picked = resolveBox(LIVE_DETECTION, { selected: true });
  assert.equal(plain.width, 3);
  assert.equal(picked.width, 5);
  assert.equal(picked.stroke, plain.stroke);
  assert.equal(picked.plateText, plain.plateText);
});

test('missing parts are dropped from the plate, never printed as gaps', () => {
  // A detection can arrive before the tracker numbers it, and a label
  // can be missing from the German table.
  assert.equal(plateText({ score: 0.42 }, 'confirmed'), '42 %');
  assert.equal(plateText({ label: 'person', score: 0.42 }, 'confirmed'), 'Person · 42 %');
  assert.equal(plateText({ track_num: 4, score: 0.42 }, 'confirmed'), '#4 · 42 %');
  assert.equal(plateText({}, 'confirmed'), '');
  for (const det of [{}, { score: 0.4 }, { track_num: 0 }]) {
    const out = plateText(det, 'confirmed');
    assert.ok(!out.includes('undefined'), `leaked undefined: ${out}`);
    assert.ok(!out.includes('NaN'), `leaked NaN: ${out}`);
  }
});

test('an untracked detection (track_num 0) prints no number', () => {
  assert.equal(plateText({ track_num: 0, label: 'bird', score: 0.6 }, 'confirmed'), 'Vogel · 60 %');
});

test('resolveBox never throws on an empty or absent detection', () => {
  for (const det of [undefined, null, {}, { verdict: 'nonsense' }]) {
    const out = resolveBox(det);
    assert.equal(typeof out.stroke, 'string');
    assert.ok(Array.isArray(out.dash));
    assert.equal(typeof out.plateText, 'string');
  }
});
