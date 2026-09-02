// ─── vplayer/_tests/delete-flow.test.js ────────────────────────────────────
// The delete branches, and the reason they are worth a test file of
// their own: the detection-feedback ledger is written SERVER-side, and
// which verdict gets booked is decided entirely by WHICH URL the
// frontend hits.
//
//   /api/camera/<cam>/events/<id>            → books correct=False
//   /api/weather/sightings/<id>              → books nothing
//   /api/camera/<cam>/timelapse/<file>       → books nothing
//
// So a mis-routed branch does not throw and does not look wrong on
// screen — it quietly files a "Fehlalarm" against a recording nobody
// judged, and because the ledger is last-write-wins per event_id it
// overwrites an honest ✅ tapped in Telegram. That is the failure these
// assertions exist to catch.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DELETE_MOTION,
  DELETE_TIMELAPSE,
  DELETE_WEATHER,
  deleteBranchFor,
  deleteRequestFor,
  needsArming,
  runDelete,
} from '../_delete-flow.js';

const MOTION = { camera_id: 'cam-1', event_id: 'ev-9', type: 'motion' };
const TIMELAPSE = { camera_id: 'cam-1', event_id: 'tl_2026-09-01', type: 'timelapse', filename: 'x.mp4' };
const WEATHER = { camera_id: 'cam-1', event_id: 'ws-3', type: 'timelapse', source: 'weather' };

/** Records the requests a flow makes. */
function fakeDeps(over = {}) {
  const calls = [];
  let armed = false;
  return {
    calls,
    isArmed: () => armed,
    arm: () => {
      armed = true;
    },
    request: (url, opts) => {
      calls.push({ url, method: opts?.method });
      return Promise.resolve({ ok: true });
    },
    onDeleted: () => {},
    onError: () => {},
    ...over,
  };
}

test('each branch is selected by its own condition', () => {
  assert.equal(deleteBranchFor(MOTION), DELETE_MOTION);
  assert.equal(deleteBranchFor(TIMELAPSE), DELETE_TIMELAPSE);
  assert.equal(deleteBranchFor(WEATHER), DELETE_WEATHER);
  assert.equal(deleteBranchFor(null), null);
});

test('a weather sighting is weather FIRST, though it is timelapse-shaped', () => {
  // It is synthesised with type:'timelapse'. Testing type first would
  // route it at the timelapse endpoint, which 404s on sighting ids.
  assert.equal(WEATHER.type, 'timelapse', 'fixture must keep the shape that makes this a trap');
  assert.equal(deleteBranchFor(WEATHER), DELETE_WEATHER);
});

test('each branch hits its OWN endpoint and no other', async () => {
  const m = fakeDeps();
  await runDelete(MOTION, m);
  assert.deepEqual(m.calls, [{ url: '/api/camera/cam-1/events/ev-9', method: 'DELETE' }]);

  const t = fakeDeps({ isArmed: () => true });
  await runDelete(TIMELAPSE, t);
  assert.deepEqual(t.calls, [{ url: '/api/camera/cam-1/timelapse/x.mp4', method: 'DELETE' }]);

  const w = fakeDeps({ isArmed: () => true });
  await runDelete(WEATHER, w);
  assert.deepEqual(w.calls, [{ url: '/api/weather/sightings/ws-3', method: 'DELETE' }]);
});

test('a timelapse delete NEVER touches the events endpoint', async () => {
  // The events endpoint is the one that books a verdict. The backend
  // additionally skips ids starting `tl_`, but the frontend must not
  // rely on that guard — it must simply not go there.
  const t = fakeDeps({ isArmed: () => true });
  await runDelete(TIMELAPSE, t);
  for (const c of t.calls) {
    assert.equal(c.url.includes('/events/'), false, `timelapse reached ${c.url}`);
  }
});

test('a weather delete NEVER touches the events endpoint', async () => {
  const w = fakeDeps({ isArmed: () => true });
  await runDelete(WEATHER, w);
  for (const c of w.calls) {
    assert.equal(c.url.includes('/events/'), false, `weather reached ${c.url}`);
  }
});

test('weather and timelapse need two taps; motion does not', () => {
  // Asymmetric by construction — this is how it shipped, and the
  // motion path's only two-step route is the ArrowDown key.
  assert.equal(needsArming(DELETE_WEATHER), true);
  assert.equal(needsArming(DELETE_TIMELAPSE), true);
  assert.equal(needsArming(DELETE_MOTION), false);
});

test('the first tap on a timelapse arms instead of deleting', async () => {
  const d = fakeDeps();
  const first = await runDelete(TIMELAPSE, d);
  assert.deepEqual(first, { armed: true });
  assert.equal(d.calls.length, 0, 'nothing may be deleted on the first tap');

  const second = await runDelete(TIMELAPSE, d);
  assert.deepEqual(second, { deleted: true });
  assert.equal(d.calls.length, 1);
});

test('a motion delete fires on the FIRST tap', async () => {
  const d = fakeDeps();
  const out = await runDelete(MOTION, d);
  assert.deepEqual(out, { deleted: true });
  assert.equal(d.calls.length, 1);
});

test('the timelapse filename falls back to the relpath basename', () => {
  const req = deleteRequestFor({
    camera_id: 'cam-1',
    type: 'timelapse',
    relpath: 'timelapse/cam-1/2026-09-01.mp4',
  });
  assert.equal(req.url, '/api/camera/cam-1/timelapse/2026-09-01.mp4');
});

test('every id and filename is URL-encoded into the path', () => {
  const req = deleteRequestFor({ camera_id: 'cam/1', event_id: 'ev 9', type: 'motion' });
  assert.equal(req.url, '/api/camera/cam%2F1/events/ev%209');
});

test('an incomplete item makes no request at all', async () => {
  assert.equal(deleteRequestFor({ type: 'motion' }), null);
  assert.equal(deleteRequestFor({ type: 'timelapse', camera_id: 'c' }), null);
  assert.equal(deleteRequestFor({ source: 'weather' }), null);

  let err = null;
  const d = fakeDeps({ onError: (m) => (err = m) });
  const out = await runDelete({ type: 'motion' }, d);
  assert.deepEqual(out, { deleted: false });
  assert.equal(d.calls.length, 0);
  assert.ok(err && err.length > 0, 'the operator must be told');
});

test('a failed request reports and does not claim the delete happened', async () => {
  let err = null;
  const d = fakeDeps({
    request: () => Promise.reject(new Error('500')),
    onError: (m) => (err = m),
  });
  let after = false;
  d.onDeleted = () => {
    after = true;
  };
  const out = await runDelete(MOTION, d);
  assert.deepEqual(out, { deleted: false });
  assert.equal(after, false, 'the aftermath must not run on a failure');
  assert.ok(err.includes('fehlgeschlagen'));
});

test('the aftermath is told which branch ran', async () => {
  // The grids, the re-pagination and the neighbour to open all differ
  // per branch, so the caller needs to know which one fired.
  const seen = [];
  const d = fakeDeps({ isArmed: () => true, onDeleted: (b) => seen.push(b) });
  await runDelete(MOTION, d);
  await runDelete(TIMELAPSE, d);
  await runDelete(WEATHER, d);
  assert.deepEqual(seen, [DELETE_MOTION, DELETE_TIMELAPSE, DELETE_WEATHER]);
});
