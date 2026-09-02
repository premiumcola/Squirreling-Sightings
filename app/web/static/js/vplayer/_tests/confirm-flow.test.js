// ─── vplayer/_tests/confirm-flow.test.js ───────────────────────────────────
// Confirm, and the label correction that shares its ledger.
//
// Both write verdicts SERVER-side, and both depend on the frontend
// posting in a particular shape:
//   · confirm books correct=True on its 200 path, with no `tl_` guard —
//     asymmetric with delete, which the backend does skip for `tl_*`;
//   · labels books a correction ONLY when the posted list is non-empty
//     AND the resulting top label changed. That second rule is only
//     correct because the editor sends ONE TOGGLE PER REQUEST.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { confirmRequestFor, runConfirm } from '../_confirm-flow.js';
import { labelsRequestFor, toggleLabel } from '../panels/_reclassify.js';

const ITEM = { camera_id: 'cam-1', event_id: 'ev-9' };

test('confirm posts to the event own confirm endpoint', () => {
  assert.deepEqual(confirmRequestFor(ITEM), {
    url: '/api/camera/cam-1/events/ev-9/confirm',
    method: 'POST',
  });
});

test('confirm encodes ids into the path', () => {
  const req = confirmRequestFor({ camera_id: 'cam/1', event_id: 'ev 9' });
  assert.equal(req.url, '/api/camera/cam%2F1/events/ev%209/confirm');
});

test('a timelapse CAN be confirmed — no tl_ guard on this path', () => {
  // Deliberately asymmetric with delete, where the backend skips `tl_*`
  // ids. Confirming is a positive judgement a human actually made.
  const req = confirmRequestFor({ camera_id: 'cam-1', event_id: 'tl_2026-09-01' });
  assert.ok(req.url.endsWith('/events/tl_2026-09-01/confirm'));
});

test('an incomplete item makes no confirm request', async () => {
  assert.equal(confirmRequestFor({ camera_id: 'c' }), null);
  assert.equal(confirmRequestFor(null), null);
  const calls = [];
  let err = null;
  const out = await runConfirm(
    { camera_id: 'c' },
    { request: (u) => calls.push(u), onError: (m) => (err = m) },
  );
  assert.deepEqual(out, { confirmed: false });
  assert.equal(calls.length, 0);
  assert.ok(err);
});

test('a failed confirm does not run the aftermath', async () => {
  let after = false;
  const out = await runConfirm(ITEM, {
    request: () => Promise.reject(new Error('500')),
    onConfirmed: () => {
      after = true;
    },
    onError: () => {},
  });
  assert.deepEqual(out, { confirmed: false });
  assert.equal(after, false);
});

test('a successful confirm runs the aftermath exactly once', async () => {
  let n = 0;
  const out = await runConfirm(ITEM, {
    request: () => Promise.resolve({ ok: true }),
    onConfirmed: () => {
      n += 1;
    },
  });
  assert.deepEqual(out, { confirmed: true });
  assert.equal(n, 1);
});

// ── the label correction ───────────────────────────────────────────────

test('toggling adds a label that was absent and removes one present', () => {
  assert.deepEqual(toggleLabel(['cat'], 'bird').sort(), ['bird', 'cat']);
  assert.deepEqual(toggleLabel(['cat', 'bird'], 'cat'), ['bird']);
  assert.deepEqual(toggleLabel([], 'cat'), ['cat']);
  assert.deepEqual(toggleLabel(undefined, 'cat'), ['cat']);
});

test('a two-tap correction really does arrive as two requests', () => {
  // cat → squirrel is remove-cat then add-squirrel. The backend books
  // nothing for the first (the list is briefly empty) and the
  // correction for the second. Batching the two into one request would
  // silently change which corrections the corpus records.
  const afterFirst = toggleLabel(['cat'], 'cat');
  assert.deepEqual(afterFirst, [], 'the intermediate state IS empty');
  const afterSecond = toggleLabel(afterFirst, 'squirrel');
  assert.deepEqual(afterSecond, ['squirrel']);
});

test('the labels request posts the FULL set, not a delta', () => {
  const req = labelsRequestFor(ITEM, ['cat', 'bird']);
  assert.deepEqual(req, {
    url: '/api/camera/cam-1/events/ev-9/labels',
    method: 'POST',
    body: { labels: ['cat', 'bird'] },
  });
});

test('clearing every label is representable and posts an empty list', () => {
  // "Fehlalarm · alle entfernen". The backend books NO correction for
  // it on purpose: "motion" is then our fallback, not the operator
  // asserting the class.
  const req = labelsRequestFor(ITEM, []);
  assert.deepEqual(req.body, { labels: [] });
});

test('an incomplete item makes no labels request', () => {
  assert.equal(labelsRequestFor({ camera_id: 'c' }, ['cat']), null);
  assert.equal(labelsRequestFor(null, ['cat']), null);
});
