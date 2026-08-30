// ─── mediaview/player/_pref.js ─────────────────────────────────────────────
// Which player the operator wants for a recorded clip:
//
//   'inline'  — our in-page player. Detection boxes, trails, the
//               per-class swimlane and the Aufnahme-Settings panel all
//               live in the DOM around the <video>, so they only exist
//               here. This is the default on every platform.
//   'native'  — the platform's own fullscreen player (AVPlayer on iOS).
//               Familiar and rock-solid, but every DOM overlay is gone:
//               a fullscreen <video> on iOS is a native view OUTSIDE the
//               web page, so there is nothing for the SVG layer to sit on.
//
// Persistence follows overlay-toggles.js's precedent exactly — one small
// localStorage key of our own, every access wrapped, no settings.json
// involvement. A private window (getItem/setItem throw) must degrade to
// the default, never break playback.

const _LS_KEY = 'tamspy.playerPref.v1';

export const PLAYER_INLINE = 'inline';
export const PLAYER_NATIVE = 'native';

/** @returns {'inline'|'native'} — 'inline' for anything unreadable. */
export function getPlayerPref() {
  try {
    return localStorage.getItem(_LS_KEY) === PLAYER_NATIVE ? PLAYER_NATIVE : PLAYER_INLINE;
  } catch {
    /* private mode / storage disabled — silent */
    return PLAYER_INLINE;
  }
}

export function setPlayerPref(value) {
  try {
    localStorage.setItem(_LS_KEY, value === PLAYER_NATIVE ? PLAYER_NATIVE : PLAYER_INLINE);
  } catch {
    /* quota / private mode — the session keeps working, just forgets */
  }
}

export function prefersNativePlayer() {
  return getPlayerPref() === PLAYER_NATIVE;
}
