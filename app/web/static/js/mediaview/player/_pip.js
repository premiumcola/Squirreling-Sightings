// ─── mediaview/player/_pip.js ───────────────────────────────────────────────
// Picture-in-Picture handoff for the recorded-clip player — the SAME
// underlying problem _native.js solves for fullscreen (a <video> promoted
// out of the normal DOM stacking context cannot be followed by its SVG/
// canvas overlay siblings), reached through a different platform API and
// with one genuinely different failure mode on the way out.
//
// Entry is FEATURE-DETECTED, mirroring canNativeFullscreen's own shape —
// never a UA sniff:
//   document.pictureInPictureEnabled  — PiP not disabled by policy/platform
//   videoEl.requestPictureInPicture   — the standard entry point exists
//   !videoEl.disablePictureInPicture  — this element isn't opted out
//
// What this deliberately does NOT chase: iOS Safari's OLD, non-standard
// entry point — `webkitSupportsPresentationMode` /
// `webkitSetPresentationMode('picture-in-picture')` — that some pre-14
// iOS Safari versions used before the standard requestPictureInPicture
// API landed there. core/ios-video.js's enterVideoFullscreen chain (the
// only existing precedent in this codebase for a multi-API fallback)
// chains THREE calls, but all three are STANDARD-SHAPED — the same verb,
// just vendor-prefixed. webkitSetPresentationMode is a different SHAPE
// entirely (a mode-string setter with a separate capability-probe
// method, not a Promise-returning request), and nothing elsewhere in
// this codebase carries a fallback of that shape. Given no existing
// precedent for it and no way to test it against a real device from
// here, the decision is: standard API only. An operator on an iOS
// version old enough to lack it simply doesn't get the control offered
// — canPictureInPicture() returns false and the button never renders,
// the same graceful degradation canNativeFullscreen already gives an
// unsupported browser. UNVERIFIED: the exact iOS version cutoff and any
// device-specific quirks beyond what public compatibility tables say —
// no real device was available to confirm this by hand.
//
// suspendOverlayForNative / resumeOverlayAfterNative are reused AS-IS
// from _native.js — they were already written presentation-mode-
// agnostic (they check THAT the video left normal layout, never WHY),
// so there is nothing PiP-specific to add there.
//
// The refusal path is genuinely different, though: iOS's
// webkitEnterFullscreen can refuse SILENTLY (return undefined, do
// nothing) when called outside a user gesture, which is why
// handoffToNativePlayer needs a grace-period timeout to notice a refusal
// that never fires any event at all. requestPictureInPicture() is
// specified to return a Promise that REJECTS on refusal (no active user
// gesture, permissions-policy block, another element already in PiP that
// won't yield, etc.) — there is no silent-no-op case to guard against
// with a timer, so this module does not carry an equivalent of
// _REFUSAL_GRACE_MS. What it does carry is the same defensive shape
// handoffToNativePlayer uses for a synchronous throw.

import { resumeOverlayAfterNative, suspendOverlayForNative } from './_native.js';

/**
 * Can this element be handed to Picture-in-Picture at all?
 *
 * Wrapped in try/catch on purpose: `document.pictureInPictureEnabled` is
 * a newer, less uniformly implemented property (standard desktop-Safari/
 * Chromium API; iOS Safari's OWN video PiP historically used a different,
 * non-standard surface entirely — see this file's header). A capability
 * PROBE must never itself be the thing that throws — this ran unguarded
 * during the recorded-clip shell's mount sequence
 * (mediaview/recorded-mode.js::_openRecordedVideoShell), which reveals
 * the lightbox modal only as its LAST statement with no surrounding
 * try/catch: any exception anywhere upstream, including here, silently
 * left the modal permanently hidden with no error shown — "the player
 * doesn't open at all" with nothing in the failure path to explain why.
 */
export function canPictureInPicture(videoEl) {
  try {
    if (!videoEl || videoEl.disablePictureInPicture) return false;
    return !!(
      typeof document !== 'undefined' &&
      document.pictureInPictureEnabled &&
      videoEl.requestPictureInPicture
    );
  } catch {
    return false;
  }
}

/** Is this element the page's current Picture-in-Picture window? Same
 *  never-throw contract as canPictureInPicture, same reason. */
export function isInPictureInPicture(videoEl) {
  try {
    return !!(
      videoEl &&
      typeof document !== 'undefined' &&
      document.pictureInPictureElement === videoEl
    );
  } catch {
    return false;
  }
}

/**
 * Watch a video element for Picture-in-Picture transitions. Simpler than
 * watchNativeFullscreen on purpose: PiP has exactly one entry API and its
 * events (`enterpictureinpicture` / `leavepictureinpicture`) fire
 * directly on the element for EVERY source of the transition — our own
 * button, the browser's native "PiP" context-menu entry, the floating
 * window's own close control — so there is no document-level
 * fullscreenElement-style polling branch to write, unlike fullscreen's
 * watcher. Not worth folding into watchNativeFullscreen: the event names,
 * the listener target (element-only, no document listeners) and the
 * absence of an active-element comparison all differ, so a single
 * parameterized function would need more branching than the two
 * functions save.
 *
 * @returns {Function} teardown
 */
export function watchPictureInPicture(videoEl, { onEnter, onExit } = {}) {
  if (!videoEl || !videoEl.addEventListener) return () => {};
  const fire = (fn) => {
    if (typeof fn === 'function') fn(videoEl);
  };
  const onPipEnter = () => fire(onEnter);
  const onPipExit = () => fire(onExit);
  videoEl.addEventListener('enterpictureinpicture', onPipEnter);
  videoEl.addEventListener('leavepictureinpicture', onPipExit);
  return () => {
    videoEl.removeEventListener('enterpictureinpicture', onPipEnter);
    videoEl.removeEventListener('leavepictureinpicture', onPipExit);
  };
}

/**
 * Request Picture-in-Picture for this element. Must be called from a
 * user gesture in every implementation this was checked against.
 *
 * @param {HTMLVideoElement} videoEl
 * @returns {boolean} whether the request was attempted.
 */
export function requestPip(videoEl) {
  if (!canPictureInPicture(videoEl)) return false;
  suspendOverlayForNative(videoEl);
  try {
    const res = videoEl.requestPictureInPicture();
    if (res && typeof res.catch === 'function') {
      res.catch(() => resumeOverlayAfterNative(videoEl));
    }
  } catch {
    resumeOverlayAfterNative(videoEl);
    return false;
  }
  return true;
}

/**
 * Toggle Picture-in-Picture for this element. PiP's exit call is
 * document-scoped, not element-scoped (`document.exitPictureInPicture`
 * exits WHATEVER is currently in PiP), so the "is it this element"
 * check happens first. Either direction only INITIATES the transition —
 * the overlay state settles through watchPictureInPicture's onEnter/
 * onExit, same division of responsibility as the fullscreen button vs.
 * watchNativeFullscreen.
 *
 * @returns {boolean} whether a transition was attempted.
 */
export function togglePictureInPicture(videoEl) {
  if (isInPictureInPicture(videoEl)) {
    if (typeof document === 'undefined' || typeof document.exitPictureInPicture !== 'function') {
      return false;
    }
    try {
      const res = document.exitPictureInPicture();
      if (res && typeof res.catch === 'function') res.catch(() => {});
    } catch {
      /* nothing to undo — the element's own state, whatever it settles
         to, is what watchPictureInPicture's onExit reacts to */
    }
    return true;
  }
  return requestPip(videoEl);
}
