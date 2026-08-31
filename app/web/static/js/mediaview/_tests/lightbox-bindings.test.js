// ─── mediaview/_tests/lightbox-bindings.test.js ────────────────────────────
// getActiveLightboxBindings is pure DISPATCH-MIRRORING data: it must show
// exactly the keys keyboard.js's own _openLightboxShortcut branches would
// actually act on for a given ctx — no more (a key that's a no-op in this
// mode listed as if it worked), no less (a real binding silently missing).
// ctx here is hand-built the same shape keyboard.js's _buildLightboxCtx()
// produces ({ video, videoActive, suppressed }), matching the existing
// keyboard-transport.test.js pattern of testing the pure half directly
// without a DOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getActiveLightboxBindings, isShortcutHelpAvailable } from '../lightbox-bindings.js';
import { TIER_FULL, TIER_COMPACT } from '../device-tier.js';

function _keysOf(bindings) {
  return bindings.map((b) => b.keys.join('/'));
}

test('recorded mode with an active video: seek + transport-v2 + confirm/delete + esc + ?', () => {
  const ctx = { videoActive: true, suppressed: false };
  const keys = _keysOf(getActiveLightboxBindings(ctx));
  assert.deepEqual(
    new Set(keys),
    new Set([
      'Esc',
      '←/→', // 5s seek variant
      '↑',
      '↓',
      'Space',
      'F',
      ',/.',
      '</>',
      'L',
      '[/]',
      'S',
      '?',
    ]),
  );
  // Only ONE arrow-key entry is active at a time — the seek variant, not
  // the prev/next-item variant — since a real video is showing.
  assert.equal(keys.filter((k) => k === '←/→').length, 1);
});

test('a context with no video active (e.g. between items): nav + confirm/delete only', () => {
  const ctx = { videoActive: false, suppressed: false };
  const keys = _keysOf(getActiveLightboxBindings(ctx));
  assert.deepEqual(new Set(keys), new Set(['Esc', '←/→', '↑', '↓', '?']));
  // Play/pause, fullscreen and every Transport v2 key require a video —
  // none of them may appear when nothing is playing.
  for (const gone of ['Space', 'F', ',/.', '</>', 'L', '[/]', 'S']) {
    assert.ok(!keys.includes(gone), `"${gone}" must not be listed without a video`);
  }
  // The label for this arrow binding must be the nav variant, not seek.
  const arrowBinding = getActiveLightboxBindings(ctx).find((b) => b.keys.join('/') === '←/→');
  assert.match(arrowBinding.label, /Element/);
});

test('live-detect / weather (suppressed): only Esc and ? survive', () => {
  const ctx = { videoActive: false, suppressed: true };
  const keys = _keysOf(getActiveLightboxBindings(ctx));
  assert.deepEqual(new Set(keys), new Set(['Esc', '?']));
});

test('suppressed but somehow videoActive still only exposes the video-gated keys, never nav/confirm/delete', () => {
  // Defensive case: even if a future caller ever set suppressed+videoActive
  // together, arrows/confirm/delete (gated on !suppressed) must stay off
  // while Space/F/transport-v2 (gated only on videoActive) still show —
  // this mirrors _openLightboxShortcut's actual independent guards exactly.
  const ctx = { videoActive: true, suppressed: true };
  const keys = _keysOf(getActiveLightboxBindings(ctx));
  assert.ok(!keys.includes('↑'));
  assert.ok(!keys.includes('↓'));
  assert.ok(!keys.includes('←/→'));
  assert.ok(keys.includes('Space'));
  assert.ok(keys.includes(',/.'));
});

test('the "?" key itself is always listed, in every context', () => {
  for (const ctx of [
    { videoActive: true, suppressed: false },
    { videoActive: false, suppressed: false },
    { videoActive: false, suppressed: true },
  ]) {
    assert.ok(_keysOf(getActiveLightboxBindings(ctx)).includes('?'));
  }
});

test('isShortcutHelpAvailable gates strictly on the full tier', () => {
  assert.equal(isShortcutHelpAvailable(TIER_FULL), true);
  assert.equal(isShortcutHelpAvailable(TIER_COMPACT), false);
  assert.equal(isShortcutHelpAvailable(undefined), false);
  assert.equal(isShortcutHelpAvailable('bogus'), false);
});
