// ─── vplayer/_keys.js ──────────────────────────────────────────────────────
// PURE. One key press → one intention. No DOM, no video element.
//
// „Zudem bitte auf Leertaste will ich pausieren und auf Pfeiltaste links,
// rechts, wenn ich will hin und her spulen können und Leertaste dann auch
// wieder play."
//
// WHY NOTHING HAPPENED BEFORE. _shell.js already swallowed Space, both
// arrows, Home and End — deliberately, so mediaview/keyboard.js's
// document-level back-navigation could not fire underneath an open
// player. But the only key its consumer ever acted on was Escape, so the
// rest were caught and dropped. The keys were not missing; they were
// being eaten in silence, which is the worse of the two failures because
// pressing harder looks like the same nothing.
//
// Kept pure and separate so every mapping below is a unit test rather
// than something to be discovered by pressing keys at a video.

/** Seconds a left/right arrow moves. The step a person expects from a
 *  video player, and small enough that two presses are still a scrub. */
export const STEP_S = 5;

/** …and with Shift, or with an up/down arrow: a coarser jump for a long
 *  clip, so crossing a 25-second recording is not five presses. */
export const STEP_BIG_S = 10;

/**
 * What a key means to a player.
 *
 * @param {string} key    KeyboardEvent.key
 * @param {object} [mod]  { shift }
 * @returns {{type: string, delta?: number, to?: number}|null}
 *   `null` for a key with no meaning here — the caller must then leave
 *   the event alone rather than swallow it.
 */
export function keyAction(key, mod = {}) {
  const big = mod.shift === true;
  switch (key) {
    case ' ':
    case 'Spacebar': // old Edge / Firefox ESR still report this name
      return { type: 'toggle' };
    case 'ArrowLeft':
      return { type: 'seek', delta: -(big ? STEP_BIG_S : STEP_S) };
    case 'ArrowRight':
      return { type: 'seek', delta: big ? STEP_BIG_S : STEP_S };
    // Up and down are the coarse pair. NOT volume: these clips are
    // watched for what moved in them, the audio is usually absent
    // entirely (record_audio is off on every camera here), and a volume
    // binding on a silent clip is a key that does nothing.
    case 'ArrowUp':
      return { type: 'seek', delta: STEP_BIG_S };
    case 'ArrowDown':
      return { type: 'seek', delta: -STEP_BIG_S };
    case 'Home':
      return { type: 'seekTo', to: 0 };
    case 'End':
      return { type: 'seekTo', to: Infinity };
    case 'Escape':
      return { type: 'close' };
    default:
      return null;
  }
}

/**
 * Apply an action's arithmetic to a position.
 *
 * Separate from `keyAction` because the clamp is the part that goes
 * wrong: seeking past the end of a clip leaves some browsers parked at
 * `duration` with `ended` set, which reads as "it played to the end" to
 * every other surface in this player.
 *
 * @param {object} action
 * @param {number} current   current time, seconds
 * @param {number} duration  clip length, seconds
 * @returns {number|null} the time to seek to, or null when not a seek
 */
export function seekTarget(action, current, duration) {
  if (!action) return null;
  const dur = Number.isFinite(duration) && duration > 0 ? duration : 0;
  const now = Number.isFinite(current) ? current : 0;
  let want;
  if (action.type === 'seek') want = now + action.delta;
  else if (action.type === 'seekTo') want = action.to;
  else return null;
  if (!dur) return 0;
  // A hair inside the end, never exactly on it — see above.
  return Math.min(Math.max(0, want), Math.max(0, dur - 0.05));
}
