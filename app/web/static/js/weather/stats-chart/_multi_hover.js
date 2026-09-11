// ─── weather/stats-chart/_multi_hover.js ───────────────────────────────────
// Relative-minute hover math for the episode overlay chart: which sample
// of which series answers for the hovered minute, how wide "near" is,
// and the tooltip rows that come out of it.
//
// Split out of _multi.js rather than added to it. That file sat at 349
// of its 400 lines when the compare view had to carry several METRICS at
// once ("beliebige kurven parallel anzuwählen"), and CLAUDE.md's rule is
// to find the seam and extract BEFORE the edit, not to add the new code
// and split later. The seam is clean: everything here is pure —
// [relativeMinute, value] pairs in, numbers and HTML strings out — while
// what stayed behind is geometry and composition.
//
// _multi.js re-exports the four public helpers, so their import path
// never moved for anyone.
//
// Sampling is the weather poll, whose interval is user-configurable.
// Nothing in here assumes a value for it: the tolerance is MEASURED off
// the samples that actually arrived, so a 600 s poll, a coalesced job or
// a restart-shaped hole changes the number instead of quietly breaking
// the tooltip.

// Synthetic timestamps let bindChartHover's wall-clock lookup serve the
// relative-minute axis unchanged — the mapping minMin…maxMin →
// tFirst…tLast is linear and identical to the one buildLinePath uses.
const _REL_EPOCH = Date.UTC(2000, 0, 1);
const _relToTs = (m) => new Date(_REL_EPOCH + m * 60_000).toISOString();

/**
 * Union of every series' relative minutes — the hover grid. One tooltip
 * column per distinct sampled minute across the selection.
 *
 * With several metrics on the plot the same episode contributes one
 * series per metric, all on the same minutes, so the Set collapses them
 * back to one column: the tooltip still has one entry per moment in
 * time, not one per curve.
 */
/** How many readings the tooltip shows before it says „und N weitere".
 *  Eight fits the 220 px chart wrapper with its header and padding. */
export const HOVER_MAX_ROWS = 8;

export function episodeHoverGrid(series) {
  const set = new Set();
  for (const s of series) for (const [m] of s.points) if (Number.isFinite(m)) set.add(m);
  return [...set].sort((a, b) => a - b).map((m) => ({ ts: _relToTs(m), rel: m }));
}

/**
 * The sample of `points` closest to relative minute `rel`, within
 * `tol` minutes. `null` when the series has nothing that near.
 *
 * Exact matching is wrong here: the episodes are weeks apart and their
 * 5-minute polls are not phase-locked, so two series' relative-minute
 * sets almost never intersect and an `===` lookup shows one episode per
 * tooltip — the one thing a compare view must not do.
 */
export function nearestPoint(points, rel, tol) {
  let best = null,
    bestD = Infinity;
  for (const [m, v] of points || []) {
    if (!Number.isFinite(m) || !Number.isFinite(v)) continue;
    const d = Math.abs(m - rel);
    if (d <= tol && d < bestD) {
      bestD = d;
      best = [m, v];
    }
  }
  return best;
}

/**
 * Median gap between consecutive samples of one series, in minutes.
 * NaN for a series with fewer than two finite minutes.
 *
 * Median, not mean: a poll outage or a restart leaves a hole an order
 * of magnitude wider than the cadence, and a mean would let one such
 * hole inflate the tolerance until unrelated samples matched.
 */
export function medianStep(points) {
  const mins = (points || []).map(([m]) => m).filter((m) => Number.isFinite(m));
  mins.sort((a, b) => a - b);
  const gaps = [];
  for (let i = 1; i < mins.length; i++) if (mins[i] > mins[i - 1]) gaps.push(mins[i] - mins[i - 1]);
  if (!gaps.length) return NaN;
  gaps.sort((a, b) => a - b);
  const mid = gaps.length >> 1;
  return gaps.length % 2 ? gaps[mid] : (gaps[mid - 1] + gaps[mid]) / 2;
}

// Floor for the derived tolerance, and the fallback when nothing can be
// measured (one sample per series). Half of the shipped default poll
// interval — used ONLY when measurement is impossible.
const HOVER_TOLERANCE_FLOOR_MIN = 0.5;
const HOVER_TOLERANCE_FALLBACK_MIN = 2.5;

/**
 * Half of the widest per-series cadence in the selection.
 *
 * MEASURED, not assumed. The old constant 2.5 was "half a poll" against
 * a 300 s poll_interval that the operator can change: at 600 s every
 * tooltip regressed to one episode. Reading the cadence off the samples
 * that actually arrived also survives an episode recorded under a
 * different setting than the one next to it.
 *
 * Widest, not narrowest: a 10-min episode compared against a 5-min one
 * still has to resolve, and over-reaching by half a step never crosses
 * into another sample's territory.
 */
export function hoverTolerance(series) {
  let widest = 0;
  for (const s of series || []) {
    const step = medianStep(s.points);
    if (Number.isFinite(step) && step > widest) widest = step;
  }
  if (!widest) return HOVER_TOLERANCE_FALLBACK_MIN;
  return Math.max(HOVER_TOLERANCE_FLOOR_MIN, widest / 2);
}

/**
 * What one series has to say about relative minute `rel`:
 *
 *   {v}      — a reading within `tol`
 *   null     — inside the episode's own span, but no sample near: a
 *              GAP (failed poll, coalesced job, restart). The row is
 *              still drawn, with a dash, because silently dropping the
 *              episode is what made the tooltip look like the storm
 *              wasn't in the comparison at all.
 *   undefined — outside the episode's span entirely. No row: the
 *              episode genuinely does not reach this far from its peak.
 */
export function seriesReading(points, rel, tol) {
  const mins = (points || []).map(([m]) => m).filter((m) => Number.isFinite(m));
  if (!mins.length) return undefined;
  if (rel < Math.min(...mins) - tol || rel > Math.max(...mins) + tol) return undefined;
  const hit = nearestPoint(points, rel, tol);
  return hit ? hit[1] : null;
}

/**
 * Tooltip rows: "[1] ⚡ Hagelfront · Regen — 12,4 mm/h", one per series
 * that spans the hovered minute.
 *
 * With more than one metric on the plot this tooltip is no longer a
 * convenience — it is where the numbers LIVE. The Y axis drops its
 * labels as soon as the curves stop sharing a unit (see _multi_scale.js
 * for why), so `showMetric` is not decoration: without the metric name
 * on each row the reader has four numbers and no way to tell which
 * quantity any of them is.
 *
 * CAPPED, because the box it opens in cannot grow. Four episodes times
 * five metrics is twenty rows, and the chart wrapper is 220 px tall with
 * `overflow: hidden` (23-weather-3.css) — the rows past the edge would
 * simply be cut off, with nothing saying so. A stated remainder is the
 * honest version of a list that does not fit; the operator who needs row
 * eleven can switch a metric off, which is what the pills are for.
 *
 * `fmtValue` and `shortOf` are injected so this module stays free of
 * German-formatting imports from the storms package — which imports this
 * one, and the dependency must not become a cycle. `label` arrives
 * pre-escaped: it can be an operator-typed episode name.
 */
export function episodeHoverRows(series, { fmtValue, shortOf, showMetric }) {
  const tol = hoverTolerance(series);
  return (sample) => {
    const rows = [];
    for (const s of series) {
      const v = seriesReading(s.points, sample.rel, tol);
      if (v === undefined) continue;
      const txt = v === null ? '—' : fmtValue(v, s.metric);
      const name = showMetric ? `${s.label} · ${shortOf(s.metric)}` : s.label;
      rows.push(
        `<div class="ws-tt-row"><span class="ws-tt-dot" style="background:${s.colour}"></span><span class="ws-tt-lbl">${name}</span><span class="ws-tt-val">${txt}</span></div>`,
      );
    }
    const shown = rows.slice(0, HOVER_MAX_ROWS);
    const hidden = rows.length - shown.length;
    if (hidden > 0) shown.push(`<div class="ws-tt-more">+${hidden} weitere</div>`);
    return shown.join('');
  };
}
