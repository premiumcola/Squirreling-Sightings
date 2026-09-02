// ─── vplayer/_helpers.js ───────────────────────────────────────────────────
// PURE formatters for the player's readouts. No DOM, no state — so the
// whole set is provable under a bare `node --test`.
//
// WHAT IS REUSED RATHER THAN REWRITTEN. The m:ss playhead clock and the
// −remaining readout are core/clock-format.js's; this file imports them
// and re-exports them so a consumer inside the package has one place to
// look, and imports them SEPARATELY because a re-export alone would not
// put them in this module's own scope (spanLabel below calls one) — the
// repeat regression CLAUDE.md's refactor section documents.
//
// German relative age is NOT here. camedit/detection.js already exports
// _fmtRelativeAgeS and alerting.js already imports it cross-package, so
// it is the canonical one; it simply cannot be imported into a pure
// module today because its home publishes a `window.x` bridge at module
// scope. The panels that need it reach for it directly.

import { clockLabel } from '../core/clock-format.js';
export { clockLabel, remainingLabel } from '../core/clock-format.js';
// PLACEHOLDER and pctLabel moved to core/format.js when core/box-model.js
// came to need them — a shared module must not reach up into a feature
// package. Imported AND re-exported: this file's own formatters use
// PLACEHOLDER, and a re-export alone would not put it in local scope.
import { PLACEHOLDER } from '../core/format.js';
export { PLACEHOLDER, pctLabel } from '../core/format.js';

/**
 * A detection's time span within the clip, as `0:03–0:11`.
 *
 * Separator is U+2013 EN DASH with no surrounding spaces, matching the
 * span convention weather/_feed.js already renders for clock-of-day
 * ranges. A zero-length span (a single-sample track) collapses to the
 * one timestamp rather than printing `0:03–0:03`, because a lane that
 * exists for one frame should read as a moment, not a duration.
 *
 * @param {number} t0  start, seconds into the clip
 * @param {number} t1  end, seconds into the clip
 * @returns {string}
 */
export function spanLabel(t0, t1) {
  const a = Number.isFinite(t0) && t0 > 0 ? t0 : 0;
  const hasEnd = Number.isFinite(t1) && t1 > a;
  if (!Number.isFinite(t0)) return PLACEHOLDER;
  const from = clockLabel(a);
  return hasEnd ? `${from}–${clockLabel(t1)}` : from;
}

/**
 * A count with its German noun, singular or plural: `1 Objekt`,
 * `3 Objekte`. Keeps the "1 Objekte" bug out of every row that counts
 * something.
 *
 * @param {number} n
 * @param {string} one    singular noun
 * @param {string} many   plural noun
 * @returns {string}
 */
export function countLabel(n, one, many) {
  if (!Number.isFinite(n)) return PLACEHOLDER;
  const i = Math.max(0, Math.round(n));
  return `${i} ${i === 1 ? one : many}`;
}

/**
 * Any value that might be missing, rendered as a row value. This is the
 * degradation rule the whole package leans on: the backend's provenance
 * and per-detection attribution are landing concurrently, so a field
 * that is not there yet must read as a labelled placeholder, never as
 * the string "undefined" and never as a blank that looks like a value
 * of zero.
 *
 * @param {*} v
 * @param {string} [suffix]  unit appended when the value is present
 * @returns {string}
 */
export function valueOr(v, suffix = '') {
  if (v === null || v === undefined) return PLACEHOLDER;
  if (typeof v === 'number' && !Number.isFinite(v)) return PLACEHOLDER;
  const s = String(v).trim();
  if (!s) return PLACEHOLDER;
  return suffix ? `${s} ${suffix}` : s;
}

/**
 * Seconds as a short duration for a track's age: `4,2 s`, `1:05`.
 * Comma decimal separator, because the rest of the German UI uses one
 * (storms/_helpers.js::fmtNumberDe). Under a minute it stays in
 * seconds with one decimal, which is the resolution a tracker age is
 * actually interesting at; past that the clock form takes over.
 *
 * @param {number} seconds
 * @returns {string}
 */
export function ageLabel(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return PLACEHOLDER;
  if (seconds < 60) return `${seconds.toFixed(1).replace('.', ',')} s`;
  return clockLabel(seconds);
}
