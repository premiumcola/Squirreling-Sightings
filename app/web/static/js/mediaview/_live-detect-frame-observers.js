// ─── mediaview/_live-detect-frame-observers.js ─────────────────────────────
// Frame observers for the live poll loop. live-detect-poll.js's fan-out is
// bound to one player's renderers by direct import, which is fine for that
// player and leaves no way for a second surface to see a frame without
// either forking the loop or being wired into that list of calls. Neither
// is acceptable: the in-flight/no-abort contract, the adaptive cadence and
// cycle EMA, the CONTACT-vs-PACE watchdog split and the three 429/503
// branches are all fixes for reproduced regressions, and a second copy
// would have to reproduce every one of them.
//
// So: an observer list. With nothing subscribed this is a no-op, and every
// observer is called inside its own try/catch — a throwing consumer must
// never take down the poll loop, which is the thing keeping the live view
// alive.
//
// live-detect-poll.js re-exports onLiveFrame; vplayer/_data/live.js
// subscribes through that path.
const _frameObservers = new Set();

/**
 * Subscribe to every frame the live loop renders.
 *
 * @param {(data: object) => void} fn
 * @returns {() => void} unsubscribe
 */
export function onLiveFrame(fn) {
  if (typeof fn !== 'function') return () => {};
  _frameObservers.add(fn);
  return () => _frameObservers.delete(fn);
}

/**
 * Fan one frame out to every subscriber. A throwing observer is logged and
 * skipped; the remaining observers still see the frame.
 *
 * @param {object} data the backend's test-detection response
 */
export function _notifyFrameObservers(data) {
  for (const fn of _frameObservers) {
    try {
      fn(data);
    } catch (err) {
      console.warn('[sim-frame] observer threw', err);
    }
  }
}
