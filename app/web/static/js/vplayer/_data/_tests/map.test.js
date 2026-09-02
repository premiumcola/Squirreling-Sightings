// ─── vplayer/_data/_tests/map.test.js ──────────────────────────────────────
// The live frame mapping. The distinction worth pinning is KEPT versus
// DISCARDED: a discarded detection is the pipeline working — a class
// outside the filter, a subject inside a mask, a box outside every zone
// — and it must reach the panel with the reason attached, because "why
// did it not alert on the thing I can see" is the question operators
// actually ask.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { DISCARD_REASON_DE, mapDetection, mapFrame, objectRowsFor } from '../_map.js';

const PASS = { label: 'person', score: 0.9, bbox: [10, 20, 40, 30], verdict: 'pass', track_num: 1 };
const FILTERED = {
  label: 'car',
  score: 0.8,
  bbox: [0, 0, 10, 10],
  verdict: 'filtered',
  reason: "Klasse 'car' nicht im Objektfilter",
  track_num: null,
};

test('a passing detection is kept and carries a drawable box', () => {
  const d = mapDetection(PASS);
  assert.equal(d.discarded, false);
  assert.deepEqual(d.box, { x: 10, y: 20, w: 40, h: 30 });
  assert.equal(d.trackNum, 1);
  assert.equal(typeof d.style.stroke, 'string');
});

test('the backend German reason is preserved verbatim', () => {
  assert.equal(mapDetection(FILTERED).reason, "Klasse 'car' nicht im Objektfilter");
});

test('a verdict the backend did not explain still gets a German reason', () => {
  const d = mapDetection({ label: 'cat', score: 0.7, bbox: [0, 0, 5, 5], verdict: 'masked' });
  assert.equal(d.reason, DISCARD_REASON_DE.masked);
  assert.ok(d.reason.length > 0);
});

test('the four discard verdicts are discarded; pass and tentative are not', () => {
  for (const verdict of ['filtered', 'masked', 'outside_zone', 'no_track']) {
    assert.equal(mapDetection({ verdict }).discarded, true, verdict);
  }
  // tentative HOLDS its track — it is not a drop, and the existing
  // panel does not treat it as one either.
  assert.equal(mapDetection({ verdict: 'tentative' }).discarded, false);
  assert.equal(mapDetection({ verdict: 'pass' }).discarded, false);
});

test('a frame splits into kept and discarded without losing any row', () => {
  const frame = mapFrame({ detections: [PASS, FILTERED], frame_size: { w: 960, h: 540 } });
  assert.equal(frame.detections.length, 2);
  assert.equal(frame.kept.length, 1);
  assert.equal(frame.discarded.length, 1);
  assert.equal(frame.kept.length + frame.discarded.length, frame.detections.length);
  assert.deepEqual(frame.frameSize, { w: 960, h: 540 });
});

test('the untouched response is kept so no unmapped field is lost', () => {
  // The backend grows fields alongside this player; a key this mapping
  // does not know about must still be reachable.
  const raw = { detections: [], modes: { roi_mode_active: '2x2' }, some_future_key: 42 };
  const frame = mapFrame(raw);
  assert.equal(frame.raw.some_future_key, 42);
  assert.equal(frame.raw.modes.roi_mode_active, '2x2');
});

test('an undrawable bbox yields a null box rather than a throw', () => {
  assert.equal(mapDetection({ label: 'x', bbox: null }).box, null);
  assert.equal(mapDetection({ label: 'x', bbox: [1, 2, 0, 0] }).box, null);
});

test('an empty, malformed or error frame maps without throwing', () => {
  for (const bad of [null, undefined, {}, { detections: 'nope' }]) {
    const frame = mapFrame(bad);
    assert.deepEqual(frame.detections, []);
    assert.deepEqual(frame.kept, []);
    assert.deepEqual(frame.discarded, []);
    assert.deepEqual(frame.trace, []);
  }
});

test('ok is false only when the backend actually said so', () => {
  assert.equal(mapFrame({}).ok, true);
  assert.equal(mapFrame({ ok: true }).ok, true);
  assert.equal(mapFrame({ ok: false }).ok, false);
});

test('the decision trace passes through as an array', () => {
  assert.deepEqual(mapFrame({ decision_trace: ['a', 'b'] }).trace, ['a', 'b']);
  assert.deepEqual(mapFrame({ decision_trace: 'nope' }).trace, []);
});

// ── recorded object rows ───────────────────────────────────────────────

test('the sidecar is preferred, because only it carries timing', () => {
  const tracks = {
    tracks: [
      {
        _num: 1,
        label: 'person',
        color: '#22c55e',
        best_score: 0.91,
        model: 'detector',
        samples: [{ t: 3 }, { t: 11 }],
      },
    ],
  };
  const rows = objectRowsFor({ detections: [{ label: 'cat', score: 0.4 }] }, tracks);
  assert.equal(rows.length, 1);
  assert.deepEqual(
    { n: rows[0].num, l: rows[0].label, s: rows[0].score, a: rows[0].t0, b: rows[0].t1 },
    { n: 1, l: 'person', s: 0.91, a: 3, b: 11 },
  );
});

test('the track keeps its stamped colour, which the timeline shares', () => {
  const tracks = { tracks: [{ _num: 2, label: 'cat', color: '#ff00ff', samples: [{ t: 1 }] }] };
  assert.equal(objectRowsFor({}, tracks)[0].colour, '#ff00ff');
});

test('best_score is preferred over the last score', () => {
  // "How sure was it at its best" is the useful question; the last
  // sample of a departing subject is always its worst.
  const tracks = { tracks: [{ _num: 1, best_score: 0.9, score: 0.2, samples: [{ t: 1 }] }] };
  assert.equal(objectRowsFor({}, tracks)[0].score, 0.9);
});

test('without a sidecar the event detections are used, with no span', () => {
  // A raw detection is one frame. A fabricated span would read as a
  // duration the detector never observed.
  const rows = objectRowsFor({ detections: [{ label: 'bird', score: 0.7 }] }, null);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].label, 'bird');
  assert.equal(rows[0].t0, null);
  assert.equal(rows[0].t1, null);
  assert.equal(rows[0].num, null);
});

test('an empty sidecar falls back rather than showing nothing', () => {
  const rows = objectRowsFor({ detections: [{ label: 'cat', score: 0.5 }] }, { tracks: [] });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].label, 'cat');
});

test('no tracks and no detections is an empty list, not a throw', () => {
  assert.deepEqual(objectRowsFor({}, null), []);
  assert.deepEqual(objectRowsFor(null, null), []);
  assert.deepEqual(objectRowsFor(null, { tracks: null }), []);
});

test('every row carries a stable unique key for the DOM', () => {
  const tracks = { tracks: [{ _num: 1, samples: [{ t: 1 }] }, { _num: 2, samples: [{ t: 2 }] }] };
  const keys = objectRowsFor({}, tracks).map((r) => r.key);
  assert.equal(new Set(keys).size, keys.length);
});
