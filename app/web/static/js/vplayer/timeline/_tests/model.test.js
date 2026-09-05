// ─── vplayer/timeline/_tests/model.test.js ─────────────────────────────────
// The timeline is the part of this player most likely to be got subtly
// wrong, which is why it is arithmetic with no DOM. Every case here is
// an edge the old implementation either handled invisibly or not at all.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildTimelineModel, classifySample, pctOf, segmentTrack } from '../_model.js';

/** A track of evenly spaced detected samples. */
function track(num, label, t0, t1, step = 1, extra = {}) {
  const samples = [];
  for (let t = t0; t <= t1 + 1e-9; t += step) {
    samples.push({ t: Number(t.toFixed(3)), bbox: [10, 10, 20, 20], score: 0.9, source: 'detect' });
  }
  return { _num: num, label, color: '#22c55e', samples, ...extra };
}

const OPTS = { duration: 20, preRoll: 3, postRoll: 4, threshold: 0.5 };

// Mask polygons are stored as {points: [{x, y}, …]} with an optional
// source_w/source_h — the shape settings.json actually holds.
const FULL_FRAME_MASK = [
  { x: 0, y: 0 },
  { x: 100, y: 0 },
  { x: 100, y: 100 },
  { x: 0, y: 100 },
];

test('a normal clip lays out lanes, roll bands and the first-event mark', () => {
  const m = buildTimelineModel([track(1, 'person', 5, 9)], OPTS);
  assert.equal(m.duration, 20);
  assert.equal(m.preRoll, 3);
  assert.equal(m.postRoll, 4);
  assert.equal(m.postRollT0, 16);
  assert.equal(m.firstEventT, 5);
  assert.equal(m.lanes.length, 1);
  assert.deepEqual(
    { n: m.lanes[0].trackNum, dot: m.lanes[0].dotT, t0: m.lanes[0].barT0, t1: m.lanes[0].barT1 },
    { n: 1, dot: 5, t0: 5, t1: 9 },
  );
});

test('duration 0 divides by nothing and suppresses the marker', () => {
  const m = buildTimelineModel([track(1, 'person', 0, 2)], { duration: 0, threshold: 0.5 });
  assert.equal(m.duration, 0);
  assert.equal(m.firstEventT, null, 'a marker at 0 would read as "began immediately"');
  assert.equal(pctOf(1, 0), 0);
  assert.ok(Number.isFinite(pctOf(1, 0)));
  for (const v of [m.preRoll, m.postRoll, m.postRollT0]) assert.ok(Number.isFinite(v));
});

test('a single-sample track keeps its lane as a dot with a zero-length bar', () => {
  const one = { _num: 4, label: 'bird', samples: [{ t: 7, bbox: [0, 0, 5, 5], score: 0.9 }] };
  const m = buildTimelineModel([one], OPTS);
  assert.equal(m.lanes.length, 1, 'a one-frame subject must not vanish');
  assert.equal(m.lanes[0].dotT, 7);
  assert.equal(m.lanes[0].barT0, 7);
  assert.equal(m.lanes[0].barT1, 7);
});

test('a track with no samples produces no lane at all', () => {
  const m = buildTimelineModel([{ _num: 9, label: 'cat', samples: [] }], OPTS);
  assert.deepEqual(m.lanes, []);
  assert.equal(m.firstEventT, null);
});

test('a track starting inside the pre-roll keeps its real start time', () => {
  // The pre-roll is footage recorded BEFORE the trigger; a detection
  // can legitimately fall inside it and must not be pushed forward.
  const m = buildTimelineModel([track(1, 'person', 1, 6)], OPTS);
  assert.equal(m.lanes[0].barT0, 1);
  assert.equal(m.firstEventT, 1);
  assert.ok(pctOf(m.firstEventT, m.duration) < pctOf(m.preRoll, m.duration));
});

test('two tracks starting on the same frame hold a stable order', () => {
  const a = track(2, 'cat', 5, 9);
  const b = track(1, 'person', 5, 9);
  const first = buildTimelineModel([a, b], OPTS).lanes.map((l) => l.trackNum);
  const second = buildTimelineModel([b, a], OPTS).lanes.map((l) => l.trackNum);
  assert.deepEqual(first, [1, 2], 'ties break by track number');
  assert.deepEqual(first, second, 'input order must not reshuffle the rows');
});

test('lanes are ordered by start time', () => {
  const m = buildTimelineModel([track(3, 'c', 12, 14), track(1, 'a', 2, 4), track(2, 'b', 6, 8)], OPTS);
  assert.deepEqual(
    m.lanes.map((l) => l.barT0),
    [2, 6, 12],
  );
});

test('a post-roll longer than the clip is clamped inside the rail', () => {
  const m = buildTimelineModel([track(1, 'person', 1, 2)], {
    duration: 5,
    preRoll: 2,
    postRoll: 30,
  });
  assert.ok(m.postRollT0 >= m.preRoll, 'the bands must not cross');
  assert.ok(m.postRollT0 <= m.duration);
  assert.equal(pctOf(m.postRollT0 + m.postRoll, m.duration), 1, 'never past 1.0');
  assert.equal(m.preRoll + m.postRoll <= m.duration, true);
});

test('a pre-roll that swallows the whole clip is not drawn at all', () => {
  // It used to be clamped to the duration, which painted the ENTIRE rail
  // as pre-roll and left no room for the event the clip exists to show.
  // „Du sagst hier Vor- und Nachlauf drei Sekunden, aber das Video dauert
  // nur drei Sekunden … das kann schon mal gar nicht stimmen." Right: a
  // band covering everything is not a shortened measurement, it is a
  // false one, and saying so is the only honest option left.
  const m = buildTimelineModel([], { duration: 5, preRoll: 30, postRoll: 0 });
  assert.equal(m.preRoll, 0);
  assert.equal(m.postRoll, 0);
  assert.equal(m.rollsUnreliable, true);
});

test('the two rolls may not add up to more than the clip', () => {
  // The photographed case, to the second: a 3.9 s clip carrying a
  // configured 3 s pre-roll and 3 s post-roll, with a person detected
  // over it. Six seconds of roll do not fit in 3.9 seconds of video.
  const m = buildTimelineModel([], { duration: 3.9, preRoll: 3, postRoll: 3 });
  assert.equal(m.rollsUnreliable, true);
  assert.equal(m.preRoll, 0);
  assert.equal(m.postRoll, 0);
});

test('a detection inside the pre-roll does NOT shrink the pre-roll', () => {
  // The complement of the rule above, and the reason the fix stops at
  // the sum: the pre-roll is footage from before the TRIGGER, and a
  // subject already standing in frame is legitimately detected inside
  // it. Inferring the roll from detection times would rewrite it.
  const m = buildTimelineModel([track(1, 'person', 1, 8)], {
    duration: 10,
    preRoll: 3,
    postRoll: 3,
  });
  assert.equal(m.preRoll, 3);
  assert.equal(m.postRoll, 3);
  assert.equal(m.rollsUnreliable, false);
});

test('with no lanes the configured rolls stand, as long as they fit', () => {
  const m = buildTimelineModel([], { duration: 20, preRoll: 3, postRoll: 3 });
  assert.equal(m.preRoll, 3);
  assert.equal(m.postRoll, 3);
  assert.equal(pctOf(m.preRoll, m.duration), 0.15);
});

test('a predicted tail is segmented as predicted, not as detected', () => {
  // The tracker carries a box forward when the detector loses it. That
  // segment is the only place a viewer learns the box is inferred.
  const samples = [
    { t: 1, bbox: [0, 0, 5, 5], score: 0.9, source: 'detect' },
    { t: 2, bbox: [0, 0, 5, 5], score: 0.9, source: 'detect' },
    { t: 3, bbox: [0, 0, 5, 5], score: 0.9, source: 'predict' },
    { t: 4, bbox: [0, 0, 5, 5], score: 0.9, source: 'predict' },
  ];
  const segs = segmentTrack(samples, { threshold: 0.5 });
  assert.deepEqual(segs, [
    { status: 'confirmed', t0: 1, t1: 3 },
    { status: 'predicted', t0: 3, t1: 4 },
  ]);
});

test('a sample under the spawn threshold segments as weak', () => {
  const samples = [
    { t: 1, bbox: [0, 0, 5, 5], score: 0.9, source: 'detect' },
    { t: 2, bbox: [0, 0, 5, 5], score: 0.2, source: 'detect' },
  ];
  const segs = segmentTrack(samples, { threshold: 0.5 });
  assert.deepEqual(segs.map((s) => s.status), ['confirmed', 'weak']);
});

test('an all-masked track segments as one masked run and reads as masked', () => {
  // A 100x100 mask over the whole frame; the probe point is the bottom
  // centre of the box, which lands inside it.
  const masks = [{ points: FULL_FRAME_MASK }];
  const samples = [
    { t: 1, bbox: [10, 10, 20, 20], score: 0.9, source: 'detect' },
    { t: 2, bbox: [12, 12, 20, 20], score: 0.9, source: 'detect' },
  ];
  const opts = { duration: 10, threshold: 0.5, masks, srcW: 100, srcH: 100 };
  const segs = segmentTrack(samples, opts);
  assert.deepEqual(segs, [{ status: 'masked', t0: 1, t1: 2 }]);
  const m = buildTimelineModel([{ _num: 1, label: 'cat', samples }], opts);
  assert.equal(m.lanes[0].status, 'masked');
});

test('masked beats a confirmed score — the mask is about the place', () => {
  const masks = [{ points: FULL_FRAME_MASK }];
  const s = { t: 1, bbox: [10, 10, 20, 20], score: 1, source: 'detect' };
  assert.equal(classifySample(s, { threshold: 0.5, masks, srcW: 100, srcH: 100 }), 'masked');
});

test('a track outside every mask is not masked', () => {
  const masks = [
    {
      points: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 10 },
        { x: 0, y: 10 },
      ],
    },
  ];
  const s = { t: 1, bbox: [50, 50, 20, 20], score: 0.9, source: 'detect' };
  assert.equal(classifySample(s, { threshold: 0.5, masks, srcW: 100, srcH: 100 }), 'confirmed');
});

test('a track status reflects the run it spent the most time in', () => {
  const samples = [
    { t: 0, bbox: [0, 0, 5, 5], score: 0.9, source: 'detect' },
    { t: 1, bbox: [0, 0, 5, 5], score: 0.2, source: 'detect' },
    { t: 9, bbox: [0, 0, 5, 5], score: 0.2, source: 'detect' },
  ];
  const m = buildTimelineModel([{ _num: 1, label: 'cat', samples }], OPTS);
  assert.equal(m.lanes[0].status, 'weak', '8 s weak beats 1 s confirmed');
});

// ── the rolling live window ────────────────────────────────────────────

const LIVE = { windowMs: 60000, now: 1000, threshold: 0.5 };

test('the rolling window is right-anchored and 60 s wide', () => {
  const m = buildTimelineModel([track(1, 'person', 970, 1000, 10)], LIVE);
  assert.equal(m.rolling, true);
  assert.equal(m.duration, 60);
  // now-30 .. now maps to 30 .. 60 of a 60 s window.
  assert.equal(m.lanes[0].barT0, 30);
  assert.equal(m.lanes[0].barT1, 60);
});

test('the rolling window evicts a track that fell out of it', () => {
  const stale = track(1, 'person', 800, 900, 10);
  const fresh = track(2, 'cat', 980, 1000, 10);
  const m = buildTimelineModel([stale, fresh], LIVE);
  assert.equal(m.lanes.length, 1);
  assert.equal(m.lanes[0].trackNum, 2);
});

test('a track straddling the window edge is clipped, never dropped', () => {
  // Still on screen, just been there a while. Dropping it would make a
  // stationary object disappear from the strip.
  const m = buildTimelineModel([track(1, 'person', 900, 1000, 10)], LIVE);
  assert.equal(m.lanes.length, 1);
  assert.equal(m.lanes[0].barT0, 0, 'clipped to the window start');
  assert.equal(m.lanes[0].barT1, 60);
  assert.ok(m.lanes[0].segments.every((s) => s.t0 >= 0 && s.t1 <= 60));
});

test('an empty live buffer renders an empty strip rather than crashing', () => {
  const m = buildTimelineModel([], LIVE);
  assert.deepEqual(m.lanes, []);
  assert.equal(m.firstEventT, null);
  assert.equal(m.duration, 60);
});

test('a malformed source is treated as no tracks at all', () => {
  for (const bad of [null, undefined, 'tracks', 42, {}]) {
    const m = buildTimelineModel(bad, OPTS);
    assert.deepEqual(m.lanes, []);
  }
});

test('pctOf clamps at both ends and never returns NaN', () => {
  assert.equal(pctOf(0, 20), 0);
  assert.equal(pctOf(10, 20), 0.5);
  assert.equal(pctOf(20, 20), 1);
  assert.equal(pctOf(999, 20), 1);
  assert.equal(pctOf(-5, 20), 0);
  assert.equal(pctOf(NaN, 20), 0);
  assert.equal(pctOf(5, 0), 0);
  assert.equal(pctOf(5, -1), 0);
});
