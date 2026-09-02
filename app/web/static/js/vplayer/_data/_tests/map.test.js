// ─── vplayer/_data/_tests/map.test.js ──────────────────────────────────────
// The live frame mapping. The distinction worth pinning is KEPT versus
// DISCARDED: a discarded detection is the pipeline working — a class
// outside the filter, a subject inside a mask, a box outside every zone
// — and it must reach the panel with the reason attached, because "why
// did it not alert on the thing I can see" is the question operators
// actually ask.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DISCARD_REASON_DE,
  mapDetection,
  mapFrame,
  objectRowsFor,
  objectsNote,
} from '../_map.js';

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

// ── the whole-clip aggregate ───────────────────────────────────────────
//
// `whole_clip` is one row per subject across the WHOLE recording. The
// two older sources answer narrower questions — the sidecar re-walks the
// video at the raw floor, `detections` is the trigger frame alone — so
// the aggregate wins where it exists, and the list is never built from
// more than one of them at a time.

const TWO_BIRDS = {
  whole_clip: {
    detections: [
      { label: 'bird', score: 0.88, species: 'Grünfink', model: 'bird_classifier', first_s: 1.5, last_s: 4.25 }, // prettier-ignore
      { label: 'bird', score: 0.71, species: 'Blaumeise', model: 'bird_classifier', first_s: 6, last_s: 9 }, // prettier-ignore
    ],
    species: [
      { species: 'Grünfink', best_score: 0.88 },
      { species: 'Blaumeise', best_score: 0.71 },
    ],
    frames: 40,
    truncated: false,
  },
};

test('the whole-clip block wins over the sidecar and the trigger frame', () => {
  // The operator's complaint: a clip holding two different birds files
  // one species. Only this source has both of them.
  const tracks = { tracks: [{ _num: 1, label: 'bird', samples: [{ t: 1 }] }] };
  const item = { ...TWO_BIRDS, detections: [{ label: 'bird', score: 0.5 }] };
  const rows = objectRowsFor(item, tracks);
  assert.equal(rows.length, 2);
  assert.deepEqual(
    rows.map((r) => r.species),
    ['Grünfink', 'Blaumeise'],
  );
});

test('a whole-clip row reports the span it was actually present for', () => {
  const rows = objectRowsFor(TWO_BIRDS, null);
  assert.equal(rows[0].t0, 1.5);
  assert.equal(rows[0].t1, 4.25);
});

test('every row says which source it came from, and one list has only one', () => {
  // Mixing them would put spawn-gated rows (what the live pipeline
  // acted on) next to raw-floor rows (what a re-walk saw at lower
  // confidence) with nothing to tell them apart.
  const tracks = { tracks: [{ _num: 1, label: 'cat', samples: [{ t: 1 }] }] };
  const bases = (item, t) => new Set(objectRowsFor(item, t).map((r) => r.basis));
  assert.deepEqual(bases(TWO_BIRDS, tracks), new Set(['clip']));
  assert.deepEqual(bases({ detections: [{ label: 'cat' }] }, tracks), new Set(['sidecar']));
  assert.deepEqual(bases({ detections: [{ label: 'cat' }] }, null), new Set(['frame']));
});

test('a whole-clip row carries no number and no lane colour', () => {
  // #N and the lane colour are the SIDECAR's numbering, which the
  // timeline and the boxes also read. This block comes from a
  // different tracker run, so a number here would point at a lane
  // showing something else.
  const rows = objectRowsFor(TWO_BIRDS, null);
  assert.equal(rows[0].num, null);
  assert.equal(rows[0].colour, null);
});

test('an empty whole-clip block falls back rather than showing nothing', () => {
  // A stub written before the first analysis tick has the key with an
  // empty list. That is not an answer, so the older sources still get
  // their turn.
  const empty = { whole_clip: { detections: [], species: [], frames: 0, truncated: false } };
  const tracks = { tracks: [{ _num: 1, label: 'cat', samples: [{ t: 2 }] }] };
  assert.equal(objectRowsFor(empty, tracks)[0].basis, 'sidecar');
  assert.equal(objectRowsFor({ ...empty, detections: [{ label: 'cat' }] }, null)[0].basis, 'frame');
});

test('a malformed whole_clip is stepped over, not thrown on', () => {
  const tracks = { tracks: [{ _num: 1, label: 'cat', samples: [{ t: 2 }] }] };
  assert.equal(objectRowsFor({ whole_clip: null }, tracks)[0].basis, 'sidecar');
  assert.equal(objectRowsFor({ whole_clip: { detections: 'no' } }, tracks)[0].basis, 'sidecar');
  assert.deepEqual(objectRowsFor({ whole_clip: {} }, null), []);
});

// ── the list's footnote ────────────────────────────────────────────────

test('an event with no whole_clip has no footnote at all', () => {
  // Byte-identical rendering for every clip recorded before the
  // aggregate existed depends on this being null.
  const tracks = { tracks: [{ _num: 1, label: 'cat', samples: [{ t: 1 }] }] };
  assert.equal(objectsNote(objectRowsFor({}, tracks), {}), null);
  assert.equal(objectsNote(objectRowsFor({ detections: [{ label: 'cat' }] }, null), {}), null);
  assert.equal(objectsNote([], TWO_BIRDS), null);
});

test('the footnote says the rows cover the whole clip', () => {
  assert.equal(objectsNote(objectRowsFor(TWO_BIRDS, null), TWO_BIRDS), 'Ganzer Clip');
});

test('a truncated list says so rather than reading as complete', () => {
  const item = { whole_clip: { ...TWO_BIRDS.whole_clip, truncated: true } };
  assert.equal(objectsNote(objectRowsFor(item, null), item), 'Ganzer Clip · Liste gekürzt');
});

test('a species no visible row names is still reported', () => {
  // Reachable when the row caps refused a subject whose species had
  // already entered the species tally — precisely the case where a
  // silent list would hide the answer the operator came for.
  const item = {
    whole_clip: {
      detections: [{ label: 'bird', score: 0.9, species: 'Grünfink', first_s: 0, last_s: 2 }],
      species: [{ species: 'Grünfink' }, { species: 'Kohlmeise' }],
      frames: 9,
      truncated: true,
    },
  };
  assert.equal(
    objectsNote(objectRowsFor(item, null), item),
    'Ganzer Clip · Liste gekürzt · auch: Kohlmeise',
  );
});
