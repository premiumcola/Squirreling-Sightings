// ─── vplayer/_tests/overflow-menu.test.js ──────────────────────────────────
// Which actions a mode offers. Cheap to pin here, expensive to
// rediscover in a browser — and every entry is an action with
// consequences: a delete offered where there is nothing to delete, or a
// system-player switch offered on a live snapshot stream that has no
// video to hand over.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildPlayerConfig } from '../_config.js';
import {
  buildOverflowItems,
  VP_MENU_DELETE,
  VP_MENU_NATIVE,
  VP_MENU_RECORD,
} from '../_overflow-menu.js';

const ids = (items) => items.map((i) => i.id);

test('a recorded clip with a delete handler offers the delete', () => {
  const cfg = buildPlayerConfig({ mode: 'recorded', actions: { onDelete: () => {} } });
  const items = buildOverflowItems(cfg, { nativeAvailable: true });
  assert.deepEqual(ids(items), [VP_MENU_NATIVE, VP_MENU_DELETE]);
});

test('the delete is marked as the destructive item', () => {
  const cfg = buildPlayerConfig({ mode: 'recorded', actions: { onDelete: () => {} } });
  const del = buildOverflowItems(cfg, {}).find((i) => i.id === VP_MENU_DELETE);
  assert.equal(del.danger, true);
  assert.equal(del.label, 'Aufnahme löschen');
});

test('a mode that permits deleting still offers nothing without a handler', () => {
  // The permission and the handler are different facts. A menu row that
  // calls nothing is worse than an absent one.
  const cfg = buildPlayerConfig({ mode: 'recorded' });
  assert.equal(ids(buildOverflowItems(cfg, {})).includes(VP_MENU_DELETE), false);
});

test('live and simulation never offer a delete, even if handed a handler', () => {
  for (const mode of ['live', 'sim']) {
    const cfg = buildPlayerConfig({ mode, actions: { onDelete: () => {} } });
    assert.equal(
      ids(buildOverflowItems(cfg, { nativeAvailable: true })).includes(VP_MENU_DELETE),
      false,
      `${mode} must not offer a delete`,
    );
  }
});

test('live and simulation offer the record action; recorded does not', () => {
  for (const mode of ['live', 'sim']) {
    const cfg = buildPlayerConfig({ mode });
    assert.ok(ids(buildOverflowItems(cfg, {})).includes(VP_MENU_RECORD));
  }
  const rec = buildPlayerConfig({ mode: 'recorded' });
  assert.equal(ids(buildOverflowItems(rec, {})).includes(VP_MENU_RECORD), false);
});

test('the system-player item appears only when the browser has one', () => {
  const cfg = buildPlayerConfig({ mode: 'recorded' });
  // Feature-detected by the caller and passed in — never UA-sniffed. A
  // UA sniff is what made the detection overlay unreachable on iOS.
  assert.deepEqual(ids(buildOverflowItems(cfg, { nativeAvailable: false })), []);
  assert.deepEqual(ids(buildOverflowItems(cfg, { nativeAvailable: true })), [VP_MENU_NATIVE]);
});

test('the builder never throws on a bare or malformed config', () => {
  assert.deepEqual(buildOverflowItems(null, {}), []);
  assert.deepEqual(buildOverflowItems({}, {}), []);
  assert.deepEqual(buildOverflowItems({ flags: {} }, {}), []);
});

test('every item carries the three fields the renderer reads', () => {
  const cfg = buildPlayerConfig({ mode: 'recorded', actions: { onDelete: () => {} } });
  for (const item of buildOverflowItems(cfg, { nativeAvailable: true })) {
    assert.equal(typeof item.id, 'string');
    assert.equal(typeof item.label, 'string');
    assert.equal(typeof item.danger, 'boolean');
    assert.ok(item.label.length > 0);
  }
});
