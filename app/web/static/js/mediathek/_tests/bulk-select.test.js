// ─── mediathek/_tests/bulk-select.test.js ──────────────────────────────────
// „Alle Elemente auf der aktuellen Seite eben mit einem Klick auswählen,
// vielleicht irgendwie rechts oben mit irgend 'nem Button, der erst
// angezeigt wird, wenn ich eben im Auswahlmodus bin."
//
// The PAGE, not the library: the page is what the operator can look at
// before deleting it. `state.media` is the page slice (mediathek/
// _paging.js); `state._allMedia` is everything the filter matched, and
// selecting that with one tap is how a bulk delete becomes a surprise.

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis.window || {};
globalThis.document = {
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  body: { classList: { add() {}, remove() {}, toggle() {} } },
};

const { pageEventIds, pageFullySelected } = await import('../bulk-delete.js');

test('the page ids are the current slice, in order', () => {
  const media = [{ event_id: 'a' }, { event_id: 'b' }, { event_id: 'c' }];
  assert.deepEqual(pageEventIds(media), ['a', 'b', 'c']);
});

test('entries without an id are skipped rather than selected as undefined', () => {
  assert.deepEqual(pageEventIds([{ event_id: 'a' }, {}, null, { event_id: '' }]), ['a']);
});

test('an empty page yields nothing to select', () => {
  assert.deepEqual(pageEventIds([]), []);
  assert.deepEqual(pageEventIds(null), []);
});

test('the page counts as fully selected only when every id is in the set', () => {
  const ids = ['a', 'b'];
  assert.equal(pageFullySelected(ids, new Set(['a', 'b'])), true);
  assert.equal(pageFullySelected(ids, new Set(['a'])), false);
  assert.equal(pageFullySelected(ids, new Set()), false);
});

test('a selection reaching beyond this page still counts as full', () => {
  // Page 2 selected, then back to page 1 and select it too — page 1 is
  // full even though the set holds more than page 1 holds.
  assert.equal(pageFullySelected(['a'], new Set(['a', 'zz-from-page-2'])), true);
});

test('an empty page is never "fully selected" — there is nothing to clear', () => {
  assert.equal(pageFullySelected([], new Set(['a'])), false);
});

// ── across cameras, and the prune preset ────────────────────────────────

const { groupIdsByCamera, idsExceptLongestPerDay } = await import('../bulk-delete.js');

const clip = (id, cam, day, dur) => ({
  event_id: id,
  camera_id: cam,
  time: `${day}T08:00:00`,
  duration_s: dur,
});

test('a selection made in "Alle Medien" is grouped per camera', () => {
  // The delete endpoint is addressed per camera; the button used to be
  // hidden outside a single-camera drilldown for exactly that reason.
  const items = [clip('a', 'cam1', '2026-09-10', 5), clip('b', 'cam2', '2026-09-10', 5)];
  assert.deepEqual(groupIdsByCamera(['a', 'b'], items), { cam1: ['a'], cam2: ['b'] });
});

test('an id with no known camera is left out, never posted to the wrong one', () => {
  const items = [clip('a', 'cam1', '2026-09-10', 5)];
  assert.deepEqual(groupIdsByCamera(['a', 'fremd'], items), { cam1: ['a'] });
  assert.deepEqual(groupIdsByCamera([], items), {});
  assert.deepEqual(groupIdsByCamera(['a'], []), {});
});

test('the prune preset spares each day its three longest clips', () => {
  const items = [
    clip('d1_long', 'c', '2026-09-10', 30),
    clip('d1_mid', 'c', '2026-09-10', 20),
    clip('d1_third', 'c', '2026-09-10', 10),
    clip('d1_short', 'c', '2026-09-10', 3),
    clip('d2_only', 'c', '2026-09-11', 4),
  ];

  assert.deepEqual(idsExceptLongestPerDay(items), ['d1_short']);
});

test('per DAY, not overall — a quiet day keeps its own best', () => {
  // A global top-3 would erase whole weeks; the 4 s clip on a day of its
  // own is still that day's record.
  const items = [
    clip('a', 'c', '2026-09-10', 90),
    clip('b', 'c', '2026-09-10', 80),
    clip('c', 'c', '2026-09-10', 70),
    clip('quiet', 'c', '2026-09-11', 4),
  ];
  assert.deepEqual(idsExceptLongestPerDay(items), []);
});

test('an unknown length is offered for deletion, not silently protected', () => {
  const items = [
    clip('a', 'c', '2026-09-10', 9),
    clip('b', 'c', '2026-09-10', 8),
    clip('c', 'c', '2026-09-10', 7),
    { event_id: 'kaputt', camera_id: 'c', time: '2026-09-10T09:00:00' },
  ];
  assert.deepEqual(idsExceptLongestPerDay(items), ['kaputt']);
});

test('keeping zero marks everything; an empty pool marks nothing', () => {
  const items = [clip('a', 'c', '2026-09-10', 9), clip('b', 'c', '2026-09-10', 8)];
  assert.deepEqual(idsExceptLongestPerDay(items, 0).sort(), ['a', 'b']);
  assert.deepEqual(idsExceptLongestPerDay([]), []);
  assert.deepEqual(idsExceptLongestPerDay(null), []);
});
