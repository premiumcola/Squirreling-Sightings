// ─── sichtungen/_tests/person-naming.test.js ───────────────────────────────
// „kannst du fotos der personen aus allen videos extrahieren damit ich die
// dann auf individuen branden kann?"
//
// The pure halves of the naming sheet: what the counter says, which names
// are offered, and what one assignment sends.

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis.window || {};
globalThis.document = globalThis.document || { getElementById: () => null };

const { namingCounter, nameChoices, assignPayload } = await import('../person-naming.js');

test('the counter counts from one and never runs past the end', () => {
  assert.equal(namingCounter(0, 12), '1 / 12');
  assert.equal(namingCounter(11, 12), '12 / 12');
  // The last assignment removes an item while the index still points at it.
  assert.equal(namingCounter(12, 12), '12 / 12');
});

test('nothing to name says nothing at all', () => {
  assert.equal(namingCounter(0, 0), '');
});

test('known names are offered once each, blanks dropped', () => {
  assert.deepEqual(
    nameChoices([{ name: 'Roman' }, { name: ' Roman ' }, { name: '' }, {}, null, { name: 'Anna' }]),
    ['Roman', 'Anna'],
  );
  assert.deepEqual(nameChoices(null), []);
});

test('an assignment carries the crop AND the clip it came from', () => {
  // Without cam_id/event_id the name reaches the registry but never the
  // event, so the clip would offer the same face again tomorrow.
  const item = {
    relpath: 'motion_detection/cam_a/2026-09-11/crops/e-1.jpg',
    cam_id: 'cam_a',
    event_id: 'e',
  };
  assert.deepEqual(assignPayload(item, '  Roman '), {
    relpath: 'motion_detection/cam_a/2026-09-11/crops/e-1.jpg',
    name: 'Roman',
    cam_id: 'cam_a',
    event_id: 'e',
  });
});

test('a missing item does not produce the string "undefined"', () => {
  assert.deepEqual(assignPayload(null, null), { relpath: '', name: '', cam_id: '', event_id: '' });
});
