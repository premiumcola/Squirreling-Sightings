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
//               there is no shared value scale. Previously this branch
//               emitted four unlabelled gridlines and left the reserved
//               left lane blank, which read as "the axis is broken" and
//               hid the fact that "near the top" means a different
//               number for every line. Label the percentage instead:
//               it is what the axis actually measures, and saying so is
//               better than labelling nothing or — worse — printing one
//               line's units next to seven lines' curves.
export function buildYAxis({ isolated, lineMetas, data, pad, cw, ch }) {
  if (isolated && lineMetas[isolated]) {
    const meta = lineMetas[isolated];
    const unit = (data?.units || {})[isolated] || '';
    const colour = WEATHER_STATS_PALETTE[isolated] || '#94a3b8';
    const { ticks } = niceAxisTicks(meta.lo, meta.hi, 4);
    const span = meta.hi - meta.lo || 1;
    const fmt = (v) => (Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 1 : 0));
    let svg = '';
    for (const v of ticks) {
      // Skip ticks outside the data range (niceNum can over-shoot).
      if (v < meta.lo - span * 0.05 || v > meta.hi + span * 0.05) continue;
      const y = pad.t + ch - ((v - meta.lo) / span) * ch;
      svg += gridLine(pad, cw, y);
      svg += `<text x="${pad.l - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-size="11" fill="${colour}" opacity="0.75">${fmt(v)}${unit ? ' ' + unit : ''}</text>`;
    }
    return svg;
  }
  let svg = '';
  for (let g = 0; g <= 4; g++) {
    const y = pad.t + (g / 4) * ch;
    svg += gridLine(pad, cw, y);
    svg += `<text x="${pad.l - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-size="11" fill="${AXIS_TEXT}">${100 - g * 25} %</text>`;
  }
  return svg;
}
