// ─── mediathek/bbox-overlay/_box-style.js ──────────────────────────────────
// Pure per-box style + label-text resolution — the ONE place that turns
// (sample, trackColor, status, masked, trackNum) into paintable parameters.
// Both the canvas trail layer (renderTrailLayer) and the SVG box layer
// (svg-boxes.js) read from here so the two surfaces can never drift —
// mirrors canvas/trail-layer.js's buildTrailPoints -> {drawTrailPolyline,
// buildTrailSvg} split: one shared geometry/style helper, thin per-surface
// paint code.
//
// Status dash/alpha come from mediaview/status-legend.js's MV_STATUS_STYLE
// (the fold that used to live as a private duplicate here — see git log).
import { MV_STATUS_STYLE } from '../../mediaview/status-legend.js';

// Neutral gray for the ⊘ Maskiert modifier. Replaces the track's
// per-identity color (the per-track hue still drives the timeline
// row and the legend's "Farbe = Person" hint, but a masked-out
// subject is rendered in neutral so it's visually clear it has
// been filtered out of alerting).
export const MASKED_STROKE = '#94a3b8';

/**
 * Darken a hex color toward black for label-text use. Keeps the
 * hue family so the pill text reads as "the same color, but dark"
 * — never plain black. factor 0..1, smaller = darker.
 */
function _darkenHex(hex, factor) {
  const fb = '#0a0a0a';
  if (!hex || typeof hex !== 'string' || hex[0] !== '#') return fb;
  let h = hex.slice(1);
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  if (h.length !== 6) return fb;
  const n = parseInt(h, 16);
  if (!Number.isFinite(n)) return fb;
  const r = Math.floor(((n >> 16) & 0xff) * factor);
  const g = Math.floor(((n >> 8) & 0xff) * factor);
  const b = Math.floor((n & 0xff) * factor);
  return `rgb(${r},${g},${b})`;
}

// "↓ #N · X %" (status marker + person number + score) — recorded's own
// pill convention (no class name; the timeline badge + swimlane already
// name the class). Kept distinct from live's `_bboxLabelText` (which DOES
// print the class name) — recorded's visual identity predates that and
// this refactor isn't the place to change it.
function _pillText(sample, trackNum, masked, marker) {
  const hasNum = typeof trackNum === 'number';
  const pct = sample.score != null ? Math.round(sample.score * 100) : null;
  const prefix = `${masked ? '⊘ ' : ''}${marker}`;
  const numText = hasNum ? `#${trackNum}` : '';
  if (numText && pct != null) return `${prefix}${numText} · ${pct}%`;
  if (numText) return `${prefix}${numText}`.trim();
  if (pct != null) return `${prefix}${pct}%`;
  return '';
}

/**
 * Resolve every paint parameter for one box: which category (confirmed /
 * weak / ghost, folding in the masked override), stroke color, dash
 * pattern, alpha, and the pill's text + colors. Both painters call this
 * and only differ in how they turn `bbox` + these params into pixels.
 */
export function resolveBoxStyle(sample, trackColor, status, masked, trackNum) {
  const cat = status && MV_STATUS_STYLE[status] ? status : 'confirmed';
  const style = MV_STATUS_STYLE[cat];
  const baseColor = trackColor || '#22c55e';
  const stroke = masked ? MASKED_STROKE : baseColor;
  return {
    dash: style.dash,
    alpha: style.alpha,
    stroke,
    pillBg: masked ? 'rgba(148,163,184,0.92)' : baseColor,
    pillTextColor: _darkenHex(masked ? MASKED_STROKE : baseColor, 0.18),
    text: _pillText(sample, trackNum, masked, style.marker),
  };
}
