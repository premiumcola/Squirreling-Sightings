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
