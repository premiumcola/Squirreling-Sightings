// ─── mediaview/player/_detection-nav.js ────────────────────────────────────
// Jump-to-next/previous-detection — reads the SAME track data the
// recorded swimlane (mediathek/bbox-overlay/timeline-panel.js) already
// fetched and rendered, via its public getTimelineTracks() export. No
// second tracks.json fetch, no parallel data path.
//
// Pure math lives in _detection-math.js (its own header explains why:
// this file's bbox-overlay import drags in that package's module-load
// side effects, which the pure math must stay free of to unit-test).
import { getTimelineTracks } from '../../mediathek/bbox-overlay/index.js';
import { showToast } from '../../core/toast.js';
import { findAdjacentSeek, seeksFromTracks } from './_detection-math.js';

/**
 * Impure — seeks `video` to the next/previous detection relative to its
 * current time. Returns true on a successful seek, false when there is
 * no next/prev entry (start/end of the list) — surfaced as a toast so
 * the operator gets feedback instead of a button that silently did
 * nothing, rather than throwing.
 *
 * @param {HTMLVideoElement} video
 * @param {number} [dir]  +1 (default, next) or -1 (previous)
 */
export function applyDetectionJump(video, dir = 1) {
  if (!video) return false;
  const times = seeksFromTracks(getTimelineTracks());
  const t = findAdjacentSeek(times, video.currentTime, dir);
  if (t == null) {
    showToast(dir > 0 ? 'Keine weitere Erkennung' : 'Keine frühere Erkennung', 'info');
    return false;
  }
  video.currentTime = t;
  if (video.paused) video.play().catch(() => {});
  return true;
}
