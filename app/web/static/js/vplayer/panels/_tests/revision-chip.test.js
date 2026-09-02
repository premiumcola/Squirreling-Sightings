// ─── vplayer/panels/_tests/revision-chip.test.js ───────────────────────────
// The two PURE halves of the revision picker: how a revision is named,
// and which one is active. The rendering half is not tested here — it
// touches the live poll session and a fetch, which is exactly why those
// two decisions were pulled out as pure functions.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PLACEHOLDER } from '../../_helpers.js';
import { activeRevision, revisionLabel } from '../_revision-chip.js';

const REVS = [
  { id: 'current', kind: 'current', label: 'Aktuelles Profil', ts: null },
  { id: 'factory', kind: 'factory', label: 'Werkseinstellung', ts: null },
  { id: '20260830-120000-000001', kind: 'frage', label: 'person', ts: '2026-08-30T12:00:00' },
];

test('the two synthetic revisions are named without a timestamp', () => {
  assert.equal(revisionLabel(REVS[0]), 'Aktuelles Profil');
  assert.equal(revisionLabel(REVS[1]), 'Werkseinstellung');
});

test('an archived revision leads with WHEN, then what kind and which class', () => {
  // The operator picks by time first — "the one from before I changed
  // the threshold this morning" — so the timestamp leads.
  const label = revisionLabel(REVS[2]);
  assert.match(label, /^30\.08\. 12:00/);
  assert.ok(label.includes('Frage'), label);
  assert.ok(label.includes('person'), label);
});

test('a revision label degrades rather than printing Invalid Date', () => {
  // An unparseable stamp is shown as it came rather than as the epoch
  // or "Invalid Date" — the rest of the row still names the kind.
  assert.equal(revisionLabel({ kind: 'frage', ts: 'not-a-date' }), 'not-a-date · Frage');
  assert.equal(revisionLabel({}), PLACEHOLDER);
  assert.equal(revisionLabel(null), PLACEHOLDER);
  // An unknown kind is shown raw rather than swallowed.
  assert.ok(revisionLabel({ kind: 'future_kind', ts: '2026-08-30T12:00:00' }).includes('future_kind'));
});

test('no chosen revision means the current profile', () => {
  assert.equal(activeRevision(REVS, null).id, 'current');
  assert.equal(activeRevision(REVS, undefined).id, 'current');
  assert.equal(activeRevision(REVS, 'factory').id, 'factory');
});

test('a revision the archive no longer offers is NOT silently the current one', () => {
  // Retention evicts records. Falling back to "current" here would put
  // the chip on "Aktuelles Profil" while the backend refuses the id the
  // session still carries — the panel would name a profile that is not
  // the one being asked for.
  assert.equal(activeRevision(REVS, 'evicted-id'), null);
  assert.equal(activeRevision([], 'current'), null);
  assert.equal(activeRevision(null, 'current'), null);
});
