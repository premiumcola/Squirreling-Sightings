// ─── mediaview/_live-detect-cadence.js ─────────────────────────────────────
// Pure cadence arithmetic for the live poll loop, lifted verbatim out of
// live-detect-poll.js's _scheduleNext so the numbers can be exercised
// without a DOM, a session, a socket or a clock.
//
// Nothing here reads S, the session or Date.now() — every function is a
// total function of its arguments. The poll loop keeps the decisions
// (when to fire, what to stash on S.tickState); this module owns only the
// arithmetic behind them, together with the constants that arithmetic is
// written against. live-detect.js re-exports those constants, so every
// existing importer keeps its old import path.

// C73 · cadence floors. The original 1 Hz floor was set against the
// main-stream cost budget (2560×1440 frame copy + JPEG encode +
// inference ~600-1500 ms). With C41's sub-stream path the per-tick
// cost drops to ~250 ms, so 500 ms is a safe floor on that path.
// _cadenceForCycle picks the right floor based on the most recent
// diag.frame_src; the main_fallback path keeps the 1 Hz floor so an
// unhealthy / sub-disabled camera doesn't get hammered.
export const _TICK_FLOOR_SUB_MS = 500;
export const _TICK_FLOOR_MAIN_MS = 1000;
// Ceiling on the pause BETWEEN ticks. Scaled by the mode's inference
// count at the callsite (_scheduleNext): a 4 s ceiling is meaningless
// when one tick legitimately takes 10 s.
export const _TICK_MAX_MS = 4000;
export const _TICK_FACTOR = 1.2;

// gp384 — hold-time for bbox fade-out after the live tick goes
// empty. Each live bbox lingers for this long after its last sight,
// fading from full opacity down to zero. Without hold-time the
// bboxes vanish the instant the 1 Hz detector misses a frame —
// which on a fluttering bird or jittery score → "blinky" UX and
// the user assumes the renderer is broken.
// C84 · upper bound for the dynamic bbox hold-time. The hold is
// derived per-cycle from the EMA of recent tick wall-times:
//   hold_ms = clamp(2 * EMA, 800, _HOLD_MS_CEILING)
// so on a healthy sub-stream path (~500-700 ms ticks) the hold
// converges around ~1000-1400 ms — long enough to bridge a single
// missed tick, short enough that a moving subject's box doesn't
// ghost behind it.
export const _HOLD_MS_CEILING = 1500;
export const _HOLD_MS_FLOOR = 800;

/**
 * The three cadence numbers for the tick that just finished.
 *
 * C73 · the floor depends on which stream the LAST tick used. Sub-stream
 * ticks cost less, so 500 ms is the floor on that path. The fallback
 * floor of 1 s keeps the unhealthy-camera case from getting hammered.
 * Unknown (first tick) defaults to the safer 1 s floor — the second tick
 * will tighten if sub came back.
 *
 * P5 · the between-tick ceiling scales with what a tick costs. Clamping a
 * 10 s 3×3 cycle to a 4 s ceiling asks the camera for a new frame before
 * the previous answer is even back.
 *
 * @param {number} lastCycleMs wall-time of the cycle that just ended
 * @param {string} frameSrc    diag.frame_src of the last frame ('sub' | …)
 * @param {number} modeInvokes inferences the current mode costs per frame
 * @returns {{floor: number, cycleMs: number, delay: number}}
 */
export function _cadenceForCycle(lastCycleMs, frameSrc, modeInvokes) {
  const floor = frameSrc === 'sub' ? _TICK_FLOOR_SUB_MS : _TICK_FLOOR_MAIN_MS;
  const cycleMs = Number.isFinite(lastCycleMs) ? lastCycleMs : floor;
  const projected = Math.round(cycleMs * _TICK_FACTOR);
  const maxDelay = _TICK_MAX_MS * modeInvokes;
  const delay = Math.min(maxDelay, Math.max(floor, projected));
  return { floor, cycleMs, delay };
}

/**
 * C84 · EMA over recent cycle wall-times. The first observation seeds the
 * EMA so the hold isn't 0-initialised on the very first tick; subsequent
 * ticks pull the average toward the new cycle at factor 0.4 (a 5-tick
 * effective window).
 *
 * @param {number} prevEmaMs the running EMA, NaN before the first tick
 * @param {number} cycleMs   the cycle just observed
 * @returns {number} the new EMA
 */
export function _nextCycleEma(prevEmaMs, cycleMs) {
  if (!Number.isFinite(prevEmaMs)) return cycleMs;
  return 0.4 * cycleMs + 0.6 * prevEmaMs;
}

/**
 * C84 · hold = clamp(2 * EMA, 800, 1500). Two cycles of slack absorbs one
 * missed tick at the current cadence without lingering across multiple.
 *
 * @param {number} emaMs the running cycle EMA
 * @returns {number} bbox hold-time in ms
 */
export function _holdMsFromEma(emaMs) {
  return Math.min(_HOLD_MS_CEILING, Math.max(_HOLD_MS_FLOOR, 2 * emaMs));
}
