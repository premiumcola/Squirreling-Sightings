// ─── mediaview/_tests/keyboard-transport.test.js ────────────────────────
// _transportV2Shortcut is pure DISPATCH: it maps e.key -> one of the
// `deps` callbacks lightbox.js supplies (the same functions the
// on-picture control row calls — see lightbox.js's installLightboxKeys
// call). Testing it needs no DOM: keyboard.js's own top-level code is
// import-only (byId is a function reference, never called at module
// load — see core/dom.js), so this file is safe to import directly
// under plain node:test.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { _transportV2Shortcut } from '../keyboard.js';

function _mockDeps() {
  const calls = [];
  const rec =
    (name) =>
    (...args) => {
      calls.push([name, ...args]);
    };
  return {
    calls,
    deps: {
      stepFrame: rec('stepFrame'),
      cycleSpeed: rec('cycleSpeed'),
      toggleLoop: rec('toggleLoop'),
      jumpDetection: rec('jumpDetection'),
      snapshot: rec('snapshot'),
    },
  };
}

function _key(k) {
  let prevented = false;
  return { key: k, preventDefault: () => (prevented = true), wasPrevented: () => prevented };
}

const ACTIVE_CTX = () => ({ video: { id: 'v' }, videoActive: true });
const INACTIVE_CTX = () => ({ video: null, videoActive: false });

test('"," and "." dispatch frame-step back/forward', () => {
  const { calls, deps } = _mockDeps();
  const ctx = ACTIVE_CTX();
  assert.equal(_transportV2Shortcut(_key(','), ctx, deps), true);
  assert.equal(_transportV2Shortcut(_key('.'), ctx, deps), true);
  assert.deepEqual(calls, [
    ['stepFrame', ctx.video, -1],
    ['stepFrame', ctx.video, 1],
  ]);
});

test('"<" and ">" dispatch speed down/up', () => {
  const { calls, deps } = _mockDeps();
  const ctx = ACTIVE_CTX();
  _transportV2Shortcut(_key('<'), ctx, deps);
  _transportV2Shortcut(_key('>'), ctx, deps);
  assert.deepEqual(calls, [
    ['cycleSpeed', ctx.video, -1],
    ['cycleSpeed', ctx.video, 1],
  ]);
});

test('"l" and "L" both toggle loop', () => {
  const { calls, deps } = _mockDeps();
  const ctx = ACTIVE_CTX();
  _transportV2Shortcut(_key('l'), ctx, deps);
  _transportV2Shortcut(_key('L'), ctx, deps);
  assert.deepEqual(calls, [
    ['toggleLoop', ctx.video],
    ['toggleLoop', ctx.video],
  ]);
});

test('"[" and "]" dispatch jump-to-detection prev/next', () => {
  const { calls, deps } = _mockDeps();
  const ctx = ACTIVE_CTX();
  _transportV2Shortcut(_key('['), ctx, deps);
  _transportV2Shortcut(_key(']'), ctx, deps);
  assert.deepEqual(calls, [
    ['jumpDetection', ctx.video, -1],
    ['jumpDetection', ctx.video, 1],
  ]);
});

test('"s" and "S" both trigger a snapshot', () => {
  const { calls, deps } = _mockDeps();
  const ctx = ACTIVE_CTX();
  _transportV2Shortcut(_key('s'), ctx, deps);
  _transportV2Shortcut(_key('S'), ctx, deps);
  assert.deepEqual(calls, [
    ['snapshot', ctx.video],
    ['snapshot', ctx.video],
  ]);
});

test('every handled key calls preventDefault', () => {
  const { deps } = _mockDeps();
  const ctx = ACTIVE_CTX();
  for (const k of [',', '.', '<', '>', 'l', 'L', '[', ']', 's', 'S']) {
    const e = _key(k);
    _transportV2Shortcut(e, ctx, deps);
    assert.equal(e.wasPrevented(), true, `expected preventDefault for "${k}"`);
  }
});

test('an unrelated key is not handled and no deps callback fires', () => {
  const { calls, deps } = _mockDeps();
  const e = _key('a');
  assert.equal(_transportV2Shortcut(e, ACTIVE_CTX(), deps), false);
  assert.equal(e.wasPrevented(), false);
  assert.equal(calls.length, 0);
});

test('keys already owned by existing shortcuts are not claimed here', () => {
  // Space/arrows/f/F/Escape are _spaceOrFullscreen / _arrowSeekOrNav /
  // closeLightbox's territory (see keyboard.js's _openLightboxShortcut) —
  // _transportV2Shortcut must return false for every one of them so the
  // existing branches keep first claim.
  const { calls, deps } = _mockDeps();
  const ctx = ACTIVE_CTX();
  for (const k of [' ', 'f', 'F', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Escape']) {
    assert.equal(_transportV2Shortcut(_key(k), ctx, deps), false, `"${k}" must stay unclaimed`);
  }
  assert.equal(calls.length, 0);
});

test('does nothing while no recorded/timelapse video is active (live/weather modes)', () => {
  const { calls, deps } = _mockDeps();
  const ctx = INACTIVE_CTX();
  for (const k of [',', '.', '<', '>', 'l', '[', ']', 's']) {
    assert.equal(_transportV2Shortcut(_key(k), ctx, deps), false);
  }
  assert.equal(calls.length, 0);
});
