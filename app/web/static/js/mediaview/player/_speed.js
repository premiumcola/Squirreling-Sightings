// ─── mediaview/player/_speed.js ────────────────────────────────────────────
// Playback-speed cycling — one of Transport v2's five additions to the
// on-picture transport (_transport.js stayed at skip/play/time on
// purpose; see its own header comment). Not persisted across clips: the
// video element is the same reused #lightboxVideo across every open
// (player/index.js's own header comment explains why), so a leftover
// 2x from the LAST clip would silently carry into the next unrelated
// one with no visual cue reminding the operator why it looks fast.
// _transport-controls.js resets to 1x on every mount instead.

export const SPEED_STEPS = [0.5, 1, 1.5, 2];

/**
 * Pure — next speed in the cycle. Snaps an off-step current value (a
 * stale playbackRate from outside this control) to the nearest step
 * before advancing, so the cycle always lands on a known value.
 *
 * @param {number} current  video.playbackRate
 * @param {number} [dir]    +1 (default, cycle up) or -1 (cycle down)
 */
export function nextSpeed(current, dir = 1) {
  const idx = SPEED_STEPS.indexOf(current);
  const from = idx >= 0 ? idx : _nearestIndex(current);
  const n = SPEED_STEPS.length;
  const next = (((from + (dir < 0 ? -1 : 1)) % n) + n) % n;
  return SPEED_STEPS[next];
}

function _nearestIndex(value) {
  const v = Number.isFinite(value) ? value : 1;
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < SPEED_STEPS.length; i++) {
    const d = Math.abs(SPEED_STEPS[i] - v);
    if (d < bestDist) {
      bestDist = d;
      best = i;
    }
  }
  return best;
}

/** `1.5` → `"1.5×"`, `1` → `"1×"`. */
export function formatSpeed(rate) {
  const r = Number.isFinite(rate) ? rate : 1;
  return `${r}×`;
}

/** Impure — advances video.playbackRate to the next step and returns it.
 * Fires the video element's native `ratechange` event, which is what
 * keeps the on-screen label in sync regardless of whether the change
 * came from the button or from a keyboard shortcut. */
export function applySpeedChange(video, dir = 1) {
  if (!video) return null;
  const rate = nextSpeed(video.playbackRate || 1, dir);
  video.playbackRate = rate;
  return rate;
}
