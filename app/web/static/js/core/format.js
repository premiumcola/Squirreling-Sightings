// ─── core/format.js ────────────────────────────────────────────────────────
// The two formatting primitives that more than one package needs: the
// placeholder every missing value renders as, and the percent form the
// whole German chrome uses.
//
// They live in core rather than beside their first caller because
// core/box-model.js needs them, and a shared module must never reach
// up into a feature package for a helper.

/**
 * What every formatter prints instead of "undefined", "NaN", or a
 * blank that a reader would mistake for a real zero.
 */
export const PLACEHOLDER = '—';

/**
 * A model score as a percent: `0.87` → `87 %`.
 *
 * One convention, with a space before the sign — the German
 * typographic form the rest of this app's chrome already uses.
 *
 * Accepts either a 0..1 fraction or an already-scaled percent, because
 * both shapes reach the UI: tracks.json stores fractions, some status
 * payloads report whole percents. Anything above 1 is taken as scaled.
 *
 * @param {number|string} v
 * @returns {string}
 */
export function pctLabel(v) {
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (!Number.isFinite(n)) return PLACEHOLDER;
  const scaled = n > 1 ? n : n * 100;
  return `${Math.round(scaled)} %`;
}
