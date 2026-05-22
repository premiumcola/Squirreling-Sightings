// ─── core/ios-video.js ─────────────────────────────────────────────────────
// iOS-specific video / stream playback helpers. Two concerns:
//
//   1. isIOS detection — a single source of truth for every module that
//      needs to apply iOS-only behaviour (mosaic stream cap, autoplay
//      retry policy, etc.). Edge-cased against the iPadOS 13+ identifies-
//      as-Mac thing and against IE11 + WebView's MSStream signature.
//
//   2. visibilitychange handling — iOS hard-pauses MJPEG <img> streams
//      and <video> playback when the tab/PWA goes to the background.
//      A plain element.play() / src reassign on resume often fails
//      silently because the element entered a weird half-paused state
//      while hidden. This module fires `tamspy:viewport-resumed` on
//      `visibilitychange` → visible so subscribers can re-init streams
//      with a cache-busted URL or a fresh play().catch() pair.

const _ua = typeof navigator !== 'undefined' ? navigator.userAgent || '' : '';
const _platform = typeof navigator !== 'undefined' ? navigator.platform || '' : '';
const _maxTouch = typeof navigator !== 'undefined' ? navigator.maxTouchPoints || 0 : 0;

export const isIOS =
  // Classic iPhone / iPad / iPod UA token, but only when the browser
  // isn't IE/WebView (window.MSStream check rules out the rare false
  // positive in old WebView shells that mimic the iOS UA).
  (/iPad|iPhone|iPod/.test(_ua) && !(typeof window !== 'undefined' && window.MSStream)) ||
  // iPadOS 13+ reports "MacIntel" with maxTouchPoints > 1; disambiguate
  // a real Mac (no touch) from an iPad pretending to be one.
  (_platform === 'MacIntel' && _maxTouch > 1);

// Fire the resume event after a small grace period — iOS sometimes
// reports `visible` while the GPU is still spinning up, and an
// immediate <video>.play() racing that window resolves the promise but
// drops the first frame. 80 ms is empirically enough for the next
// composite to land.
const _RESUME_DELAY_MS = 80;
let _scheduled = false;

function _onVisibilityChange() {
  if (typeof document === 'undefined') return;
  if (document.visibilityState !== 'visible') return;
  if (_scheduled) return;
  _scheduled = true;
  setTimeout(() => {
    _scheduled = false;
    document.dispatchEvent(
      new CustomEvent('tamspy:viewport-resumed', {
        detail: { isIOS },
      }),
    );
  }, _RESUME_DELAY_MS);
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', _onVisibilityChange);
}

// Cap on simultaneously-running MJPEG / video streams. iOS Safari
// crashes around 4 concurrent MJPEGs on real devices; desktop has no
// practical limit at the small counts the dashboard renders.
export const MAX_CONCURRENT_STREAMS = isIOS ? 2 : 6;

// Cross-browser fullscreen entry on a <video> element. Apple ships
// `webkitEnterFullscreen` (only callable on a video, not on its
// container), Chrome/Firefox ship `requestFullscreen` (callable on
// any element). Returns whatever the underlying API returns so the
// caller can chain `.catch` if needed.
export function enterVideoFullscreen(videoEl) {
  if (!videoEl) return null;
  if (videoEl.requestFullscreen) return videoEl.requestFullscreen();
  if (videoEl.webkitEnterFullscreen) return videoEl.webkitEnterFullscreen();
  if (videoEl.webkitRequestFullscreen) return videoEl.webkitRequestFullscreen();
  return null;
}
