// ─── vplayer/timeline/_tests/states.test.js ────────────────────────────────
// The three behaviours a timeline rewrite drops silently, because
// nothing else in the code references them: the lost-track ×, the three
// empty states, and the live filtered fold.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { emptyStateFor } from '../_empty-states.js';
import { buildLossReport, shouldShowLostMarker } from '../_loss-tip.js';
import { laneFingerprint, splitFiltered } from '../_rolling.js';

// ── the lost-track × ───────────────────────────────────────────────────

test('a track that ran to the end of the clip was not lost', () => {
  // It ran out of clip. Marking that as a loss would × almost every
  // track in the archive.
  assert.equal(shouldShowLostMarker({ end_reason: 'timeout' }, 19.9, 20), false);
  assert.equal(shouldShowLostMarker({ end_reason: 'ended_at_clip' }, 5, 20), false);
});

test('a timeout ending well before the clip is a loss', () => {
  assert.equal(shouldShowLostMarker({ end_reason: 'timeout' }, 5, 20), true);
});

test('a legacy sidecar with no end_reason falls back to the gap rule', () => {
  assert.equal(shouldShowLostMarker({}, 5, 20), true);
  assert.equal(shouldShowLostMarker({ end_reason: null }, 5, 20), true);
  assert.equal(shouldShowLostMarker({}, 19.9, 20), false);
});

test('merged and stitched tracks never draw an x', () => {
  // They did not end, they became part of another track.
  for (const reason of ['merged', 'stitched', 'auto', 'ended_at_clip']) {
    assert.equal(shouldShowLostMarker({ end_reason: reason }, 1, 20), false, reason);
  }
});

test('the 0.4 s gap is the boundary, and it is exclusive', () => {
  assert.equal(shouldShowLostMarker({}, 19.6, 20), false, 'exactly 0.4 s is not early');
  assert.equal(shouldShowLostMarker({}, 19.59, 20), true);
});

test('no duration means no marker rather than a divide', () => {
  assert.equal(shouldShowLostMarker({}, 5, 0), false);
  assert.equal(shouldShowLostMarker(null, 5, 20), false);
});

test('the loss report names the track, its span and a reason', () => {
  const track = {
    _num: 3,
    end_reason: 'timeout',
    samples: [{ t: 2 }, { t: 6.5 }],
  };
  const r = buildLossReport(track, {});
  assert.equal(r.title, '× Track #3 verloren · 4.5 s');
  assert.equal(r.summary, 'Tracker verloren · keine Detektion');
});

test('an unknown end_reason is shown raw rather than swallowed', () => {
  const r = buildLossReport({ _num: 1, end_reason: 'gremlins', samples: [] }, {});
  assert.equal(r.summary, 'Grund: gremlins');
});

test('a missing end_reason recommends the re-index', () => {
  const r = buildLossReport({ _num: 1, samples: [] }, {});
  assert.equal(r.summary, 'Grund unbekannt — Re-Index empfohlen');
});

test('the score row compares against the per-class threshold first', () => {
  const track = { _num: 1, label: 'person', last_score: 0.73, samples: [] };
  const rs = { conf_thresh_general: 0.5, conf_thresh_per_class: { person: 0.8 } };
  const row = buildLossReport(track, rs).rows[0];
  assert.equal(row.value, '73 % < 80 %', 'the per-class threshold must win');
  assert.equal(row.tone, 'bad');
});

test('the score row falls back to the general threshold', () => {
  const track = { _num: 1, label: 'cat', last_score: 0.73, samples: [] };
  const row = buildLossReport(track, { conf_thresh_general: 0.5 }).rows[0];
  assert.equal(row.value, '73 % ≥ 50 %');
  assert.equal(row.tone, 'ok');
});

test('every row degrades to a placeholder rather than to undefined', () => {
  const rows = buildLossReport({ _num: 1, samples: [] }, {}).rows;
  for (const row of rows) {
    assert.equal(typeof row.value, 'string');
    assert.ok(!row.value.includes('undefined'), row.value);
    assert.ok(!row.value.includes('NaN'), row.value);
  }
  assert.equal(rows[0].value, '—');
  assert.equal(rows[1].value, '—');
});

test('the bbox row ticks against the class size floor', () => {
  const base = { _num: 1, label: 'person', samples: [], last_bbox_size_px: [128, 96] };
  const big = buildLossReport({ ...base, last_bbox_frac_h: 0.3, last_bbox_frac_area: 0.1 }, {});
  assert.equal(big.rows[1].value, '128 × 96 px ✓');
  const small = buildLossReport({ ...base, last_bbox_frac_h: 0.01, last_bbox_frac_area: 0.001 }, {});
  assert.equal(small.rows[1].value, '128 × 96 px ✗');
  assert.equal(small.rows[1].tone, 'bad');
});

test('a class with no floor always passes the bbox check', () => {
  const track = { _num: 1, label: 'cat', samples: [], last_bbox_size_px: [4, 4] };
  assert.equal(buildLossReport(track, {}).rows[1].value, '4 × 4 px ✓');
});

test('the class row ticks against the object filter', () => {
  const track = { _num: 1, label: 'person', samples: [] };
  assert.equal(buildLossReport(track, { object_filter: ['person'] }).rows[2].value, 'Person ✓');
  assert.equal(buildLossReport(track, { object_filter: ['cat'] }).rows[2].value, 'Person ✗');
  // No filter configured is not a failure — it is no opinion.
  assert.equal(buildLossReport(track, {}).rows[2].value, 'Person');
  assert.equal(buildLossReport(track, {}).rows[2].tone, null);
});

// ── the three empty states ─────────────────────────────────────────────

test('a timelapse gets the action, not an explanation', () => {
  assert.equal(emptyStateFor({ type: 'timelapse' }, null), 'timelapse');
  assert.equal(emptyStateFor({ type: 'timelapse' }, { built_at: 1 }), 'timelapse');
});

test('a sidecar that ran and found nothing says so', () => {
  assert.equal(emptyStateFor({ type: 'motion' }, { built_at: 123, tracks: [] }), 'done');
  assert.equal(emptyStateFor({ type: 'motion' }, { schema: 2, tracks: [] }), 'done');
});

test('no sidecar at all means nothing has ever looked', () => {
  assert.equal(emptyStateFor({ type: 'motion' }, null), 'unindexed');
  assert.equal(emptyStateFor({ type: 'motion' }, {}), 'unindexed');
  assert.equal(emptyStateFor(null, null), 'unindexed');
});

// ── the live filtered fold ─────────────────────────────────────────────

test('one pass makes a track real, not noise', () => {
  const allFiltered = { trackNum: 1, segments: [{ status: 'masked' }, { status: 'masked' }] };
  const passedOnce = { trackNum: 2, segments: [{ status: 'masked' }, { status: 'confirmed' }] };
  const { active, filtered } = splitFiltered([allFiltered, passedOnce]);
  assert.deepEqual(
    filtered.map((l) => l.trackNum),
    [1],
  );
  assert.deepEqual(
    active.map((l) => l.trackNum),
    [2],
  );
});

test('a lane with no segments at all is not filtered', () => {
  const { active, filtered } = splitFiltered([{ trackNum: 1, segments: [] }]);
  assert.equal(active.length, 1);
  assert.equal(filtered.length, 0);
});

test('the fingerprint is stable while nothing structural changes', () => {
  const lanes = [{ trackNum: 1, colour: '#fff', status: 'confirmed' }];
  assert.equal(laneFingerprint(lanes, false, 0), laneFingerprint(lanes, false, 0));
});

test('the fingerprint changes when membership, colour or the fold does', () => {
  const base = [{ trackNum: 1, colour: '#fff', status: 'confirmed' }];
  const fp = laneFingerprint(base, false, 0);
  assert.notEqual(fp, laneFingerprint(base, true, 0), 'fold state');
  assert.notEqual(fp, laneFingerprint(base, false, 2), 'filtered count');
  assert.notEqual(
    fp,
    laneFingerprint([...base, { trackNum: 2, colour: '#000', status: 'weak' }], false, 0),
    'membership',
  );
  assert.notEqual(
    fp,
    laneFingerprint([{ trackNum: 1, colour: '#f00', status: 'confirmed' }], false, 0),
    'colour',
  );
});
