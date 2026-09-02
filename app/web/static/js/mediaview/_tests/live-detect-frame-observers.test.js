// ─── mediaview/_tests/live-detect-frame-observers.test.js ──────────────────
// The frame-observer registry that lets a second surface (vplayer's live
// adapter) see the poll loop's frames without forking the loop.
//
// The load-bearing rule is the try/catch: a throwing observer must never
// take down the poll loop, because the poll loop is the thing keeping the
// live view alive. A regression there turns one broken consumer into a
// frozen picture, so it is pinned twice below — once for the loop's own
// survival, once for the OTHER observers still getting their frame.
//
// The registry is module-level state shared by every test in this file, so
// each test unsubscribes what it adds.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { onLiveFrame, _notifyFrameObservers } from '../_live-detect-frame-observers.js';

test('with nothing subscribed, a frame is a no-op', () => {
  assert.doesNotThrow(() => _notifyFrameObservers({ ok: true }));
});

test('a subscriber sees every frame, with the payload passed through untouched', () => {
  const seen = [];
  const off = onLiveFrame((d) => seen.push(d));
  const frame = { ok: true, detections: [{ label: 'bird' }] };
  _notifyFrameObservers(frame);
  _notifyFrameObservers({ ok: false });
  off();
  assert.equal(seen.length, 2);
  assert.equal(seen[0], frame, 'the very same object, not a copy');
  assert.deepEqual(seen[1], { ok: false });
});

test('unsubscribing stops delivery', () => {
  let n = 0;
  const off = onLiveFrame(() => n++);
  _notifyFrameObservers({});
  off();
  _notifyFrameObservers({});
  assert.equal(n, 1);
});

test('unsubscribing twice is harmless', () => {
  const off = onLiveFrame(() => {});
  off();
  assert.doesNotThrow(off);
});

test('a non-function subscriber is refused but still returns a callable unsubscribe', () => {
  for (const bad of [null, undefined, 42, 'fn', {}]) {
    const off = onLiveFrame(bad);
    assert.equal(typeof off, 'function', `onLiveFrame(${String(bad)}) must return a function`);
    assert.doesNotThrow(off);
  }
  // None of those registered, so a frame is still a no-op.
  assert.doesNotThrow(() => _notifyFrameObservers({ ok: true }));
});

test('a throwing observer does NOT take down the notify pass', () => {
  const off = onLiveFrame(() => {
    throw new Error('consumer blew up');
  });
  const warn = console.warn;
  console.warn = () => {};
  try {
    assert.doesNotThrow(() => _notifyFrameObservers({ ok: true }));
  } finally {
    console.warn = warn;
    off();
  }
});

test('a throwing observer does not rob the OTHER observers of their frame', () => {
  const seen = [];
  const offBad = onLiveFrame(() => {
    throw new Error('first one blew up');
  });
  const offGood = onLiveFrame((d) => seen.push(d));
  const warn = console.warn;
  console.warn = () => {};
  try {
    _notifyFrameObservers({ ok: true });
  } finally {
    console.warn = warn;
    offBad();
    offGood();
  }
  assert.deepEqual(seen, [{ ok: true }]);
});

test('the same function subscribed twice is held once (Set semantics)', () => {
  let n = 0;
  const fn = () => n++;
  const off1 = onLiveFrame(fn);
  const off2 = onLiveFrame(fn);
  _notifyFrameObservers({});
  off1();
  off2();
  assert.equal(n, 1);
});
