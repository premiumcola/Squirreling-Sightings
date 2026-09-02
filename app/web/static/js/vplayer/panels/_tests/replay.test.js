// The replay block's pure halves: the requests each button makes, and
// the rows the answer renders as.
//
// Same contract as every other formatter in this package — a field the
// backend did not send becomes a placeholder, never "undefined", never
// "NaN", and never a throw that takes the fold down with it. That
// matters more here than usual: this payload is the newest surface in
// the app and an archived event can be replayed years after the shape
// it was written under.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PLACEHOLDER } from '../../_helpers.js';
import { REPLAY_SOURCE_DE, replaySummaryRows, replayVerdict } from '../_helpers.js';
import { preflightRequestFor, replayRequestFor } from '../_replay.js';

const ITEM = { event_id: '20260522T120000_cam_a', camera_id: 'cam_a' };

function response(over = {}) {
  return {
    ok: true,
    frames_analysed: 240,
    frames_available: 1000,
    truncated: true,
    settings: { source: 'stored', basis: 'provenance', hash: 'abc123def456', note: null },
    comparison: {
      before: {
        detection_count: 2,
        track_count: 2,
        alert: { level: 'alarm', notify: true, labels: ['person'] },
      },
      after: {
        detection_count: 2,
        track_count: 2,
        alert: { level: 'alarm', notify: true, labels: ['person'] },
      },
      diff: {
        detections: {
          appeared: [],
          disappeared: [],
          class_changed: [],
          score_changed: [],
          unchanged: [],
          counts: {
            before: 2,
            after: 2,
            appeared: 0,
            disappeared: 0,
            class_changed: 0,
            score_changed: 0,
            unchanged: 2,
          },
        },
        tracks: { counts: { appeared: 0, disappeared: 0, class_changed: 0, score_changed: 0 } },
      },
      tracks_comparable: true,
      alert_changed: false,
      changed: false,
    },
    ...over,
  };
}

function rowsBy(res) {
  return Object.fromEntries(replaySummaryRows(res).map((r) => [r.key, r.value]));
}

// ── request builders ───────────────────────────────────────────────────

test('the preflight is a GET carrying the camera hint', () => {
  const req = preflightRequestFor(ITEM);
  assert.equal(req.method, 'GET');
  assert.equal(req.url, '/api/event/20260522T120000_cam_a/replay?camera_id=cam_a');
});

test('both buttons post to the same URL, differing only in the settings set', () => {
  const stored = replayRequestFor(ITEM, 'stored');
  const current = replayRequestFor(ITEM, 'current');
  assert.equal(stored.url, current.url);
  assert.equal(stored.method, 'POST');
  assert.deepEqual(stored.body, { settings: 'stored' });
  assert.deepEqual(current.body, { settings: 'current' });
});

test('ids are URL-encoded so an odd event id cannot break out of the path', () => {
  const req = preflightRequestFor({ event_id: 'a/b?c', camera_id: 'x y' });
  assert.ok(req.url.includes('a%2Fb%3Fc'), req.url);
  assert.ok(req.url.includes('x%20y'), req.url);
});

test('an item with no event id yields no request rather than a bad one', () => {
  assert.equal(preflightRequestFor({}), null);
  assert.equal(preflightRequestFor(null), null);
  assert.equal(replayRequestFor({}, 'stored'), null);
});

test('an unknown settings mode is refused', () => {
  assert.equal(replayRequestFor(ITEM, 'yesterday'), null);
  assert.equal(replayRequestFor(ITEM, undefined), null);
});

test('a missing camera_id still produces a usable URL', () => {
  const req = preflightRequestFor({ event_id: 'e1' });
  assert.equal(req.url, '/api/event/e1/replay?camera_id=');
});

// ── the verdict line ───────────────────────────────────────────────────

test('an identical result says so in one line', () => {
  const v = replayVerdict(response());
  assert.equal(v.text, 'Ergebnis identisch');
  assert.equal(v.tone, 'ok');
});

test('a changed result names what moved', () => {
  const res = response();
  res.comparison.changed = true;
  res.comparison.diff.detections.counts.appeared = 1;
  res.comparison.diff.detections.counts.class_changed = 2;
  const v = replayVerdict(res);
  assert.equal(v.text, '1 neu · 2 andere Klasse');
  assert.equal(v.tone, 'warn');
});

test('an alert flip alone is enough to be worth naming', () => {
  const res = response();
  res.comparison.changed = true;
  res.comparison.alert_changed = true;
  assert.equal(replayVerdict(res).text, 'Alarm anders');
});

test('a verdict with no comparison degrades instead of throwing', () => {
  assert.equal(replayVerdict(undefined).text, PLACEHOLDER);
  assert.equal(replayVerdict({}).text, PLACEHOLDER);
});

// ── the rows ───────────────────────────────────────────────────────────

test('an unchanged run renders every row without an empty or undefined', () => {
  const rows = replaySummaryRows(response());
  assert.ok(rows.length >= 9, `expected the full row set, got ${rows.length}`);
  for (const r of rows) {
    assert.ok(r.value, `${r.key} rendered blank`);
    assert.ok(!String(r.value).includes('undefined'), `${r.key}: ${r.value}`);
    assert.ok(!String(r.value).includes('NaN'), `${r.key}: ${r.value}`);
  }
});

test('the object counts read as a before/after pair', () => {
  const res = response();
  res.comparison.after.detection_count = 3;
  assert.equal(rowsBy(res)['Objekte'], '2 → 3');
});

test('an unchanged count carries no tone, a changed one does', () => {
  const same = replaySummaryRows(response()).find((r) => r.key === 'Objekte');
  assert.equal(same.tone, null);
  const res = response();
  res.comparison.after.detection_count = 5;
  const moved = replaySummaryRows(res).find((r) => r.key === 'Objekte');
  assert.equal(moved.tone, 'warn');
});

test('new and vanished objects are named, not just counted', () => {
  const res = response();
  res.comparison.diff.detections.appeared = [{ label: 'squirrel', score: 0.6 }];
  res.comparison.diff.detections.disappeared = [{ label: 'cat', score: 0.5 }];
  const by = rowsBy(res);
  assert.equal(by['Neu'], 'squirrel');
  assert.equal(by['Weggefallen'], 'cat');
});

test('an empty bucket renders the placeholder, never a blank', () => {
  const by = rowsBy(response());
  assert.equal(by['Neu'], PLACEHOLDER);
  assert.equal(by['Weggefallen'], PLACEHOLDER);
  assert.equal(by['Klasse geändert'], PLACEHOLDER);
});

test('a class change reads as the old label arrowed to the new one', () => {
  const res = response();
  res.comparison.diff.detections.class_changed = [
    { before: { label: 'bird', score: 0.6 }, after: { label: 'squirrel', score: 0.8 } },
  ];
  assert.equal(rowsBy(res)['Klasse geändert'], 'bird → squirrel');
});

test('a confidence change names the label once and both percentages', () => {
  const res = response();
  res.comparison.diff.detections.score_changed = [
    {
      before: { label: 'person', score: 0.9 },
      after: { label: 'person', score: 0.45 },
      delta: -0.45,
    },
  ];
  assert.equal(rowsBy(res)['Konfidenz'], 'person 90 % → 45 %');
});

test('an un-indexed clip says the tracks cannot be compared', () => {
  const res = response();
  res.comparison.tracks_comparable = false;
  assert.match(rowsBy(res)['Spuren'], /kein Vergleich/);
});

test('an unchanged alert says so, with the level, rather than staying silent', () => {
  assert.equal(rowsBy(response())['Alarm'], 'alarm · würde melden (unverändert)');
});

test('a downgrade that still notifies is reported as a change', () => {
  // The regression a threshold tweak actually causes: still notified,
  // but no longer as an alarm. Comparing only notify would call this
  // unchanged.
  const res = response();
  res.comparison.alert_changed = true;
  res.comparison.after.alert = { level: 'info', notify: true, labels: ['motion'] };
  const row = replaySummaryRows(res).find((r) => r.key === 'Alarm');
  assert.equal(row.value, 'alarm → info · würde melden');
  assert.equal(row.tone, 'warn');
});

test('an alert that stops firing says no meldung', () => {
  const res = response();
  res.comparison.alert_changed = true;
  res.comparison.after.alert = { level: 'logged', notify: false, labels: [] };
  assert.equal(rowsBy(res)['Alarm'], 'alarm → logged · keine Meldung');
});

test('a truncated run says how much of the clip it got through', () => {
  const row = replaySummaryRows(response()).find((r) => r.key === 'Analysiert');
  assert.equal(row.value, '240 von 1000 Frames');
  assert.equal(row.tone, 'warn', 'a partial run must be visibly partial');
});

test('a complete run says so instead of showing an unhelpful ratio', () => {
  const res = response({ frames_analysed: 30, frames_available: 30, truncated: false });
  const row = replaySummaryRows(res).find((r) => r.key === 'Analysiert');
  assert.equal(row.value, '30 Frames (ganzer Clip)');
  assert.equal(row.tone, null);
});

test('the settings row names the set in German and shows its fingerprint', () => {
  assert.equal(rowsBy(response())['Settings'], `${REPLAY_SOURCE_DE.stored} · abc123def456`);
});

test('every settings source has German copy', () => {
  for (const source of ['stored', 'current', 'custom']) {
    const res = response({ settings: { source, hash: 'h' } });
    assert.ok(rowsBy(res)['Settings'].startsWith(REPLAY_SOURCE_DE[source]), source);
  }
});

test('a fallback basis surfaces its note as a row', () => {
  const res = response({
    settings: { source: 'stored', basis: 'recording_settings', hash: 'h', note: 'Ältere Aufnahme' },
  });
  const row = replaySummaryRows(res).find((r) => r.key === 'Hinweis');
  assert.equal(row.value, 'Ältere Aufnahme');
  assert.equal(row.tone, 'warn');
});

test('no note means no Hinweis row rather than an empty one', () => {
  assert.equal(
    replaySummaryRows(response()).some((r) => r.key === 'Hinweis'),
    false,
  );
});

test('a completely empty response still renders every row', () => {
  const rows = replaySummaryRows({});
  assert.ok(rows.length >= 9);
  for (const r of rows) {
    assert.ok(!String(r.value).includes('undefined'), `${r.key}: ${r.value}`);
    assert.ok(!String(r.value).includes('NaN'), `${r.key}: ${r.value}`);
  }
});

test('rows survive being handed nothing at all', () => {
  assert.doesNotThrow(() => replaySummaryRows(undefined));
  assert.doesNotThrow(() => replaySummaryRows(null));
});
