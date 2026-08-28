// ─── weather/stats-chart/_multi.js ─────────────────────────────────────────
// Multi-EPISODE overlay chart for the Gewitter-Browser's compare view.
// Lives inside stats-chart/ deliberately: there is one chart package in
// this app, not two. It composes the same primitives the Wetterstatistik
// chart uses — buildLinePath for the geometry, buildValueAxis for the Y
// ticks, buildRelTicks for the X ticks, bindChartHover for the tooltip.
//
// ── Why the X axis is PEAK-aligned, and why that is not configurable ──
//
// t = 0 is each episode's `peak_at`. Two alternatives were considered
// and rejected; recording the reasoning here so a later refactor does
// not "helpfully" add wall-clock alignment back:
//
//   Wall-clock — the episodes are weeks or months apart. Overlaying
//   them on absolute time produces disjoint curves on a multi-month
//   axis. Non-starter.
//
//   Onset (`started_at`) — a threshold crossing. The threshold is a
//   fixed level, so a violent cell crosses it early in its own build-up
//   while a marginal one crosses near its own maximum: the origin is
//   shared but means something different per episode. Worse, time-to-
//   peak varies from minutes to over an hour, so onset-alignment
//   scatters the maxima and the one thing you came to compare never
//   lines up.
//
//   Peak — defined identically for every episode. Aligning there puts
//   the maxima on top of each other (relative severity is a direct
//   vertical read) and turns the difference in build-up and decay into
//   left/right asymmetry, which is the meteorologically interesting
//   part. The records' pre_min / post_min margins guarantee data on
//   both flanks, so it can never produce a one-sided curve.
//
// Sampling is the weather poll, whose interval is user-configurable.
// Nothing in here assumes a value for it: the hover tolerance is
// MEASURED off the samples that actually arrived (see hoverTolerance),
// so a 600 s poll, a coalesced job or a restart-shaped hole changes the
// number instead of quietly breaking the tooltip.

import { buildLinePath } from './_paths.js';
import { buildValueAxis } from './_axes.js';
import { buildRelTicks, fmtRelMinute } from './_ticks.js';
import { bindChartHover } from './_hover.js';
import { isWorse } from '../metric-direction.js';

// Default padding matches the Wetterstatistik chart. Below 600 px the
// right lane shrinks: `r: 72` exists to park seven threshold labels on
// the right edge, and compare draws exactly one neutral threshold — so
// 44 px is ample and buys 28 px of plot back on a 375 px iPhone.
const PAD_WIDE = { l: 42, r: 72, t: 12, b: 26 };
const PAD_NARROW = { l: 40, r: 44, t: 12, b: 26 };

// Synthetic timestamps let bindChartHover's wall-clock lookup serve the
// relative-minute axis unchanged — the mapping minMin…maxMin →
// tFirst…tLast is linear and identical to the one buildLinePath uses.
const _REL_EPOCH = Date.UTC(2000, 0, 1);
const _relToTs = (m) => new Date(_REL_EPOCH + m * 60_000).toISOString();

function _sizeOf(wrap) {
  const w = Math.round(wrap.clientWidth);
  const h = Math.round(wrap.clientHeight);
  return w > 0 && h > 0 ? { w, h } : null;
}

// Shared absolute value domain across every series, plus the relative-
// minute domain. The value floor is pinned to 0 for the non-negative
// storm metrics so two curves' heights are directly comparable rather
// than each being stretched to its own extent. Every threshold line is
// folded in so none of them is ever drawn off-plot.
function _domain(series, thresholds) {
  let minMin = Infinity,
    maxMin = -Infinity,
    lo = Infinity,
    hi = -Infinity;
  for (const s of series) {
    for (const [m, v] of s.points) {
      if (Number.isFinite(m)) {
        if (m < minMin) minMin = m;
        if (m > maxMin) maxMin = m;
      }
      if (Number.isFinite(v)) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  for (const t of thresholds) hi = Math.max(hi, t.value);
  lo = Math.min(0, lo);
  if (hi - lo < 1e-9) hi = lo + 1;
  return { minMin, maxMin, lo, hi };
}

// One path per episode, in the episode's slot colour. Colour means
// "which episode" in this view and nothing else — the class is carried
// by the legend glyph, the metric by the pills above the chart.
function _seriesPaths(series, dom, pad, cw, ch) {
  let svg = '';
  for (const s of series) {
    const samples = s.points.map(([, v]) => ({ values: { v } }));
    const meta = buildLinePath(samples, 'v', pad.l, pad.t, cw, ch, {
      lo: dom.lo,
      hi: dom.hi,
      xValues: s.points.map(([m]) => m),
      xLo: dom.minMin,
      xHi: dom.maxMin,
    });
    if (!meta) continue;
    svg += `<path d="${meta.path}" fill="none" stroke="${s.colour}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`;
  }
  return svg;
}

/**
 * The WORST value in a series, with the relative minute it occurred at.
 * `null` when the series carries no finite reading.
 *
 * Two things it is deliberately not:
 *
 *   Not `t = 0`. The x axis is anchored on the record's `peak_at`,
 *   which the backend derives from the thresholded fields only — a
 *   metric with no configured threshold (wind gusts) can never set it,
 *   so "the sample nearest t=0" is not that metric's extreme.
 *
 *   Not an argmax. `isWorse` decides the direction, because on an
 *   inverted metric the maximum is the CALMEST sample: an unconditional
 *   argmax planted the slot dot on the 24 000 m reading of a fog
 *   episode and skipped the 800 m one.
 */
export function seriesPeak(points, metric) {
  let best = null;
  for (const [m, v] of points || []) {
    if (!Number.isFinite(m) || !Number.isFinite(v)) continue;
    if (best === null || isWorse(metric, v, best.v)) best = { m, v };
  }
  return best;
}

// Redundant, non-colour identity channel: a filled dot carrying the slot
// number at each series' own worst reading. Survives colour-blindness
// and a greyscale screenshot. No dash patterns: they wreck the
// readability of a noisy storm curve.
function _peakDots(series, metric, dom, pad, cw, ch) {
  const span = dom.maxMin - dom.minMin || 1;
  let svg = '';
  for (const s of series) {
    const top = seriesPeak(s.points, metric);
    if (!top) continue;
    const x = pad.l + ((top.m - dom.minMin) / span) * cw;
    const y = pad.t + ch - ((top.v - dom.lo) / (dom.hi - dom.lo)) * ch;
    svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="7" fill="${s.colour}"/>`;
    svg += `<text x="${x.toFixed(1)}" y="${(y + 3.5).toFixed(1)}" text-anchor="middle" font-size="9" font-weight="700" fill="#0a0e14">${s.slot}</text>`;
  }
  return svg;
}

// The t=0 anchor: dashed vertical in the shared guide style plus a
// "Höhepunkt" caption above it, and ONE threshold line per distinct
// trigger level in the selection.
//
// Not one line for the whole chart: every record stamps the thresholds
// it was measured against, and the archive outlives the settings that
// produced it — so four curves can legitimately carry four different
// trigger levels. Drawing the first episode's line across all of them
// labels three curves with a threshold that was never theirs. When the
// levels differ, each line names the slots it belongs to.
//
// The lines are white at 45 %, NOT the metric colour — colour means
// "which episode" here, and one colour must mean one thing per view.
function _anchors(dom, thresholds, pad, cw, ch) {
  const span = dom.maxMin - dom.minMin || 1;
  const x = pad.l + ((0 - dom.minMin) / span) * cw;
  let svg =
    `<line x1="${x.toFixed(1)}" y1="${pad.t}" x2="${x.toFixed(1)}" y2="${pad.t + ch}" stroke="rgba(255,255,255,.35)" stroke-width="1" stroke-dasharray="3 3"/>` +
    `<text x="${x.toFixed(1)}" y="${pad.t - 2}" text-anchor="middle" font-size="10" fill="rgba(255,255,255,.55)">Höhepunkt</text>`;
  for (const t of thresholds) {
    const y = pad.t + ch - ((t.value - dom.lo) / (dom.hi - dom.lo)) * ch;
    svg += `<line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${(pad.l + cw).toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,.45)" stroke-width="1" stroke-dasharray="5 4"/>`;
    svg += `<text x="${(pad.l + cw + 4).toFixed(1)}" y="${(y + 3).toFixed(1)}" font-size="10" fill="rgba(255,255,255,.45)">${t.label}</text>`;
  }
  return svg;
}

// Union of every series' relative minutes — the hover grid. One tooltip
// column per distinct sampled minute across the selection.
function _hoverGrid(series) {
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

// Tooltip rows: "[1] ⚡ Hagelfront · 2400 J/kg", one per episode that
// spans the hovered minute. `fmtValue` is injected so this module stays
// free of German-formatting imports from the storms package (which
// imports this one — the dependency must not become a cycle).
function _hoverRows(series, fmtValue) {
  const tol = hoverTolerance(series);
  return (sample) =>
    series
      .map((s) => {
        const v = seriesReading(s.points, sample.rel, tol);
        if (v === undefined) return '';
        const txt = v === null ? '—' : fmtValue(v);
        return `<div class="ws-tt-row"><span class="ws-tt-dot" style="background:${s.colour}"></span><span class="ws-tt-lbl">${s.label}</span><span class="ws-tt-val">${txt}</span></div>`;
      })
      .filter(Boolean)
      .join('');
}

/**
 * Draw up to four peak-aligned episode curves for ONE metric.
 *
 * @param wrap   laid-out container element (its CSS pixel size is the viewBox)
 * @param series [{ slot:1-4, colour, label, points: [[relMinutes, value], …] }]
 * @param opts   { metric, unit, thresholds:[{value,label}], fmtValue, aria }
 */
export function renderEpisodeChart(wrap, series, opts = {}) {
  if (!wrap) return;
  const list = (series || []).filter((s) => s && s.points && s.points.length >= 2);
  if (!list.length) {
    wrap.innerHTML =
      '<div class="ws-stats-empty">Für diese Auswahl liegen keine Messwerte vor.</div>';
    return;
  }
  const size = _sizeOf(wrap);
  if (!size) return;
  const pad = size.w < 600 ? PAD_NARROW : PAD_WIDE;
  const cw = size.w - pad.l - pad.r;
  const ch = size.h - pad.t - pad.b;
  if (cw <= 0 || ch <= 0) return;
  // `> 0`, not just finite: a metric with no configured threshold
  // arrives as 0 from a `Number(null)` somewhere upstream, and a
  // "Schwelle" line along the axis floor is worse than no line.
  const thresholds = (opts.thresholds || []).filter(
    (t) => Number.isFinite(t?.value) && t.value > 0,
  );
  const dom = _domain(list, thresholds);
  if (!dom) return;
  const fmtValue = opts.fmtValue || ((v) => String(v));
  wrap.innerHTML = `
    <svg viewBox="0 0 ${size.w} ${size.h}" preserveAspectRatio="none" role="img" aria-label="${opts.aria || 'Gewitter-Vergleich'}">
      ${buildValueAxis({ lo: dom.lo, hi: dom.hi, unit: opts.unit || '', colour: 'rgba(255,255,255,.55)', pad, cw, ch })}
      ${buildRelTicks({ minMin: dom.minMin, maxMin: dom.maxMin, pad, cw, ch, vbH: size.h })}
      ${_anchors(dom, thresholds, pad, cw, ch)}
      ${_seriesPaths(list, dom, pad, cw, ch)}
      ${_peakDots(list, opts.metric, dom, pad, cw, ch)}
      <line class="ws-chart-guide" x1="0" y1="${pad.t}" x2="0" y2="${pad.t + ch}" stroke="rgba(255,255,255,.35)" stroke-width="1" stroke-dasharray="3 3" style="display:none;pointer-events:none"/>
      <rect class="ws-chart-hover-area" x="${pad.l}" y="${pad.t}" width="${cw}" height="${ch}" fill="transparent" style="pointer-events:all;cursor:crosshair"/>
    </svg>
    <div class="ws-chart-tooltip" hidden></div>
  `;
  const grid = _hoverGrid(list);
  bindChartHover(wrap, grid, [], pad, cw, size.w, null, {
    head: (s) => fmtRelMinute(s.rel),
    rows: _hoverRows(list, fmtValue),
  });
}
