// ─── weather/stats-chart/index.js ──────────────────────────────────────────
// R11 — extracted from stats.js, split into a package when it crossed the
// 400-line ceiling. Pure-SVG multi-line chart for the Wetterstatistik
// panel. Geometry lives in _paths.js, axis math + German formatters in
// _ticks.js, axis SVG in _axes.js, the tooltip in _hover.js. The
// threshold overlay is composed in from stats-thresholds.js after the
// base chart is laid out.

import { byId } from '../../core/dom.js';
import { WEATHER_STATS_PALETTE, _WS_FIELD_ORDER, _wsStatsState } from '../stats.js';
import { _buildThresholdSvg } from '../stats-thresholds.js';
import { buildLinePath } from './_paths.js';
import { buildXTicks, buildYAxis } from './_axes.js';
import { bindChartHover } from './_hover.js';

const PAD = { l: 42, r: 72, t: 12, b: 26 };

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

export function renderWeatherStatsChart() {
  const wrap = byId('weatherStatsChartWrap');
  if (!wrap) return;
  _observe(wrap);
  const data = _wsStatsState.data;
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
  const VB_W = size.w;
  const VB_H = size.h;
  const cw = VB_W - PAD.l - PAD.r;
  const ch = VB_H - PAD.t - PAD.b;
  if (cw <= 0 || ch <= 0) return;
  const isolated = _wsStatsState.isolated;
  const fields = isolated ? [isolated] : _WS_FIELD_ORDER;
  const hours = _wsStatsState.hours || 24;

  const tickSvg = buildXTicks({ samples, pad: PAD, cw, ch, vbH: VB_H, hours });

  // Lines — collect per-field meta so the threshold pass can renormalise
  // each tick against the same {lo, hi} the line was drawn against.
  let linesSvg = '';
  const lineMetas = {};
  for (const key of fields) {
    const meta = buildLinePath(samples, key, PAD.l, PAD.t, cw, ch);
    if (!meta) continue;
    lineMetas[key] = meta;
    const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
    const opacity = isolated && isolated !== key ? 0.15 : 1;
    linesSvg += `<path d="${meta.path}" fill="none" stroke="${colour}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" opacity="${opacity}"/>`;
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

  wrap.innerHTML = `
    <svg viewBox="0 0 ${VB_W} ${VB_H}" preserveAspectRatio="none" role="img" aria-label="Wetterverlauf">
      ${yAxisSvg}
      ${tickSvg}
      ${linesSvg}
      ${thresholdSvg}
      <line class="ws-chart-guide" x1="0" y1="${PAD.t}" x2="0" y2="${PAD.t + ch}" stroke="rgba(255,255,255,.35)" stroke-width="1" stroke-dasharray="3 3" style="display:none;pointer-events:none"/>
      <rect class="ws-chart-hover-area" x="${PAD.l}" y="${PAD.t}" width="${cw}" height="${ch}" fill="transparent" style="pointer-events:all;cursor:crosshair"/>
    </svg>
    ${noThresholdHint}
    <div class="ws-chart-tooltip" hidden></div>
  `;
  bindChartHover(wrap, samples, fields, PAD, cw, VB_W, data);
}
