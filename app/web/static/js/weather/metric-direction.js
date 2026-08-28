// ─── weather/metric-direction.js ───────────────────────────────────────────
// Which way is "worse" for a weather metric — the ONE place that knows.
//
// Mirror of FIELD_DIRECTION in app/app/weather_episodes/_consts.py, and
// of the `worse()` helper the backend's peak picker uses (_build.py).
//
// Why its own module rather than a constant inside storms/_state.js:
// the direction was already known in three places (the backend's peak
// picker, the backend's severity score, the frontend's severity ratio)
// and consulted in only some of them, so the compare chart planted its
// peak dot on the CLEAREST moment of a fog and the comparison table
// bolded the episode with the BEST visibility as the worst one. Two
// sites that agree by convention drift; one helper that every consumer
// calls cannot.
//
// It lives under weather/ rather than storms/ because direction is a
// property of the METRIC, not of the archive browser — and because the
// chart package must be able to ask without importing the storms
// package back (that would close a cycle).

/**
 * Metrics whose LOW reading is the alarm.
 *
 * Only `visibility` today: fog is configured as a ceiling (`vis_max_m`),
 * so 800 m is a worse reading than 24 000 m and the episode's stored
 * "peak" is its MINIMUM.
 */
export const METRICS_INVERTED = new Set(['visibility']);

export function isMetricInverted(key) {
  return METRICS_INVERTED.has(key);
}

/**
 * True when `value` sits further on the alarm side than `current`.
 * Bit-for-bit mirror of `_build.worse()`.
 *
 * A `null` / absent metric key means "higher is worse", which is right
 * for every non-metric quantity that reuses this (duration, intensity).
 */
export function isWorse(key, value, current) {
  return isMetricInverted(key) ? value < current : value > current;
}

/**
 * The worst finite value in `values`, or NaN when there is none.
 * Ties return that one value, so every tied cell can be marked.
 */
export function worstValue(key, values) {
  let best = NaN;
  for (const raw of values || []) {
    const v = Number(raw);
    if (!Number.isFinite(v)) continue;
    if (!Number.isFinite(best) || isWorse(key, v, best)) best = v;
  }
  return best;
}
