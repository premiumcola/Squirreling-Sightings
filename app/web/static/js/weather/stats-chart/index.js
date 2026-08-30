// ─── weather/stats-chart/index.js ──────────────────────────────────────────
// R11 — extracted from stats.js, split into a package when it crossed the
// 400-line ceiling. Pure-SVG multi-line chart for the Wetterstatistik
// panel. Geometry lives in _paths.js, axis math + German formatters in
// _ticks.js, axis SVG in _axes.js, the tooltip in _hover.js. The
// threshold overlay is composed in from stats-thresholds.js after the
// base chart is laid out.

import { byId } from '../../core/dom.js';
import {
  WEATHER_STATS_PALETTE,
  _WS_FIELD_ORDER,
  _wsStatsState,
  wsVisibleFields,
  wsLineEmphasis,
  onWeatherChartRangeSelect,
} from '../stats.js';
import { isZoomActive, zoomedSamples } from '../_zoom.js';
import { _buildThresholdSvg } from '../stats-thresholds.js';
import { buildLinePath } from './_paths.js';
import { buildXTicks, buildYAxis } from './_axes.js';
import { bindChartHover } from './_hover.js';

const PAD = { l: 42, r: 72, t: 12, b: 26 };

// Exported so a consumer can map its own timestamps onto a rendered
// chart's plot area (the storm detail view paints a footage band across
// it). Re-deriving these four numbers at the callsite would be a second
// copy of the geometry, which is exactly what drifts.
export const STATS_CHART_PAD = PAD;

// The viewBox is authored at the wrapper's own CSS-pixel size, so one
// user unit is one CSS pixel and the scale is exactly 1:1.
//
// It used to be a fixed 600 × 220 box stretched to fill the wrapper with
// preserveAspectRatio="none", above a comment claiming "the visual scale
// change is sub-pixel and not noticeable". That was wrong by a factor of
// two: the wrapper is width:100% (≈1300 px on a desktop) at a fixed
// height:220px, so X scaled ≈2.14× while Y scaled ≈0.97×. Every glyph
// came out 2.2× wider than tall — which is what "unscharfe, unschöne"
// axis labels and a "pixelige" curve actually were. Not a rasterisation
// problem at all; SVG text is vector and stays sharp under UNIFORM
// scaling. It was pure geometric distortion.
//
// preserveAspectRatio stays "none" but is now a no-op: viewBox and
// element share one aspect ratio by construction, so it only guarantees
// an exact fill against sub-pixel rounding.
function _sizeOf(wrap) {
  const w = Math.round(wrap.clientWidth);
  const h = Math.round(wrap.clientHeight);
  if (w > 0 && h > 0) return { w, h };
  return null;
}

// Re-render on resize so the 1:1 mapping survives a window drag or an
// orientation change. Guarded on the integer width/height actually
// changing: innerHTML replacement inside the wrapper does not resize the
// wrapper, but the guard makes that independent of layout quirks rather
// than relying on it.
function _observe(wrap) {
  if (wrap._wsChartObserver) return;
  let last = '';
  const ro = new ResizeObserver(() => {
    const size = _sizeOf(wrap);
    const key = size ? `${size.w}x${size.h}` : '';
    if (key === last) return;
    last = key;
    if (size) renderWeatherStatsChart();
  });
  ro.observe(wrap);
  wrap._wsChartObserver = ro;
}

// Optional labelled vertical markers at absolute timestamps — the storm
// detail chart pins Beginn / Höhepunkt / Ende onto the episode's own
// verlauf. Off by default, so the Wetter panel is unaffected.
function _markersSvg(markers, samples, pad, cw, ch) {
  const tFirst = new Date(samples[0]?.ts).getTime();
  const tLast = new Date(samples[samples.length - 1]?.ts).getTime();
  const span = tLast - tFirst;
  if (!Number.isFinite(span) || span <= 0) return '';
  let svg = '';
  for (const m of markers) {
    const t = new Date(m.ts).getTime();
    if (!Number.isFinite(t) || t < tFirst || t > tLast) continue;
    const x = pad.l + ((t - tFirst) / span) * cw;
    const colour = m.colour || 'rgba(255,255,255,.45)';
    svg += `<line x1="${x.toFixed(1)}" y1="${pad.t}" x2="${x.toFixed(1)}" y2="${pad.t + ch}" stroke="${colour}" stroke-width="1" stroke-dasharray="4 3"/>`;
    if (m.label) {
      svg += `<text x="${x.toFixed(1)}" y="${pad.t - 2}" text-anchor="middle" font-size="10" fill="${colour}">${m.label}</text>`;
    }
  }
  return svg;
}

// Body of the chart: axes + lines + threshold overlay, as one SVG
// string. Split out of renderStatsChartInto purely to keep both under
// the 60-line function ceiling.
function _buildChartSvg({ samples, data, isolated, fields, hours, geo, markers }) {
  const { VB_W, VB_H, cw, ch } = geo;
  const tickSvg = buildXTicks({ samples, pad: PAD, cw, ch, vbH: VB_H, hours });
  // Lines — collect per-field meta so the threshold pass can renormalise
  // each tick against the same {lo, hi} the line was drawn against.
  let linesSvg = '';
  const lineMetas = {};
  // Hidden fields never reach `fields` at all (wsVisibleFields already
  // filtered them) — nothing here dims a curve by omission any more.
  // What remains competes for attention by how much it actually moved
  // in this window, via wsLineEmphasis — UNLESS exactly one field is on
  // screen, where there is nothing to compete with and it always reads
  // clearly.
  for (const key of fields) {
    const meta = buildLinePath(samples, key, PAD.l, PAD.t, cw, ch);
    if (!meta) continue;
    lineMetas[key] = meta;
    const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
    const { width, opacity } = isolated
      ? { width: 2.2, opacity: 1 }
      : wsLineEmphasis(key, meta.lo, meta.hi);
    linesSvg += `<path d="${meta.path}" fill="none" stroke="${colour}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" opacity="${opacity}"/>`;
  }
  const yAxisSvg = buildYAxis({ isolated, lineMetas, data, pad: PAD, cw, ch });
  // Threshold overlay — delegated to stats-thresholds.js so this file
  // stays focused on geometry.
  const { thresholdSvg, noThresholdHint } = _buildThresholdSvg({
    isolated,
    data,
    lineMetas,
    pad: PAD,
    cw,
    ch,
  });
  const svg = `
    <svg viewBox="0 0 ${VB_W} ${VB_H}" preserveAspectRatio="none" role="img" aria-label="Wetterverlauf">
      ${yAxisSvg}
      ${tickSvg}
      ${linesSvg}
      ${thresholdSvg}
      ${markers && markers.length ? _markersSvg(markers, samples, PAD, cw, ch) : ''}
      <line class="ws-chart-guide" x1="0" y1="${PAD.t}" x2="0" y2="${PAD.t + ch}" stroke="rgba(255,255,255,.35)" stroke-width="1" stroke-dasharray="3 3" style="display:none;pointer-events:none"/>
      <rect class="ws-chart-brush" x="0" y="${PAD.t}" width="0" height="${ch}" fill="rgba(127,174,201,.22)" style="display:none;pointer-events:none"/>
      <rect class="ws-chart-hover-area" x="${PAD.l}" y="${PAD.t}" width="${cw}" height="${ch}" fill="transparent" style="pointer-events:all;cursor:crosshair"/>
    </svg>`;
  return svg + noThresholdHint + '<div class="ws-chart-tooltip" hidden></div>';
}

// Render a history payload into ANY wrapper. Extracted from
// renderWeatherStatsChart, which was hard-wired to
// #weatherStatsChartWrap + the module-global _wsStatsState — the storm
// detail view needs the same chart with its OWN isolated field, since
// the global one belongs to the Wetter panel above it.
//
// `opts.isolated` — field key to draw alone (null = every line).
// `opts.hours`    — window size, only used for the legacy x-tick fallback.
// `opts.markers`  — [{ ts, label, colour }] vertical guides at absolute times.
// `opts.hover`    — forwarded to bindChartHover (head / rows / onGuide).
export function renderStatsChartInto(wrap, data, opts = {}) {
  if (!wrap) return;
  const samples = data?.samples || [];
  if (samples.length < 2) {
    wrap.innerHTML =
      '<div class="ws-stats-empty">Noch zu wenige Messpunkte — der Verlauf füllt sich alle 5 min.</div>';
    return;
  }
  // Unmeasurable wrapper (display:none, not laid out yet). Drawing into
  // FALLBACK here would reintroduce exactly the stretch this package
  // exists to remove, so leave the DOM alone; the observer re-renders as
  // soon as the panel has a size.
  const size = _sizeOf(wrap);
  if (!size) return;
  const geo = {
    VB_W: size.w,
    VB_H: size.h,
    cw: size.w - PAD.l - PAD.r,
    ch: size.h - PAD.t - PAD.b,
  };
  if (geo.cw <= 0 || geo.ch <= 0) return;
  const isolated = opts.isolated || null;
  // `opts.fields` lets a caller (the Wetter panel) draw a hand-picked
  // subset; storms/_detail.js never passes it, so it keeps its original
  // "isolated one field, else every field" behaviour unchanged.
  const fields = opts.fields || (isolated ? [isolated] : _WS_FIELD_ORDER);
  wrap.innerHTML = _buildChartSvg({
    samples,
    data,
    isolated,
    fields,
    hours: opts.hours || 24,
    geo,
    markers: opts.markers,
  });
  bindChartHover(wrap, samples, fields, PAD, geo.cw, geo.VB_W, data, opts.hover || {});
}

// A custom drag-zoom (weather/_zoom.js) is a client-side slice of the
// SAME fetched payload, never a second fetch: the history buffer has no
// downsampling (see routes/weather.py::api_weather_history's docstring
// and the service's own history() — every sample from the ring buffer
// at its native poll cadence, regardless of `hours`), so a wide preset's
// own data already carries full resolution for any narrower range
// inside it.
export function renderWeatherStatsChart() {
  const wrap = byId('weatherStatsChartWrap');
  if (!wrap) return;
  _observe(wrap);
  const data = _wsStatsState.data;
  const viewData = isZoomActive() ? { ...data, samples: zoomedSamples(data?.samples) } : data;
  renderStatsChartInto(wrap, viewData, {
    isolated: _wsStatsState.isolated,
    fields: wsVisibleFields(),
    hours: _wsStatsState.hours || 24,
    hover: { onRangeSelect: onWeatherChartRangeSelect },
  });
}
