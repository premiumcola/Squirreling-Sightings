// ─── weather/stats-chart/_multi.js ─────────────────────────────────────────
// Multi-EPISODE, multi-METRIC overlay chart for the Gewitter-Browser's
// compare view. Lives inside stats-chart/ deliberately: there is one
// chart package in this app, not two. It composes the same primitives
// the Wetterstatistik chart uses — buildLinePath for the geometry,
// buildValueAxis / buildYAxis for the Y ticks, buildRelTicks for the X
// ticks, bindChartHover for the tooltip.
//
// Two siblings carry the parts that outgrew this file:
//   _multi_scale.js — the per-metric value bands + the direct end
//                     labels, and the record of why the Y axis goes
//                     unlabelled once two units share the plot.
//   _multi_hover.js — the relative-minute hover math and tooltip rows.
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
// The X SPAN is not normalised either. Every series is mapped through
// the one union domain minMin…maxMin, so a 40-minute squall occupies a
// third of the width next to a two-hour front: „bitte achte beim
// vergleich auch auf die zeitliche ausdehnung die muss vergleichbar
// bleiben also kein verzug des zeitrahmens!"

import { buildLinePath } from './_paths.js';
import { buildValueAxis, buildYAxis } from './_axes.js';
import { statsChartPad, axisTickLabels } from './_pad.js';
import { buildRelTicks, fmtRelMinute } from './_ticks.js';
import { bindChartHover } from './_hover.js';
import { isWorse } from '../metric-direction.js';
import { valueBands, bandY, domainX, metricEndLabels } from './_multi_scale.js';
import { episodeHoverGrid, episodeHoverRows } from './_multi_hover.js';

// The four pure hover helpers moved to _multi_hover.js; re-exported here
// so their import path never changed for anyone. (This file's own uses
// go through the explicit imports above — a re-export does NOT put a
// symbol into local scope.)
export { nearestPoint, medianStep, hoverTolerance, seriesReading } from './_multi_hover.js';

function _sizeOf(wrap) {
  const w = Math.round(wrap.clientWidth);
  const h = Math.round(wrap.clientHeight);
  return w > 0 && h > 0 ? { w, h } : null;
}

// One path per series, drawn against ITS METRIC's band — shared by every
// episode on that metric, so two rain curves stay directly comparable
// while a gust curve next to them gets its own scale (_multi_scale.js
// carries the full reasoning).
//
// Colour means "which episode" in this view and nothing else. The class
// is carried by the legend glyph, the metric by the pills above the
// chart and by the direct end label on the curve itself. Explicitly NOT
// dash patterns: they wreck the readability of a noisy storm curve.
function _seriesPaths(series, dom, geo) {
  const { pad, cw, ch } = geo;
  let svg = '';
  for (const s of series) {
    const band = dom.bands[s.metric];
    if (!band) continue;
    const samples = s.points.map(([, v]) => ({ values: { v } }));
    const meta = buildLinePath(samples, 'v', pad.l, pad.t, cw, ch, {
      lo: band.lo,
      hi: band.hi,
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
// and a greyscale screenshot.
function _peakDots(series, dom, geo) {
  const { pad, cw, ch } = geo;
  let svg = '';
  for (const s of series) {
    const band = dom.bands[s.metric];
    const top = band ? seriesPeak(s.points, s.metric) : null;
    if (!top) continue;
    const x = domainX(dom, top.m, pad, cw);
    const y = bandY(band, top.v, pad, ch);
    svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="7" fill="${s.colour}"/>`;
    svg += `<text x="${x.toFixed(1)}" y="${(y + 3.5).toFixed(1)}" text-anchor="middle" font-size="9" font-weight="700" fill="#0a0e14">${s.slot}</text>`;
  }
  return svg;
}

// The t=0 anchor: dashed vertical in the shared guide style plus a
// "Höhepunkt" caption above it, and ONE threshold line per distinct
// trigger level in the selection, normalised on its OWN metric's band.
//
// Not one line for the whole chart: every record stamps the thresholds
// it was measured against, and the archive outlives the settings that
// produced it — so four curves can legitimately carry four different
// trigger levels. Drawing the first episode's line across all of them
// labels three curves with a threshold that was never theirs. When the
// levels differ, each line names the slots it belongs to; when several
// metrics share the plot, it names the metric too (storms/_compare.js
// builds those labels).
//
// The lines are white at 45 %, NOT the metric colour — colour means
// "which episode" here, and one colour must mean one thing per view.
function _anchors(dom, thresholds, geo) {
  const { pad, cw, ch } = geo;
  const x = domainX(dom, 0, pad, cw);
  let svg =
    `<line x1="${x.toFixed(1)}" y1="${pad.t}" x2="${x.toFixed(1)}" y2="${pad.t + ch}" stroke="rgba(255,255,255,.35)" stroke-width="1" stroke-dasharray="3 3"/>` +
    `<text x="${x.toFixed(1)}" y="${pad.t - 2}" text-anchor="middle" font-size="10" fill="rgba(255,255,255,.55)">Höhepunkt</text>`;
  for (const t of thresholds) {
    const band = dom.bands[t.metric];
    if (!band) continue;
    const y = bandY(band, t.value, pad, ch);
    svg += `<line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${(pad.l + cw).toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,.45)" stroke-width="1" stroke-dasharray="5 4"/>`;
    svg += `<text x="${(pad.l + cw + 4).toFixed(1)}" y="${(y + 3).toFixed(1)}" font-size="10" fill="rgba(255,255,255,.45)">${t.label}</text>`;
  }
  return svg;
}

// Rails are measured against the labels this render will actually draw
// (stats-chart/_pad.js). Labelled value ticks exist only while ONE
// metric is on the plot; with several, buildYAxis' unlabelled-gridline
// branch draws nothing in the left rail, so nothing is reserved for it.
function _geometry(size, dom, metrics, thresholds, opts) {
  const band = metrics.length === 1 ? dom.bands[metrics[0]] : null;
  const unit = band ? opts.unitOf(metrics[0]) : '';
  const pad = statsChartPad({
    width: size.w,
    yLabels: band ? axisTickLabels(band.lo, band.hi, unit) : [],
    edgeLabels: thresholds.map((t) => t.label),
  });
  const cw = size.w - pad.l - pad.r;
  const ch = size.h - pad.t - pad.b;
  if (cw <= 0 || ch <= 0) return null;
  return { pad, cw, ch, band, unit };
}

// One labelled value axis while a single metric owns the plot; four
// plain gridlines as soon as two units share it. Same two modes, and the
// same reasoning, as buildYAxis' own isolated / all-lines split — which
// is why the second branch calls it rather than re-drawing gridlines.
function _axisSvg(geo) {
  const { band, unit, pad, cw, ch } = geo;
  if (band) {
    return buildValueAxis({
      lo: band.lo,
      hi: band.hi,
      unit,
      colour: 'rgba(255,255,255,.55)',
      pad,
      cw,
      ch,
    });
  }
  return buildYAxis({ isolated: null, lineMetas: {}, data: null, pad, cw, ch });
}

function _chartSvg(list, dom, geo, metrics, thresholds, opts, size) {
  const { pad, cw, ch } = geo;
  return `
    <svg viewBox="0 0 ${size.w} ${size.h}" preserveAspectRatio="none" role="img" aria-label="${opts.aria || 'Gewitter-Vergleich'}">
      ${_axisSvg(geo)}
      ${buildRelTicks({ minMin: dom.minMin, maxMin: dom.maxMin, pad, cw, ch, vbH: size.h })}
      ${_anchors(dom, thresholds, geo)}
      ${_seriesPaths(list, dom, geo)}
      ${_peakDots(list, dom, geo)}
      ${metrics.length > 1 ? metricEndLabels(list, dom, geo, opts.shortOf) : ''}
      <line class="ws-chart-guide" x1="0" y1="${pad.t}" x2="0" y2="${pad.t + ch}" stroke="rgba(255,255,255,.35)" stroke-width="1" stroke-dasharray="3 3" style="display:none;pointer-events:none"/>
      <rect class="ws-chart-hover-area" x="${pad.l}" y="${pad.t}" width="${cw}" height="${ch}" fill="transparent" style="pointer-events:all;cursor:crosshair"/>
    </svg>
    <div class="ws-chart-tooltip" hidden></div>
  `;
}

// Tooltip rows grouped by metric: with several on the plot the reader is
// comparing episodes WITHIN a metric, so those rows have to sit
// together rather than interleave by episode.
function _byMetric(list, metrics) {
  return [...list].sort(
    (a, b) => metrics.indexOf(a.metric) - metrics.indexOf(b.metric) || a.slot - b.slot,
  );
}

const _IDENTITY = (v) => String(v);

/**
 * Draw peak-aligned episode curves — up to four episodes × any number of
 * metrics, each metric on its own shared band.
 *
 * @param wrap   laid-out container element (its CSS pixel size is the viewBox)
 * @param series [{ slot:1-4, colour, label, metric, points: [[relMinutes, value], …] }]
 *               `label` must arrive pre-escaped; it can be an
 *               operator-typed episode name.
 * @param opts   { metrics, unitOf, shortOf, fmtValue, thresholds, aria }
 *               `metrics` fixes the draw / legend order and defaults to
 *               the distinct metrics present in `series`; `thresholds`
 *               entries are [{ value, label, metric }].
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
  // `> 0`, not just finite: a metric with no configured threshold
  // arrives as 0 from a `Number(null)` somewhere upstream, and a
  // "Schwelle" line along the axis floor is worse than no line.
  const thresholds = (opts.thresholds || []).filter(
    (t) => Number.isFinite(t?.value) && t.value > 0,
  );
  const dom = valueBands(list, thresholds);
  if (!dom) return;
  const metrics = opts.metrics?.length ? opts.metrics : [...new Set(list.map((s) => s.metric))];
  const o = {
    aria: opts.aria,
    unitOf: opts.unitOf || (() => ''),
    shortOf: opts.shortOf || ((m) => m),
    fmtValue: opts.fmtValue || _IDENTITY,
  };
  const geo = _geometry(size, dom, metrics, thresholds, o);
  if (!geo) return;
  wrap.innerHTML = _chartSvg(list, dom, geo, metrics, thresholds, o, size);
  bindChartHover(wrap, episodeHoverGrid(list), [], geo.pad, geo.cw, size.w, null, {
    head: (s) => fmtRelMinute(s.rel),
    rows: episodeHoverRows(_byMetric(list, metrics), { ...o, showMetric: metrics.length > 1 }),
  });
}
