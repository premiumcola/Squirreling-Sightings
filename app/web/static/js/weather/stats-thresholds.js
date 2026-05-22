// ─── weather/stats-thresholds.js ───────────────────────────────────────────
// R11 — extracted from stats.js. Builds the threshold-overlay SVG for the
// Wetterstatistik chart. stats-chart.js calls this after the base chart
// is rendered; the helper returns the threshold svg fragment + an
// optional "Schwelle nicht im Bereich" hint that the chart appends below.
import { WEATHER_STATS_PALETTE, _WS_FIELD_ORDER } from './stats.js';

// Threshold overlay.
//
//  - Isolated mode: full horizontal dashed red line + right-side label
//    (existing behaviour — that mode is for direct line-vs-boundary
//    comparisons).
//  - All-lines mode: per-field 18 px tick on the right edge in the
//    line's own colour, with a 9 px label to the right of the tick.
//    Always rendered when a threshold is configured, regardless of
//    the event's enabled flag — events_enabled[k]==false dims the
//    tick/label to 0.4 opacity. Out-of-range thresholds clamp to
//    the top/bottom edge with ▲/▼ glyphs.
export function _buildThresholdSvg({ isolated, data, lineMetas, pad, cw, ch }) {
  let thresholdSvg = '';
  let noThresholdHint = '';
  if (isolated) {
    const thr = (data?.thresholds || {})[isolated];
    const meta = lineMetas[isolated];
    if (thr == null) {
      noThresholdHint = '<div class="ws-stats-no-threshold">keine Schwelle konfiguriert</div>';
    } else if (meta) {
      const { lo, hi } = meta;
      const norm = (thr - lo) / (hi - lo);
      if (norm >= -0.05 && norm <= 1.05) {
        const y = pad.t + ch - Math.max(0, Math.min(1, norm)) * ch;
        const u = (data?.units || {})[isolated] || '';
        const colour = WEATHER_STATS_PALETTE[isolated] || '#94a3b8';
        // Grafana-style: thin dashed horizontal in the LINE's colour
        // (not red) so the threshold reads as part of the same series,
        // plus a colour-tinted small label outside the right edge of
        // the plot. Keeps paint-order halo for legibility against the
        // chart background.
        const lbl = `${thr}${u ? ' ' + u : ''}`;
        thresholdSvg = `
          <line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${pad.l + cw}" y2="${y.toFixed(1)}"
                stroke="${colour}" stroke-width="1" stroke-dasharray="5 4" opacity="0.55"
                vector-effect="non-scaling-stroke" shape-rendering="geometricPrecision" />
          <text class="ws-chart-threshold-label" x="${(pad.l + cw + 4).toFixed(1)}" y="${(y + 3).toFixed(1)}" font-size="9" fill="${colour}" opacity="0.85" text-rendering="optimizeLegibility">${lbl}</text>
        `;
      } else {
        noThresholdHint =
          '<div class="ws-stats-no-threshold">Schwelle außerhalb des sichtbaren Bereichs</div>';
      }
    }
  } else {
    const tickX1 = pad.l + cw - 18;
    const tickX2 = pad.l + cw;
    const labelX = pad.l + cw + 4;
    const placedYs = []; // track placed label baselines to stack collisions
    for (const key of _WS_FIELD_ORDER) {
      const meta = lineMetas[key];
      if (!meta) continue;
      const thr = (data?.thresholds || {})[key];
      if (thr == null) continue;
      const enabled = (data?.events_enabled || {})[key];
      // events_enabled === null → field has no associated event (cloud,
      // wind, sun) and no threshold either, so the thr==null branch above
      // already handled it. true = armed (full opacity), false = configured
      // but off (dim).
      const opacity = enabled === false ? 0.4 : 1.0;
      const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
      const { lo, hi } = meta;
      const norm = (thr - lo) / (hi - lo);
      let tickY,
        glyph = '',
        clampNote = '';
      if (norm > 1) {
        tickY = pad.t + 4;
        glyph = '▲ ';
        clampNote = ` · aktuell ≪`;
      } else if (norm < 0) {
        tickY = pad.t + ch - 4;
        glyph = '▼ ';
        clampNote = ` · aktuell ≫`;
      } else {
        tickY = pad.t + ch - norm * ch;
      }
      // Avoid label-on-label: shift down by 11 px until clear of any
      // already-placed label baseline (within ±11 px).
      let labelY = tickY + 3.5;
      while (placedYs.some((y) => Math.abs(y - labelY) < 11)) {
        labelY += 11;
      }
      placedYs.push(labelY);
      const u = (data?.units || {})[key] || '';
      const thrFmt =
        typeof thr === 'number' && !Number.isInteger(thr) && Math.abs(thr) < 100
          ? thr.toFixed(2)
          : Math.round(thr);
      const labelText = `${glyph}${thrFmt}${u ? ' ' + u : ''}`;
      const aria = `Schwelle ${thr}${u ? ' ' + u : ''}${clampNote}`;
      thresholdSvg += `
        <line x1="${tickX1.toFixed(1)}" y1="${tickY.toFixed(1)}" x2="${tickX2.toFixed(1)}" y2="${tickY.toFixed(1)}"
              stroke="${colour}" stroke-width="2" stroke-linecap="round" opacity="${opacity}"
              vector-effect="non-scaling-stroke" shape-rendering="geometricPrecision">
          <title>${aria}</title>
        </line>
        <text x="${labelX.toFixed(1)}" y="${labelY.toFixed(1)}" font-size="9" fill="${colour}" opacity="${opacity}" text-rendering="geometricPrecision">${labelText}</text>
      `;
    }
  }
  return { thresholdSvg, noThresholdHint };
}
