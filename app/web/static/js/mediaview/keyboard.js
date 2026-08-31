// ─── mediaview/keyboard.js ─────────────────────────────────────────────────
// Every keyboard and touch shortcut that drives the lightbox / MediaView
// modal, in one place. R23 moved the two installers below out of
// lightbox.js, which stood 822 lines against a 400-line ceiling and had
// them as bare module-scope side effects.
//
// Both installers take their collaborators as callbacks rather than
// importing lightbox.js. That is deliberate: lightbox.js already sits in
// three load-bearing import cycles, and reaching back into it from here
// would add a fourth for nothing — the arguments are the same functions
// the caller already has in scope.
//
// Each installer returns a teardown function. lightbox.js installs once
// at module scope and never tears down (the modal is a permanent DOM
// fixture); the return value exists so a future mount/unmount owner does
// not have to reopen this file.
import { byId } from '../core/dom.js';
import { getActiveLightboxBindings, isShortcutHelpAvailable } from './lightbox-bindings.js';
import { mountShortcutHelp } from './shortcut-help.js';
import { getDeviceTier } from './device-tier.js';

const _FORM_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

function _isFormFocus(target) {
  if (!target) return false;
  if (_FORM_TAGS.has(target.tagName)) return true;
  if (target.isContentEditable) return true;
  return false;
}

export function installMediaViewKeyboard(getVideoEl) {
  if (typeof getVideoEl !== 'function') {
    throw new Error('installMediaViewKeyboard: pass a getVideoEl() callback');
  }
  const onKey = (e) => {
    if (_isFormFocus(e.target)) return;
    const video = getVideoEl();
    if (!video) return;
    if (e.key === ' ') {
      e.preventDefault();
      if (video.paused || video.ended) {
        video.play().catch(() => {});
      } else {
        video.pause();
      }
      return;
    }
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      video.currentTime = Math.max(0, (video.currentTime || 0) - 5);
      return;
    }
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      const dur = Number.isFinite(video.duration) ? video.duration : 0;
      const next = (video.currentTime || 0) + 5;
      video.currentTime = dur > 0 ? Math.min(dur, next) : next;
    }
  };
  window.addEventListener('keydown', onKey);
  return () => window.removeEventListener('keydown', onKey);
}

// ── Lightbox keydown ────────────────────────────────────────────────────────
// Drilldown back-nav: Backspace or Escape returns to overview when no
// lightbox is open. Skip when the user is typing in an input/textarea so
// editable fields keep their normal behavior.
//
// NOTE this guard is deliberately NOT _isFormFocus: it has never counted
// SELECT as editable, while the lightbox branch below always has. Kept
// verbatim — widening it here would change which keystrokes close the
// drilldown, which is a behaviour change, not a refactor.
function _drilldownBackNav(e, deps) {
  if (e.key !== 'Escape' && e.key !== 'Backspace') return;
  if (byId('mediaDrilldown')?.style.display === 'none') return;
  const t = e.target;
  const isEditable =
    t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
  if (isEditable) return;
  e.preventDefault();
  deps.closeMediaDrilldown();
}

// Seek step — was 10 s; tightened to 5 s to match the mediaview task #6
// spec. Five-second granularity reads more naturally for 10-30 s motion
// clips, where 10 s would overshoot interesting segments in two presses.
function _arrowSeekOrNav(e, ctx, deps) {
  e.preventDefault();
  if (e.key === 'ArrowLeft') {
    if (ctx.videoActive) {
      ctx.video.currentTime = Math.max(0, (ctx.video.currentTime || 0) - 5);
      deps.showSeekOverlay('−5s');
    } else {
      deps.navPrev();
    }
    return;
  }
  if (ctx.videoActive) {
    const dur = ctx.video.duration || 0;
    const next = (ctx.video.currentTime || 0) + 5;
    ctx.video.currentTime = dur > 0 ? Math.min(dur, next) : next;
    deps.showSeekOverlay('+5s');
  } else {
    deps.navNext();
  }
}

function _spaceOrFullscreen(e, ctx) {
  if (!ctx.videoActive) return;
  e.preventDefault();
  if (e.key === ' ') {
    if (ctx.video.paused) ctx.video.play().catch(() => {});
    else ctx.video.pause();
    return;
  }
  const fsElem = document.fullscreenElement || document.webkitFullscreenElement;
  if (fsElem) {
    (document.exitFullscreen || document.webkitExitFullscreen || function () {})
      .call(document)
      .catch(() => {});
    return;
  }
  const v = ctx.video;
  const req = v.requestFullscreen || v.webkitRequestFullscreen || v.webkitEnterFullscreen;
  if (req) req.call(v).catch(() => {});
}

// Transport v2 shortcuts — frame-step / speed / loop / detection-nav /
// snapshot. `deps` supplies the actual video mutation (stepFrame,
// cycleSpeed, toggleLoop, jumpDetection, snapshot) rather than this file
// importing mediaview/player/* directly: those modules reach into
// mediathek/bbox-overlay/index.js (jumpDetection) and touch <canvas>
// (snapshot), and this file's own header comment already explains why
// its installers take collaborators as callbacks instead of importing
// across domains — lightbox.js, which already imports all of player/*
// for other reasons, is where the real functions live.
//
// Only fires while a recorded/timelapse video is actually showing
// (ctx.videoActive) — same gate _spaceOrFullscreen uses — so live/
// weather modes (no #lightboxVideo content) get a silent no-op rather
// than needing to join the ArrowUp/ArrowDown `suppressed` list below,
// which exists for keys that mean something ELSE outside video context.
export function _transportV2Shortcut(e, ctx, deps) {
  if (!ctx.videoActive) return false;
  const v = ctx.video;
  switch (e.key) {
    case ',':
    case '.':
      e.preventDefault();
      deps.stepFrame(v, e.key === '.' ? 1 : -1);
      return true;
    case '<':
    case '>':
      e.preventDefault();
      deps.cycleSpeed(v, e.key === '>' ? 1 : -1);
      return true;
    case 'l':
    case 'L':
      e.preventDefault();
      deps.toggleLoop(v);
      return true;
    case '[':
    case ']':
      e.preventDefault();
      deps.jumpDetection(v, e.key === ']' ? 1 : -1);
      return true;
    case 's':
    case 'S':
      e.preventDefault();
      deps.snapshot(v);
      return true;
    default:
      return false;
  }
}

// ── '?' shortcut-help overlay ───────────────────────────────────────────────
// Module-singleton mount handle — installLightboxKeys is only ever
// installed once (see this file's header note), so one module-level slot
// is enough and lets installLightboxKeys's onKey check "is the help panel
// currently up" without threading state through `deps`.
let _help = null;

function _closeShortcutHelp() {
  _help?.teardown();
  _help = null;
}

// Gated to the 'full' device tier (mediaview/device-tier.js). Reads the
// LIVE capability via getDeviceTier() rather than the mounted shell's
// `data-tier` — plain photo items never mount mediaview/shell.js at all
// (only the video/timelapse/weather/live-detect modes do), and '?' must
// still work there on a desktop: tier is a property of the operator's
// screen + pointer, not of which lightbox mode happens to be showing.
// On 'compact' (touch / narrow) this is a silent no-op: no
// preventDefault, no overlay — '?' behaves exactly as it did before this
// feature existed.
function _toggleShortcutHelp(ctx, e) {
  if (!isShortcutHelpAvailable(getDeviceTier())) return;
  e.preventDefault();
  if (_help) {
    _closeShortcutHelp();
    return;
  }
  _help = mountShortcutHelp(getActiveLightboxBindings(ctx), _closeShortcutHelp);
}

// Single ctx builder for the whole lightbox keydown surface — dispatch
// (below) AND the '?' shortcut-help overlay (lightbox-bindings.js's
// getActiveLightboxBindings) read the exact same `videoActive` /
// `suppressed` fields from here, so the help list can never show a
// binding that this function's own branches wouldn't also honour.
function _buildLightboxCtx() {
  const video = byId('lightboxVideo');
  const modal = byId('lightboxModal');
  // Live-sim suppresses prev/next + confirm/delete keys — there's no
  // recorded item to navigate to or label. Esc + Space + F still route
  // through their normal handlers below so the user keeps close-on-Esc
  // and fullscreen-on-F.
  // L1 · weather shares this container too; like live it has no recorded
  // item to seek/label, so it suppresses the same keys (its own title-bar
  // chevrons handle navigation).
  const suppressed = !!(
    modal &&
    (modal.classList.contains('lb-live-detect') || modal.classList.contains('lb-weather'))
  );
  return {
    video,
    videoActive: !!(video && video.style.display !== 'none' && video.src),
    suppressed,
  };
}

function _openLightboxShortcut(e, deps) {
  const ctx = _buildLightboxCtx();
  const { suppressed } = ctx;
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    if (suppressed) {
      e.preventDefault();
      return;
    }
    _arrowSeekOrNav(e, ctx, deps);
  } else if (e.key === 'ArrowUp') {
    if (suppressed) {
      e.preventDefault();
      return;
    }
    e.preventDefault();
    byId('lightboxConfirm').click();
  } else if (e.key === 'ArrowDown') {
    if (suppressed) {
      e.preventDefault();
      return;
    }
    e.preventDefault();
    deps.handleDeleteKey();
  } else if (e.key === ' ' || e.key === 'f' || e.key === 'F') {
    _spaceOrFullscreen(e, ctx);
  } else if (_transportV2Shortcut(e, ctx, deps)) {
    // handled inside — frame-step / speed / loop / detection-nav / snapshot
  } else if (e.key === '?') {
    _toggleShortcutHelp(ctx, e);
  } else if (e.key === 'Escape') {
    deps.closeLightbox();
  }
}

/**
 * Document-level shortcuts for the lightbox and the media drilldown.
 * `deps` supplies every collaborator: closeLiveView, closeMediaDrilldown,
 * closeLightbox, navPrev, navNext, handleDeleteKey, showSeekOverlay,
 * stepFrame, cycleSpeed, toggleLoop, jumpDetection, snapshot.
 */
export function installLightboxKeys(deps) {
  const onKey = (e) => {
    // The help overlay owns the keyboard while it's up: Escape (and '?'
    // again) close it, everything else is swallowed so an operator
    // reading the list can't accidentally seek/delete/navigate behind
    // it. Escape ALWAYS closes it — that's the one guarantee that keeps
    // this from trapping the operator with an open panel and no exit.
    if (_help) {
      if (e.key === 'Escape' || e.key === '?') {
        e.preventDefault();
        _closeShortcutHelp();
      }
      return;
    }
    // Live view ESC close (takes priority)
    if (e.key === 'Escape' && !byId('liveViewModal')?.classList.contains('hidden')) {
      deps.closeLiveView();
      return;
    }
    if (byId('lightboxModal').classList.contains('hidden')) {
      _drilldownBackNav(e, deps);
      return;
    }
    // Suppress lightbox shortcuts whenever the user is typing in a form
    // field — Escape and the seek/nav keys must not steal focus from an
    // active text input embedded in a panel (e.g. the Detections-tab
    // class filter chip).
    if (_isFormFocus(e.target)) return;
    _openLightboxShortcut(e, deps);
  };
  document.addEventListener('keydown', onKey);
  return () => document.removeEventListener('keydown', onKey);
}

// ── Lightbox swipe ──────────────────────────────────────────────────────────
// Swipe navigation on the lightbox media area (mobile). Horizontal swipe =
// prev/next; vertical swipes are ignored (the swipe-down-to-dismiss branch
// was removed — it was firing accidentally on scroll/zoom and the visible
// X button covers the close case).
export function installLightboxSwipe() {
  const wrap = byId('lightboxMediaWrap');
  const modal = byId('lightboxModal');
  if (!wrap || !modal) return () => {};
  let _tx = 0,
    _ty = 0,
    _dragging = false;
  const onStart = (e) => {
    if (e.touches.length !== 1) return;
    _tx = e.touches[0].clientX;
    _ty = e.touches[0].clientY;
    _dragging = true;
  };
  const onEnd = (e) => {
    if (!_dragging) return;
    _dragging = false;
    const dx = e.changedTouches[0].clientX - _tx;
    const dy = e.changedTouches[0].clientY - _ty;
    // Vertical-dominant gestures (scroll, pinch-zoom-finish) must not
    // trigger prev/next — drop them on the floor.
    if (Math.abs(dy) > Math.abs(dx)) return;
    if (Math.abs(dx) < 40) return;
    // Live-sim has no neighbour item to navigate to.
    if (modal.classList.contains('lb-live-detect')) return;
    if (dx < 0) byId('lightboxNext')?.click();
    else byId('lightboxPrev')?.click();
  };
  wrap.addEventListener('touchstart', onStart, { passive: true });
  wrap.addEventListener('touchend', onEnd, { passive: true });
  return () => {
    wrap.removeEventListener('touchstart', onStart);
    wrap.removeEventListener('touchend', onEnd);
  };
}
