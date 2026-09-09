// ─── mediathek/_tests/processing.test.js ────────────────────────────────
// The "hängt" badge used to fire the moment `queued` outlasted its
// 2-minute stall ceiling — which a busy feeder trips in minutes on a
// FIFO that is working exactly as designed (see `_encode_queue.py`).
// `/api/media/queue-status` is the encoder's own live state; when it
// confirms a "stalled" clip is still third in a real line, the UI must
// say `waiting`/"Platz 3 von N", not the scarier `hängt`. A clip the
// live queue does NOT recognise stays `hängt` — that one really has no
// thread left working on it.
import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = { addEventListener() {} };
const hostEl = { innerHTML: '' };
const gridEl = { parentNode: {} };
globalThis.document = {
  getElementById: (id) =>
    id === 'mediaGrid' ? gridEl : id === 'mediaProcessingQueue' ? hostEl : null,
};

let fetchResponse = null;
let fetchCalls = 0;
globalThis.fetch = async () => {
  fetchCalls++;
  return { ok: true, json: async () => fetchResponse };
};

const flush = () => new Promise((resolve) => setTimeout(resolve, 10));

const {
  fmtElapsed,
  isPendingItem,
  isActivelyPending,
  needsProcessingTile,
  procStateOf,
  queueTitle,
  processingQueueHTML,
  renderProcessingQueue,
} = await import('../_processing.js');

// ── fmtElapsed ───────────────────────────────────────────────────────────
test('fmtElapsed formats seconds, minutes and hours+minutes', () => {
  assert.equal(fmtElapsed(null), '');
  assert.equal(fmtElapsed(-1), '');
  assert.equal(fmtElapsed(0), '0 s');
  assert.equal(fmtElapsed(45), '45 s');
  assert.equal(fmtElapsed(59.6), '60 s');
  assert.equal(fmtElapsed(90), '1 min');
  assert.equal(fmtElapsed(3540), '59 min');
  assert.equal(fmtElapsed(3600), '1 h 0 min');
  assert.equal(fmtElapsed(3661), '1 h 1 min');
});

// ── isPendingItem / isActivelyPending / needsProcessingTile ────────────
test('a stalled clip is pending but not actively polled for', () => {
  const stalled = { stage: 'queued', stage_stalled: true };
  assert.equal(isPendingItem(stalled), true);
  assert.equal(isActivelyPending(stalled), false);
});

test('a ready clip is neither pending nor a processing tile', () => {
  const ready = { stage: 'ready', video_url: '/media/x.mp4' };
  assert.equal(isPendingItem(ready), false);
  assert.equal(needsProcessingTile(ready), false);
});

test('an error with no playable file still gets a tile', () => {
  assert.equal(needsProcessingTile({ status: 'error' }), true);
  assert.equal(needsProcessingTile({ status: 'error', video_url: '/media/x.mp4' }), false);
});

// ── procStateOf, without any live queue data ────────────────────────────
test('procStateOf: busy, stalled and failed read correctly with no queue data', () => {
  assert.equal(procStateOf({ stage: 'encoding' }).kind, 'busy');
  const stalled = procStateOf({ stage: 'queued', stage_stalled: true, stage_age_s: 400 });
  assert.equal(stalled.kind, 'stalled');
  assert.equal(stalled.label, 'hängt');
  assert.equal(procStateOf({ status: 'error' }).kind, 'failed');
});

// ── queueTitle ───────────────────────────────────────────────────────────
test('queueTitle: stuck always wins, even alongside busy/waiting', () => {
  assert.equal(queueTitle({ busy: 2, waiting: 3, stuck: 1 }), '1 Video hängt');
  assert.equal(queueTitle({ stuck: 4 }), '4 Videos hängen');
});

test('queueTitle: busy and waiting without any stuck clip', () => {
  assert.equal(queueTitle({ busy: 1 }), '1 Video wird verarbeitet');
  assert.equal(queueTitle({ busy: 2 }), '2 Videos werden verarbeitet');
  assert.equal(queueTitle({ waiting: 1 }), '1 Video wartet in der Reihe');
  assert.equal(queueTitle({ waiting: 5 }), '5 Videos warten in der Reihe');
  assert.equal(queueTitle({ busy: 1, waiting: 2 }), '3 Videos in Arbeit');
});

// ── processingQueueHTML, without live queue data ────────────────────────
test('processingQueueHTML is empty for an empty list', () => {
  assert.equal(processingQueueHTML([]), '');
});

test('a stalled-only strip shows the warning mark and "hängt"', () => {
  const html = processingQueueHTML([{ stage: 'encoding', stage_stalled: true, stage_age_s: 999 }]);
  assert.match(html, /mvp-warn/);
  assert.match(html, /hängt/);
});

// ── the actual fix: a clip the live queue still owns ────────────────────
test('a queued clip the live encode queue confirms reads as waiting, with position and ETA', async () => {
  fetchResponse = {
    slots: 2,
    running: 2,
    avg_encode_s: 30,
    queued: [
      { event_id: 'e1', camera_id: 'cam_a', camera_name: 'Cam A', position: 1, eta_s: 30 },
      { event_id: 'e2', camera_id: 'cam_a', camera_name: 'Cam A', position: 2, eta_s: 60 },
    ],
  };
  const before = fetchCalls;
  const items = [
    {
      event_id: 'e1',
      stage: 'queued',
      stage_stalled: true,
      stage_age_s: 400,
      camera_name: 'Cam A',
    },
  ];

  // First paint: nothing fetched yet, so it is still the honest "hängt".
  renderProcessingQueue(items);
  assert.equal(fetchCalls, before + 1, 'render kicked off the global-queue fetch');
  assert.match(hostEl.innerHTML, /hängt/);

  // Once the fetch resolves, the strip repaints itself unprompted.
  await flush();
  assert.match(hostEl.innerHTML, /Platz 1 von 2/);
  assert.doesNotMatch(hostEl.innerHTML, /hängt/);
  assert.match(hostEl.innerHTML, /mvp-wait/);
  assert.match(hostEl.innerHTML, /ca\. 30 s/);

  // Stop the poll so it doesn't outlive this test.
  renderProcessingQueue([]);
});

test('a clip the live queue does NOT recognise stays "hängt" even with fresh queue data', async () => {
  fetchResponse = { slots: 2, running: 2, avg_encode_s: 30, queued: [] };
  const items = [
    { event_id: 'ghost', stage: 'encoding', stage_stalled: true, stage_age_s: 200000 },
  ];
  renderProcessingQueue(items);
  await flush();
  assert.match(hostEl.innerHTML, /hängt/);
  assert.doesNotMatch(hostEl.innerHTML, /Platz/);
  renderProcessingQueue([]);
});
