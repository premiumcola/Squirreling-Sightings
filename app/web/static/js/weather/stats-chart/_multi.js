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
// Sampling is the 5 min weather poll, so t=0 carries ±2.5 min of slop.
// The caller states that in the axis hint rather than pretending
// otherwise.

import { buildLinePath } from './_paths.js';
import { buildValueAxis } from './_axes.js';
import { buildRelTicks, fmtRelMinute } from './_ticks.js';
import { bindChartHover } from './_hover.js';

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
// than each being stretched to its own extent. `threshold` is folded in
// so its line is never drawn off-plot.
function _domain(series, threshold) {
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
  if (Number.isFinite(threshold)) hi = Math.max(hi, threshold);
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

// Redundant, non-colour identity channel: a filled dot carrying the slot
// number at each episode's own peak — which, by construction, sits on
// the t=0 guide. Survives colour-blindness and a greyscale screenshot,
// and doubles as visual reinforcement of the alignment anchor. No dash
// patterns: they wreck the readability of a noisy storm curve.
function _peakDots(series, dom, pad, cw, ch) {
  const span = dom.maxMin - dom.minMin || 1;
  const x = pad.l + ((0 - dom.minMin) / span) * cw;
  let svg = '';
  for (const s of series) {
    let best = null,
      bestD = Infinity;
    for (const [m, v] of s.points) {
      const d = Math.abs(m);
      if (Number.isFinite(v) && d < bestD) {
        bestD = d;
        best = v;
      }
    }
    if (best == null) continue;
    const y = pad.t + ch - ((best - dom.lo) / (dom.hi - dom.lo)) * ch;
    svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="7" fill="${s.colour}"/>`;
    svg += `<text x="${x.toFixed(1)}" y="${(y + 3.5).toFixed(1)}" text-anchor="middle" font-size="9" font-weight="700" fill="#0a0e14">${s.slot}</text>`;
  }
  return svg;
}

// The t=0 anchor: dashed vertical in the shared guide style plus a
// "Höhepunkt" caption above it, and the single neutral threshold line.
// The threshold is white at 45 %, NOT the metric colour — colour means
// "which episode" here, and one colour must mean one thing per view.
function _anchors(dom, threshold, pad, cw, ch) {
  const span = dom.maxMin - dom.minMin || 1;
  const x = pad.l + ((0 - dom.minMin) / span) * cw;
  let svg =
    `<line x1="${x.toFixed(1)}" y1="${pad.t}" x2="${x.toFixed(1)}" y2="${pad.t + ch}" stroke="rgba(255,255,255,.35)" stroke-width="1" stroke-dasharray="3 3"/>` +
    `<text x="${x.toFixed(1)}" y="${pad.t - 2}" text-anchor="middle" font-size="10" fill="rgba(255,255,255,.55)">Höhepunkt</text>`;
  if (Number.isFinite(threshold)) {
    const y = pad.t + ch - ((threshold - dom.lo) / (dom.hi - dom.lo)) * ch;
    svg += `<line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${(pad.l + cw).toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,.45)" stroke-width="1" stroke-dasharray="5 4"/>`;
    svg += `<text x="${(pad.l + cw + 4).toFixed(1)}" y="${(y + 3).toFixed(1)}" font-size="10" fill="rgba(255,255,255,.45)">Schwelle</text>`;
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

// Tooltip rows: "[1] ⚡ Hagelfront · 2400 J/kg", one per episode that has
// a reading at the hovered minute. `fmtValue` is injected so this module
// stays free of German-formatting imports from the storms package (which
// imports this one — the dependency must not become a cycle).
function _hoverRows(series, fmtValue) {
  return (sample) => {
    const rel = sample.rel;
    return series
      .map((s) => {
        const hit = s.points.find(([m]) => m === rel);
        if (!hit || !Number.isFinite(hit[1])) return '';
        return `<div class="ws-tt-row"><span class="ws-tt-dot" style="background:${s.colour}"></span><span class="ws-tt-lbl">${s.label}</span><span class="ws-tt-val">${fmtValue(hit[1])}</span></div>`;
      })
      .filter(Boolean)
      .join('');
  };
}

/**
 * Draw up to four peak-aligned episode curves for ONE metric.
 *
 * @param wrap   laid-out container element (its CSS pixel size is the viewBox)
 * @param series [{ slot:1-4, colour, label, points: [[relMinutes, value], …] }]
 * @param opts   { unit, threshold, fmtValue, aria }
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
  const threshold = Number.isFinite(opts.threshold) ? opts.threshold : NaN;
  const dom = _domain(list, threshold);
  if (!dom) return;
  const fmtValue = opts.fmtValue || ((v) => String(v));
  wrap.innerHTML = `
    <svg viewBox="0 0 ${size.w} ${size.h}" preserveAspectRatio="none" role="img" aria-label="${opts.aria || 'Gewitter-Vergleich'}">
      ${buildValueAxis({ lo: dom.lo, hi: dom.hi, unit: opts.unit || '', colour: 'rgba(255,255,255,.55)', pad, cw, ch })}
      ${buildRelTicks({ minMin: dom.minMin, maxMin: dom.maxMin, pad, cw, ch, vbH: size.h })}
      ${_anchors(dom, threshold, pad, cw, ch)}
      ${_seriesPaths(list, dom, pad, cw, ch)}
      ${_peakDots(list, dom, pad, cw, ch)}
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
