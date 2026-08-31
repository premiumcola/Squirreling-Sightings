// ─── mediaview/player/_detection-math.js ───────────────────────────────────
// Pure arithmetic for "jump to next/prev detection", split out of
// _detection-nav.js so it can be unit-tested with plain track-shaped
// fixtures and NO imports — _detection-nav.js's own import of
// mediathek/bbox-overlay/index.js drags in that package's module-load
// side effects (its _initLbDetectionsHooks IIFE touches byId/window at
// import time), which is exactly what this codebase's existing
// node:test convention avoids (see library/_tests/ header comments).

/**
 * Sorted, deduped detection-seek timestamps (seconds) from a tracks
 * array shaped like tracks.json's `.tracks` (and _state.timelineTrackIndex,
 * the same array the swimlane's × tooltip handler reads — see
 * mediathek/bbox-overlay/track-loss-tooltip.js). One entry per track, at
 * the SAME t0 a tap on its bar seeks to
 * (mediathek/bbox-overlay/timeline-panel.js::_onTimelineBarClick) — this
 * is a re-read of the swimlane's own data, not a second source of truth.
 *
 * @param {Array<{samples?: Array<{t:number}>}>} tracks
 * @returns {number[]}
 */
export function seeksFromTracks(tracks) {
  const list = Array.isArray(tracks) ? tracks : [];
  const seen = new Set();
  const out = [];
  for (const tr of list) {
    const samples = (tr && tr.samples) || [];
    if (!samples.length) continue;
    const t0 = samples[0] && samples[0].t;
    if (!Number.isFinite(t0)) continue;
    const t = Math.max(0, t0);
    const key = t.toFixed(2);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(t);
  }
  out.sort((a, b) => a - b);
  return out;
}

// Sub-frame slack so a seek that landed EXACTLY on a detection timestamp
// (the common case right after a jump) still finds the true next/prev
// entry instead of re-triggering itself.
const _EPS = 0.05;

/**
 * Pure — the next (dir > 0) or previous (dir < 0) seek time strictly
 * past `currentTime`, or `null` when there isn't one (start/end of the
 * list — the caller decides how to surface that, e.g. a toast).
 *
 * @param {number[]} times   sorted ascending, from seeksFromTracks
 * @param {number} currentTime
 * @param {number} [dir]     +1 (default) or -1
 */
export function findAdjacentSeek(times, currentTime, dir = 1) {
  if (!Array.isArray(times) || !times.length) return null;
  const cur = Number.isFinite(currentTime) ? currentTime : 0;
  if (dir < 0) {
    for (let i = times.length - 1; i >= 0; i--) {
      if (times[i] < cur - _EPS) return times[i];
    }
    return null;
  }
  for (const t of times) {
    if (t > cur + _EPS) return t;
  }
  return null;
}
