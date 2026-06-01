// ─── core/track-color.js ───────────────────────────────────────────────────
// Single source of truth for "what color is THIS track?" Mirrors the
// post-clip worker's `tracker_core.color_for_track()` deterministic
// palette so legacy sidecars without a stamped `tr.color` derive the
// SAME color the worker would have written if it had run today —
// downstream renderers (bbox, characteristic card, timeline) all
// route through this helper so they can never disagree.

// Bit-for-bit mirror of the Python palette in app/app/tracker_core.py
// `color_for_track`. If the Python list changes, update both.
const _PALETTE = [
  '#22c55e',
  '#3b82f6',
  '#f59e0b',
  '#ef4444',
  '#a855f7',
  '#14b8a6',
  '#ec4899',
  '#84cc16',
  '#f97316',
  '#06b6d4',
  '#eab308',
  '#8b5cf6',
  '#10b981',
  '#f43f5e',
  '#0ea5e9',
];

function _hashTrackId(id) {
  let n = 0;
  for (let i = 0; i < id.length; i++) n += id.charCodeAt(i);
  return n;
}

/**
 * Resolve the per-track color for any track object. Stamped sidecar
 * values (modern post-clip worker) always win; legacy unstamped
 * tracks fall back to a deterministic derivation from `track_id` so
 * the rendered color stays stable across reloads of the same clip.
 */
export function trackColor(track) {
  if (
    track &&
    typeof track === 'object' &&
    typeof track.color === 'string' &&
    track.color.length > 0
  ) {
    return track.color;
  }
  const id = String(track?.track_id || '');
  if (!id) return _PALETTE[0];
  return _PALETTE[_hashTrackId(id) % _PALETTE.length];
}

// J · live-detect per-track palette. Here colour encodes the track NUMBER
// (not the class — the class is shown by the lane / label icon), assigned by
// `track_num` and cycled. Deliberately excludes green (#22c55e) so a track
// colour can never be confused with the green LIVE marker. Distinct from
// trackColor() above, which serves recorded clips (sidecar-stamped / hashed).
const _LIVE_PALETTE = [
  '#a78bfa',
  '#f6b73c',
  '#2dd4bf',
  '#fb7185',
  '#38bdf8',
  '#a3e635',
  '#e879f9',
  '#fb923c',
];

// Neutral grey for motion-only / unclassified detections (no track number).
export const LIVE_MOTION_COLOR = '#cbd5e1';

/**
 * Stable colour for a live track number, cycled through _LIVE_PALETTE. The
 * same track_num always maps to the same colour for the track's lifetime.
 * A missing / non-positive number (motion-only, unassociated) → neutral grey.
 */
export function liveTrackColor(trackNum) {
  const n = Number(trackNum);
  if (!Number.isFinite(n) || n <= 0) return LIVE_MOTION_COLOR;
  return _LIVE_PALETTE[(n - 1) % _LIVE_PALETTE.length];
}
