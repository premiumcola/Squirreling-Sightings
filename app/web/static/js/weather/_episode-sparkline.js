// ─── weather/_episode-sparkline.js ─────────────────────────────────────
// Card-sized preview of one episode's own curve. Reuses the stats
// chart's own normalisation (buildLinePath) instead of a second curve
// math, so a card sparkline and the big detail chart always agree on
// what "the curve" looks like for the same samples.
//
// `curve_preview` is a bounded, single-field, timestamp-free slice the
// backend attaches to LIST-view records only (see
// weather_episodes/_preview.py::build_curve_preview) — the full
// multi-field `samples` array stays detail-only, so the archive's list
// endpoint cannot grow into a multi-megabyte payload as the (never
// rolling) episode ledger accumulates years of storms.

import { buildLinePath } from './stats-chart/_paths.js';

const W = 64;
const H = 20;

/**
 * SVG markup for one episode's sparkline, or '' when there is nothing
 * to draw. Covers every edge case explicitly rather than by accident:
 *   - no preview at all (legacy record, or one with an empty window)
 *   - a single-sample episode (buildLinePath needs >= 2 real points)
 *   - a preview whose one field is entirely null (a poll outage the
 *     whole episode long)
 */
export function episodeSparklineSvg(preview, color) {
  if (!preview || !Array.isArray(preview.values) || !preview.field) return '';
  const points = preview.values.map((v) => ({ values: { [preview.field]: v } }));
  const meta = buildLinePath(points, preview.field, 0, 0, W, H);
  if (!meta || !meta.path) return '';
  const stroke = color || 'currentColor';
  return (
    `<svg class="ws-ep-spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" ` +
    `preserveAspectRatio="none" aria-hidden="true">` +
    `<path d="${meta.path}" fill="none" stroke="${stroke}" stroke-width="1.6" ` +
    `stroke-linecap="round" stroke-linejoin="round"/></svg>`
  );
}
