// ─── library/_tests/grid.test.js ────────────────────────────────────────
// `renderLibraryGrid` must render `/api/library`'s items in the order
// it is handed them — no client-side re-sort, no grouping by kind — and
// forward each card its own page-relative `idx`.
import './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { renderLibraryGrid } from '../index.js';

function _fakeHost() {
  return { innerHTML: '' };
}

test('renders a deliberately interleaved feed in the given order, not grouped by kind', () => {
  const items = [
    { kind: 'motion', id: 'motion:a', extra: { event_id: 'a' } },
    { kind: 'episode', id: 'episode:b', extra: { id: 'b', started_at: '2026-08-30T10:00:00' } },
    { kind: 'motion', id: 'motion:c', extra: { event_id: 'c' } },
    {
      kind: 'sighting',
      id: 'sighting:d',
      start: '2026-08-30T09:00:00',
      extra: { sighting_id: 'd', event_type: 'fog' },
    },
  ];
  const host = _fakeHost();
  renderLibraryGrid(host, items, {});

  const posA = host.innerHTML.indexOf('data-event-id="a"');
  const posB = host.innerHTML.indexOf('data-ep-id="b"');
  const posC = host.innerHTML.indexOf('data-event-id="c"');
  const posD = host.innerHTML.indexOf('data-id="d"');
  assert.ok(posA >= 0 && posB >= 0 && posC >= 0 && posD >= 0, 'every item rendered');
  assert.ok(posA < posB && posB < posC && posC < posD, 'DOM order must match input order exactly');
});

test('an empty page renders the empty-state message, not a blank grid', () => {
  const host = _fakeHost();
  renderLibraryGrid(host, [], {});
  assert.match(host.innerHTML, /Keine Einträge vorhanden/);
});

test('a null/undefined host is a no-op, not a throw', () => {
  assert.doesNotThrow(() => renderLibraryGrid(null, [{ kind: 'motion', extra: {} }], {}));
});
