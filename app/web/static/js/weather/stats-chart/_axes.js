// ─── weather/stats-chart/_axes.js ──────────────────────────────────────────
// Axis + gridline SVG builders. Take laid-out geometry, return strings.

import { WEATHER_STATS_PALETTE } from '../stats.js';
import { fmtTick, fmtTimeTick, pickTimeStep, anchorTickStart, niceAxisTicks } from './_ticks.js';

const GRID_STROKE = 'rgba(255,255,255,.07)';
const AXIS_TEXT = 'rgba(255,255,255,.55)';

function gridLine(pad, cw, y) {
  return `<line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${(pad.l + cw).toFixed(1)}" y2="${y.toFixed(1)}" stroke="${GRID_STROKE}" stroke-width="1"/>`;
}

// X-axis. Picks a step from the ladder so the visible tick count stays
// close to 6 regardless of window size; format adapts to step magnitude
// (HH:MM / dd. MMM / MMM YY). Falls back to the legacy index-based
// 6-tick scheme when timestamps don't parse.
export function buildXTicks({ samples, pad, cw, ch, vbH, hours }) {
  const tFirst = new Date(samples[0]?.ts).getTime();
  const tLast = new Date(samples[samples.length - 1]?.ts).getTime();
  const tSpan = tLast - tFirst;
  const baseY = (vbH - 8).toFixed(1);
  // Tick count follows the available width. The viewBox is now authored
  // at true CSS-pixel size, so a fixed target of 6 would put six labels
  // on the ~226 px plot an iPhone has room for — roughly 37 px apart for
  // a "12:00" that needs ~33 px, i.e. touching. One tick per ~90 px keeps
  // desktop denser and mobile legible from the same rule.
  const target = Math.max(3, Math.min(8, Math.round(cw / 90)));
  let svg = '';
  if (Number.isFinite(tFirst) && Number.isFinite(tLast) && tSpan > 0) {
    const stepMs = pickTimeStep(tSpan, target);
    for (let t = anchorTickStart(tFirst, stepMs); t <= tLast; t += stepMs) {
      const x = pad.l + ((t - tFirst) / tSpan) * cw;
      svg += `<line x1="${x.toFixed(1)}" y1="${(pad.t + ch).toFixed(1)}" x2="${x.toFixed(1)}" y2="${(pad.t + ch + 5).toFixed(1)}" stroke="rgba(255,255,255,.12)" stroke-width="1"/>`;
      svg += `<text x="${x.toFixed(1)}" y="${baseY}" text-anchor="middle" font-size="11" fill="${AXIS_TEXT}">${fmtTimeTick(t, stepMs)}</text>`;
    }
    return svg;
  }
  const last = samples.length - 1;
  const intervals = Math.max(2, target - 1);
  for (let k = 0; k <= intervals; k++) {
    const idx = Math.round((last * k) / intervals);
    const x = pad.l + (idx / last) * cw;
    const anchor = k === 0 ? 'start' : k === intervals ? 'end' : 'middle';
    svg += `<text x="${x.toFixed(1)}" y="${baseY}" text-anchor="${anchor}" font-size="11" fill="${AXIS_TEXT}">${fmtTick(samples[idx]?.ts, hours)}</text>`;
  }
  return svg;
}

// Y-axis + its gridlines. Two modes, because the two modes genuinely
// have different vertical meanings:
//
//   isolated  — one line, drawn against its own {lo, hi}. Label the real
//               values in the line's own colour, nice-rounded so they
//               read 0 / 5 / 10 / 15 rather than 0.13 / 4.97 / 9.81.
//   all-lines — every line is normalised against its OWN min/max, so
//               there is no shared value scale. A "0–100 %" label was
//               tried here so the reserved left lane wasn't blank — but
//               it named a number nobody was asking about ("kp was das
//               soll"): each line's 100 % is a different real value, so
//               the label was technically accurate and practically
//               noise. Four plain gridlines stay as a visual anchor;
//               the real numbers live in the legend below the chart and
//               in the per-line hover tooltip, which is where "how much"
//               actually belongs when several units share one plot.
// One labelled value axis + its gridlines, drawn against an explicit
// {lo, hi} in the value's own unit. Extracted from buildYAxis's
// isolated branch so the storm compare chart — whose Y axis is shared
// and absolute across up to four episodes — reuses the exact same tick
// logic instead of growing a second one. `colour` is the label colour:
// the Wetter chart passes the metric's palette entry, compare passes a
// neutral white (there, colour already means "which episode").
export function buildValueAxis({ lo, hi, unit, colour, pad, cw, ch }) {
  const { ticks } = niceAxisTicks(lo, hi, 4);
  const span = hi - lo || 1;
  const fmt = (v) => (Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 1 : 0));
  let svg = '';
  for (const v of ticks) {
    // Skip ticks outside the data range (niceNum can over-shoot).
    if (v < lo - span * 0.05 || v > hi + span * 0.05) continue;
    const y = pad.t + ch - ((v - lo) / span) * ch;
    svg += gridLine(pad, cw, y);
    svg += `<text x="${pad.l - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-size="11" fill="${colour}" opacity="0.75">${fmt(v)}${unit ? ' ' + unit : ''}</text>`;
  }
  return svg;
}

export function buildYAxis({ isolated, lineMetas, data, pad, cw, ch }) {
  if (isolated && lineMetas[isolated]) {
    const meta = lineMetas[isolated];
    return buildValueAxis({
      lo: meta.lo,
      hi: meta.hi,
      unit: (data?.units || {})[isolated] || '',
      colour: WEATHER_STATS_PALETTE[isolated] || '#94a3b8',
      pad,
      cw,
      ch,
    });
  }
  let svg = '';
  for (let g = 0; g <= 4; g++) {
    svg += gridLine(pad, cw, pad.t + (g / 4) * ch);
  }
  return svg;
}
