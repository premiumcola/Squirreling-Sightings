// ─── mediaview/player/_native.js ───────────────────────────────────────────
// Handing a recorded clip to the platform's own fullscreen player, and
// getting it back afterwards.
//
// Why this is a one-way door for the overlay: on iOS a fullscreen
// <video> is an AVPlayer view rendered OUTSIDE the web page. The SVG box
// layer, the trails canvas and the zone overlay are DOM siblings of that
// <video> — they do not exist in that view, and no amount of z-index
// changes it. Desktop's element-fullscreen has the same effect for the
// same reason: only the promoted element is composited. So the honest
// contract is "the native player, without the boxes", stated in
// NATIVE_WARNING and carried on the control itself (_transport.js).
//
// Entry is FEATURE-DETECTED via core/ios-video.js's enterVideoFullscreen
// (requestFullscreen → webkitEnterFullscreen → webkitRequestFullscreen).
// Never a UA sniff: sniffing is precisely what made the detection boxes
// unreachable on the one device they were built for.
//
// Two failure modes this module exists to prevent, one per direction:
//
//   → entering, a live RAF loop keeps repainting an overlay nobody can
//     see, burning battery on a phone for an invisible result.
//   ← returning, that loop stays dead. bbox-overlay/index.js restarts it
//     from the <video>'s `play` event — but a clip that played straight
//     through the handoff never emits another one. Nothing would ever
//     restart it, and the boxes would sit frozen on the frame the clip
//     was on when it left. resumeOverlayAfterNative restarts it directly.

import { byId } from '../../core/dom.js';
import { enterVideoFullscreen } from '../../core/ios-video.js';
import { showToast } from '../../core/toast.js';
import { _startRafLoop, _stopRafLoop } from '../../mediathek/bbox-overlay/raf.js';
import { _lbDrawDetections } from '../../mediathek/bbox-overlay/renderer.js';
import { clearBboxSvg } from '../../mediathek/bbox-overlay/svg-boxes.js';
import { _updatePlayPct } from '../../mediathek/bbox-overlay/time-axis.js';
import { PLAYER_NATIVE, setPlayerPref } from './_pref.js';

export const NATIVE_WARNING = 'Bboxes und Trails sind im Systemplayer nicht sichtbar.';

// How long to wait for the browser to confirm it actually went
// fullscreen before assuming the request was refused.
const _REFUSAL_GRACE_MS = 1200;

/** Is this element presenting fullscreen right now, by any of the APIs? */
function _isDisplayingFullscreen(videoEl) {
  if (!videoEl) return false;
  if (videoEl.webkitDisplayingFullscreen) return true;
  const active = document.fullscreenElement || document.webkitFullscreenElement || null;
  return active === videoEl;
}

/** Can this element be handed to a native fullscreen player at all? */
export function canNativeFullscreen(videoEl) {
  if (!videoEl) return false;
  return !!(
    videoEl.requestFullscreen ||
    videoEl.webkitEnterFullscreen ||
    videoEl.webkitRequestFullscreen
  );
}

function _wrapOf(videoEl) {
  return (
    (videoEl && videoEl.closest && videoEl.closest('#lightboxMediaWrap')) ||
    byId('lightboxMediaWrap')
  );
}

/**
 * Stop everything that paints over the video and mark the wrap so CSS
 * hides the layers outright. Idempotent — the handoff calls it eagerly
 * and the `begin` event calls it again for entries we did not start.
 */
export function suspendOverlayForNative(videoEl) {
  _stopRafLoop();
  try {
    clearBboxSvg();
  } catch {
    /* layer not mounted yet */
  }
  const wrap = _wrapOf(videoEl);
  if (wrap && wrap.dataset) wrap.dataset.nativeFs = '1';
  // The native view needs its own controls; ours are gone up there.
  if (videoEl) videoEl.controls = true;
}

/** Undo suspendOverlayForNative and get the painter running again. */
export function resumeOverlayAfterNative(videoEl) {
  const wrap = _wrapOf(videoEl);
  if (wrap && wrap.dataset) delete wrap.dataset.nativeFs;
  if (videoEl) videoEl.controls = false;
  // A repaint that throws (a layer mid-teardown, a clip that errored
  // while away) must not swallow the loop restart below — the restart is
  // the entire reason this function exists.
  try {
    _lbDrawDetections();
    _updatePlayPct();
  } catch {
    /* the loop below repaints on the next frame anyway */
  }
  if (videoEl && !videoEl.paused && !videoEl.ended) _startRafLoop();
}

/**
 * Watch a video element for fullscreen transitions from ANY source —
 * our own button, the native controls' own fullscreen affordance, Esc,
 * or the iOS swipe-down. iOS fires webkitbeginfullscreen /
 * webkitendfullscreen on the element; everyone else fires
 * fullscreenchange (webkit-prefixed on older Safari) on the document.
 *
 * @returns {Function} teardown
 */
export function watchNativeFullscreen(videoEl, { onEnter, onExit } = {}) {
  if (!videoEl || !videoEl.addEventListener) return () => {};
  const fire = (fn) => {
    if (typeof fn === 'function') fn(videoEl);
  };
  const onBegin = () => fire(onEnter);
  const onEnd = () => fire(onExit);
  const onChange = () => {
    const active = document.fullscreenElement || document.webkitFullscreenElement || null;
    if (active === videoEl) fire(onEnter);
    else if (!active) fire(onExit);
  };
  videoEl.addEventListener('webkitbeginfullscreen', onBegin);
  videoEl.addEventListener('webkitendfullscreen', onEnd);
  document.addEventListener('fullscreenchange', onChange);
  document.addEventListener('webkitfullscreenchange', onChange);
  return () => {
    videoEl.removeEventListener('webkitbeginfullscreen', onBegin);
    videoEl.removeEventListener('webkitendfullscreen', onEnd);
    document.removeEventListener('fullscreenchange', onChange);
    document.removeEventListener('webkitfullscreenchange', onChange);
  };
}

/**
 * Hand the clip over. Must be called from a user gesture — iOS refuses
 * webkitEnterFullscreen outside one.
 *
 * @param {HTMLVideoElement} videoEl
 * @param {{remember?: boolean}} [opts]  remember:false skips writing the
 *   preference (used for a one-off handoff).
 * @returns {boolean} whether the handoff was attempted.
 */
export function handoffToNativePlayer(videoEl, opts = {}) {
  if (!canNativeFullscreen(videoEl)) {
    showToast('Systemplayer steht in diesem Browser nicht zur Verfügung', 'warn');
    return false;
  }
  suspendOverlayForNative(videoEl);
  if (opts.remember !== false) setPlayerPref(PLAYER_NATIVE);
  showToast(NATIVE_WARNING, 'info');
  try {
    const res = enterVideoFullscreen(videoEl);
    if (res && typeof res.catch === 'function') {
      res.catch(() => resumeOverlayAfterNative(videoEl));
    }
  } catch {
    resumeOverlayAfterNative(videoEl);
    return false;
  }
  // A refusal can be completely silent: webkitEnterFullscreen returns
  // undefined and simply does nothing when iOS decides the call was not
  // in a user gesture. Without this check the clip would be stranded
  // with native controls over hidden overlay layers until the modal
  // closes — the "stale overlay" failure mode, arrived at from the
  // other side.
  setTimeout(() => {
    if (!_isDisplayingFullscreen(videoEl)) resumeOverlayAfterNative(videoEl);
  }, _REFUSAL_GRACE_MS);
  return true;
}
