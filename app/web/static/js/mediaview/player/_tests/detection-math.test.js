// ─── player/_tests/detection-math.test.js ──────────────────────────────
// Fixtures shaped exactly like tracks.json's `.tracks` array (and
// _state.timelineTrackIndex, which getTimelineTracks() returns unchanged
// — see mediathek/bbox-overlay/timeline-panel.js / track-loss-tooltip.js)
// — real per-sample `{ t, f, bbox, score, source }` shape, not an
// invented one.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findAdjacentSeek, seeksFromTracks } from '../_detection-math.js';

const REALISTIC_TRACKS = [
  {
    label: 'person',
    _num: 1,
    best_score: 0.91,
    samples: [
      { t: 1.2, f: 12, bbox: { x1: 10, y1: 10, x2: 50, y2: 90 }, score: 0.91, source: 'detect' },
      { t: 1.5, f: 15, bbox: { x1: 12, y1: 10, x2: 52, y2: 90 }, score: 0.9, source: 'detect' },
    ],
  },
  {
    label: 'cat',
    _num: 2,
    best_score: 0.72,
    samples: [
      { t: 8.4, f: 84, bbox: { x1: 100, y1: 60, x2: 140, y2: 100 }, score: 0.72, source: 'detect' },
    ],
  },
  {
    label: 'person',
    _num: 3,
    best_score: 0.65,
    samples: [
      { t: 8.4, f: 84, bbox: { x1: 5, y1: 5, x2: 20, y2: 20 }, score: 0.65, source: 'detect' },
    ],
  },
];

test('seeksFromTracks extracts one t0 per track, sorted ascending', () => {
  assert.deepEqual(seeksFromTracks(REALISTIC_TRACKS), [1.2, 8.4]);
});

test('seeksFromTracks dedupes tracks that start at the same timestamp', () => {
  // tracks #2 and #3 both start at t=8.4 — one seek entry, not two.
  const times = seeksFromTracks(REALISTIC_TRACKS);
  assert.equal(times.filter((t) => t === 8.4).length, 1);
});

test('seeksFromTracks handles empty/malformed input without throwing', () => {
  assert.deepEqual(seeksFromTracks([]), []);
  assert.deepEqual(seeksFromTracks(null), []);
  assert.deepEqual(seeksFromTracks([{ samples: [] }, { label: 'x' }, {}]), []);
});

test('findAdjacentSeek finds the next detection strictly after currentTime', () => {
  const times = seeksFromTracks(REALISTIC_TRACKS);
  assert.equal(findAdjacentSeek(times, 0, 1), 1.2);
  assert.equal(findAdjacentSeek(times, 1.2, 1), 8.4);
});

test('findAdjacentSeek finds the previous detection strictly before currentTime', () => {
  const times = seeksFromTracks(REALISTIC_TRACKS);
  assert.equal(findAdjacentSeek(times, 8.4, -1), 1.2);
  assert.equal(findAdjacentSeek(times, 1.2, -1), null);
});

test('findAdjacentSeek returns null at the end of the list without throwing', () => {
  const times = seeksFromTracks(REALISTIC_TRACKS);
  assert.equal(findAdjacentSeek(times, 8.4, 1), null);
});

test('findAdjacentSeek on an empty list returns null without throwing', () => {
  assert.equal(findAdjacentSeek([], 5, 1), null);
  assert.equal(findAdjacentSeek(null, 5, 1), null);
});
