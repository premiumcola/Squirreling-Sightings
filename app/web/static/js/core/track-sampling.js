// ─── core/track-sampling.js ────────────────────────────────────────────────
// Where a tracked subject WAS at time t, and how much the pipeline
// believed it. Pure — no DOM, no module state, no imports beyond the one
// constant it compares against.
//
// It lives in core for the same reason core/box-model.js does: THREE
// painters need it, and it was parked inside one of them. Its home was
// mediathek/bbox-overlay/renderer.js, an orchestrator that resolves
// #lightboxVideo, sizes a canvas and imports lightbox.js — so reaching
// these two functions from anywhere else meant loading a module that
// wires real DOM at import time. That is why the unified player could
// not test its own overlay logic without a browser, and a second
// interpolator "just for the tests" is exactly the parallel
// implementation CLAUDE.md forbids.
//
// renderer.js keeps importing AND re-exporting both, so every existing
// call site — its own, confidence-meter.js's — is unchanged. Both, not
// just the re-export: `export { X } from './y'` does not bind X in the
// re-exporting module's own scope, and renderer.js calls
// _interpolateTrackAt itself. That is the trap this codebase has hit
// before and documents in mediaview/player/_transport.js.

// Mirrors tracking_worker.TRACK_SPAWN_SCORE — a sample below this floor
// is tentative (it extends an existing track but could not spawn one on
// its own). The overlay paints it dashed so the operator can see why one
// track id is carrying mixed-confidence frames.
//
// Re-exported by bbox-overlay/_state.js, which is where it lived and
// where the legacy modules still look for it.
export const TRACK_SPAWN_SCORE = 0.5;

/**
 * The last sample the DETECTOR actually produced, in seconds.
 *
 * `predicted`-source samples extend a track past the last real detection
 * so the post-clip worker can express its grace window. On the picture
 * those frames are not a claim that the subject is still there — they
 * are the tracker saying "still trying". Capping the box at the last
 * real sample makes the outline vanish the instant the subject does,
 * instead of pinning a stale rectangle in place through the grace
 * window. The timeline still renders that tail as its hatch overlay.
 */
function _lastDetectT(track) {
  const samples = track.samples || [];
  for (let i = samples.length - 1; i >= 0; i--) {
    const s = samples[i];
    if (
      s.source === undefined ||
      s.source === null ||
      s.source === 'detect' ||
      s.source === 'track'
    ) {
      return s.t;
    }
  }
  return -1;
}

/**
 * One track, interpolated to playback time `t`.
 *
 * @param {object} track  a tracks.json track: { samples, label, best_score }
 * @param {number} t      seconds into the clip
 * @returns {{bbox, score, label}|null} null outside the track's window —
 *   which is not a failure, it is the track simply not being on screen
 *   yet. The 0.05 s tolerance at each end covers sub-sample play
 *   positions, so a box does not flicker off between two frames.
 */
export function interpolateTrackAt(track, t) {
  const samples = track.samples || [];
  if (!samples.length) return null;
  const first = samples[0];
  if (t < first.t - 0.05) return null;
  const lastDetectT = _lastDetectT(track);
  if (lastDetectT < 0) return null;
  if (t > lastDetectT + 0.05) return null;
  let prev = first,
    next = samples[samples.length - 1];
  for (let i = 0; i < samples.length; i++) {
    if (samples[i].t <= t) prev = samples[i];
    if (samples[i].t >= t) {
      next = samples[i];
      break;
    }
  }
  if (prev === next || next.t === prev.t) {
    return { bbox: prev.bbox, score: prev.score, label: track.label };
  }
  const a = (t - prev.t) / (next.t - prev.t);
  const lerp = (k) => prev.bbox[k] + (next.bbox[k] - prev.bbox[k]) * a;
  return {
    bbox: { x1: lerp('x1'), y1: lerp('y1'), x2: lerp('x2'), y2: lerp('y2') },
    score:
      (prev.source === 'detect'
        ? prev.score
        : next.source === 'detect'
          ? next.score
          : track.best_score) ?? 0,
    label: track.label,
  };
}

/**
 * Classify a track-or-detection sample against the spawn threshold.
 *
 *   confirmed — the SAMPLE's score is at or above the threshold now.
 *   weak      — the track's best_score reached the threshold at some
 *               point, but the current sample is below it.
 *   ghost     — best_score NEVER reached it (the track was held alive
 *               entirely on tentative continuation).
 *
 * The legacy fallback path — a single detection with no track — has no
 * history to derive a "best ever" from, so it collapses to the two-tier
 * view: confirmed or weak against the score alone.
 */
export function classifyTrackStatus(track, sample, threshold) {
  const t = typeof threshold === 'number' ? threshold : TRACK_SPAWN_SCORE;
  const cur = sample && sample.score != null ? sample.score : null;
  const best = track && track.best_score != null ? track.best_score : null;
  if (best != null) {
    if (best < t) return 'ghost';
    if (cur != null && cur < t) return 'weak';
    return 'confirmed';
  }
  if (cur != null && cur < t) return 'weak';
  return 'confirmed';
}
