// ─── mediaview/live-detect-bbox-shapes.js ──────────────────────────────────
// The per-detection SVG for the live bbox overlay: the box itself plus a
// readable identity plate (track number · class · confidence · status
// marker).
//
// Everything here is authored in VIEWBOX units — the overlay's viewBox is
// the snapshot's pixel size (e.g. 960×540) while the element on screen is
// ~390 px wide on an iPhone. A font-size of 12 in viewBox units would
// therefore render at 12 × 390/960 ≈ 5 px: technically drawn, humanly
// invisible. Every text/plate dimension is multiplied by ``k`` (viewBox
// units per CSS pixel) so the plate is the SAME size on screen no matter
// what resolution the camera streams. Strokes use vector-effect instead.
//
// Line style + opacity come from status-legend.js' MV_STATUS_STYLE, so a
// painted box and the legend swatch that explains it can never drift.

import { esc } from '../core/dom.js';
import { OBJ_LABEL } from '../core/icons.js';
import { liveTrackColor } from '../core/track-color.js';
import { MV_STATUS_STYLE, mvStatusCategory } from './status-legend.js';

// Neutral slate for a class the object-filter excludes — same hue the
// legend's "⊘ Maskiert" swatch uses.
const _MASKED_COLOR = '#64748b';
// On-screen sizes in CSS px (scaled into viewBox units via k).
const _FONT_PX = 12;
const _PLATE_H_PX = 18;
const _PLATE_PAD_PX = 6;
const _PLATE_GAP_PX = 3;
// Mean glyph advance for system-ui at weight 700, as a fraction of the
// font size. Only used to size the plate behind the text — SVG has no
// synchronous text metrics, and a few px of slack is invisible.
const _GLYPH_W = 0.58;

/**
 * viewBox units per CSS pixel. Multiply any on-screen px size by this to
 * get the value to author into the SVG.
 */
export function _overlayScale(frameW, screenW) {
  if (!(frameW > 0) || !(screenW > 0)) return 1;
  return frameW / screenW;
}

/**
 * The one identity string a box carries: status marker · #track ·
 * class · confidence. Mirrors the Detections panel row ("#1 Person
 * PASS 82 %") so the picture and the panel name the same thing.
 */
export function _bboxLabelText(d) {
  const cat = mvStatusCategory(d.verdict);
  const marker = MV_STATUS_STYLE[cat]?.marker || '';
  const num = Number.isFinite(d.track_num) && d.track_num > 0 ? `#${d.track_num} ` : '';
  const cls = OBJ_LABEL[d.label] || d.label;
  const pct = `${Math.round((d.score || 0) * 100)} %`;
  const tail = cat === 'masked' ? `${pct} · gefiltert` : pct;
  return `${marker ? `${marker} ` : ''}${num}${cls} · ${tail}`;
}

// Identity plate — dark slab + coloured text. A filled plate beats a
// stroked text halo here: it stays readable over bright sky AND over a
// dark hedge, and it survives the group's hold-time fade legibly.
function _plateSvg(text, colour, x, y, k, frameW) {
  const font = _FONT_PX * k;
  const h = _PLATE_H_PX * k;
  const pad = _PLATE_PAD_PX * k;
  const w = Math.min(frameW, text.length * font * _GLYPH_W + pad * 2);
  const gap = _PLATE_GAP_PX * k;
  // Above the box; flipped inside when the box is hard against the top.
  const py = y - h - gap >= 0 ? y - h - gap : y + gap;
  const px = Math.max(0, Math.min(frameW - w, x));
  return (
    `<rect x="${px.toFixed(1)}" y="${py.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="${(4 * k).toFixed(1)}" fill="rgba(8,12,18,0.85)"/>` +
    `<text x="${(px + pad).toFixed(1)}" y="${(py + h - pad * 0.9).toFixed(1)}" fill="${colour}" font-size="${font.toFixed(1)}" font-family="system-ui, sans-serif" font-weight="700">${esc(text)}</text>`
  );
}

/**
 * One detection → one `<g data-label>`. ``opts``: { k, frameW,
 * selected, holdMul }.
 */
export function _buildBboxGroup(d, opts = {}) {
  const k = opts.k || 1;
  const cat = mvStatusCategory(d.verdict);
  const style = MV_STATUS_STYLE[cat] || MV_STATUS_STYLE.confirmed;
  // J2 · colour encodes the TRACK number (class is read from the plate
  // text, the lane icon and the detail panels — never the hue). Status
  // is the line STYLE: solid = bestätigt, dashed = schwach, slate =
  // maskiert.
  const colour = cat === 'masked' ? _MASKED_COLOR : liveTrackColor(d.track_num);
  const op = style.alpha * (opts.holdMul == null ? 1 : opts.holdMul);
  const [x, y, bw, bh] = d.bbox;
  const dash = style.dash.length ? ` stroke-dasharray="${style.dash.join(' ')}"` : '';
  const width = opts.selected ? 5 : 3;
  return (
    `<g opacity="${op.toFixed(2)}" data-label="${esc(d.label)}" style="pointer-events:auto;cursor:pointer">` +
    `<rect x="${x}" y="${y}" width="${bw}" height="${bh}" fill="none" stroke="${colour}" stroke-width="${width}" vector-effect="non-scaling-stroke"${dash}/>` +
    _plateSvg(_bboxLabelText(d), colour, x, y, k, opts.frameW || 0) +
    `</g>`
  );
}
