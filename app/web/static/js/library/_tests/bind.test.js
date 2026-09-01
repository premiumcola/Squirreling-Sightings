// ─── library/_tests/bind.test.js ────────────────────────────────────────
// Regression: window._openMediaItem used to be defined ONLY inside
// mediathek/_paging.js's per-camera drilldown render — a motion card in
// THIS grid could paint and be tapped before the operator ever opened a
// single camera's drilldown, and the inline onclick called a function
// that plain did not exist yet. "Today's bird clip does nothing when
// tapped" was exactly that: silent, because a broken inline onclick has
// nowhere to report to.
//
// resolveMotionItem (library/_motion-open.js) is the pure half of the
// fix — the resolution ORDER is what actually matters (this page's own
// items before the cross-grid registry fallback), split into its own
// leaf module specifically so it stays importable without lightbox.js's
// whole dependency tree (which needs a much heavier DOM stub than
// library/_tests/_setup.js provides — confirmed by trying it first).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveMotionItem } from '../_motion-open.js';

test("resolves from this page's own items first", () => {
  const items = [{ event_id: 'e1', camera_id: 'cam1' }];
  const registry = () => {
    throw new Error('must not fall through to the registry when the item is on this page');
  };
  assert.deepEqual(resolveMotionItem(items, 'e1', registry), items[0]);
});

test('falls back to the cross-grid registry for an item painted elsewhere', () => {
  const registryItem = { event_id: 'e2', camera_id: 'cam2' };
  const registry = (id) => (id === 'e2' ? registryItem : null);
  assert.deepEqual(resolveMotionItem([], 'e2', registry), registryItem);
});

test('an id nobody has registered resolves to null, not undefined or a throw', () => {
  assert.equal(
    resolveMotionItem([], 'missing', () => null),
    null,
  );
});

test('an empty/undefined items array still checks the registry', () => {
  const registryItem = { event_id: 'e3' };
  assert.deepEqual(
    resolveMotionItem(undefined, 'e3', () => registryItem),
    registryItem,
  );
});
