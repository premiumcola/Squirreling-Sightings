// ─── vplayer/_overlay-svg.js ───────────────────────────────────────────────
// Boxes and trails as SVG markup, plus the one function allowed to
// position an overlay element.
//
// EVERYTHING IS AUTHORED IN VIEWBOX UNITS. The overlay's viewBox is the
// source's pixel size (say 2560×1440) while the element on screen is
// ~390 px wide. A font-size of 12 authored into that viewBox renders at
// 12 × 390/2560 ≈ 1.8 px: drawn, and humanly invisible. So every text
// and plate dimension is multiplied by `k`, the viewBox units per CSS
// pixel, and the plate is the same physical size whatever the camera
// streams. Strokes use vector-effect="non-scaling-stroke" instead.
//
// The trail ramp is NOT re-derived here — canvas/trail-layer.js already
// owns buildTrailPoints and buildTrailSvg, including the fade ramp and
// the leading-edge head dot. This file passes buildTrailSvg its
// scoreScale argument, which has had a parameter and no caller since it
// was written: it is what dims a filtered track relative to a passing
// one instead of painting both at full strength.

import { esc } from '../core/dom.js';
import { buildTrailSvg } from '../mediaview/canvas/trail-layer.js';
import { resolveBox } from './_box-model.js';
import { normalizeBox } from './_geometry.js';
// The layer positioner and its `inset` ban now live in core, shared
// with both existing painters. Re-exported so package code and the
// overlay-svg test keep one import path.
export { placeOverlay } from '../core/box-model.js';

// On-screen sizes in CSS px, scaled into viewBox units via k.
const _FONT_PX = 12;
const _PLATE_H_PX = 18;
const _PLATE_PAD_PX = 6;
const _PLATE_GAP_PX = 3;
// Mean glyph advance for system-ui at weight 700, as a fraction of the
// font size. Only used to size the plate behind the text — SVG has no
// synchronous text metrics and a few px of slack is invisible.
const _GLYPH_W = 0.58;

/**
 * viewBox units per CSS pixel.
 *
 * @param {number} frameW   source width, in source pixels
 * @param {number} screenW  rendered width, in CSS pixels
 */
export function overlayScale(frameW, screenW) {
  if (!(frameW > 0) || !(screenW > 0)) return 1;
  return frameW / screenW;
}

/**
 * The identity plate: dark slab, coloured text. Flips below the box
 * when the box is hard against the top edge, and is clamped inside the
 * frame horizontally so a box at the right edge keeps its label.
 */
function _plateSvg(text, colour, x, y, k, frameW) {
  if (!text) return '';
  const font = _FONT_PX * k;
  const h = _PLATE_H_PX * k;
  const pad = _PLATE_PAD_PX * k;
  const gap = _PLATE_GAP_PX * k;
  const w = Math.min(frameW || Infinity, text.length * font * _GLYPH_W + pad * 2);
  const py = y - h - gap >= 0 ? y - h - gap : y + gap;
  const px = frameW ? Math.max(0, Math.min(frameW - w, x)) : Math.max(0, x);
  return (
    `<rect x="${px.toFixed(1)}" y="${py.toFixed(1)}" width="${w.toFixed(1)}" ` +
    `height="${h.toFixed(1)}" rx="${(4 * k).toFixed(1)}" fill="rgba(8,12,18,0.85)"/>` +
    `<text x="${(px + pad).toFixed(1)}" y="${(py + h - pad * 0.9).toFixed(1)}" ` +
    `fill="${colour}" font-size="${font.toFixed(1)}" ` +
    `font-family="system-ui, sans-serif" font-weight="700">${esc(text)}</text>`
  );
}

/**
 * One detection → one `<g>`, in viewBox units.
 *
 * @param {object} det   detection or tracks.json sample
 * @param {object} opts  { k, frameW, selected, holdMul, colour }
 * @returns {string} SVG markup, or '' when the box is not drawable
 */
export function buildBoxSvg(det, opts = {}) {
  const box = normalizeBox(det && det.bbox);
  if (!box) return '';
  const k = opts.k || 1;
  const style = resolveBox(det, opts);
  const dash = style.dash.length ? ` stroke-dasharray="${style.dash.join(' ')}"` : '';
  return (
    `<g opacity="${style.alpha.toFixed(2)}" data-label="${esc(det.label || '')}"` +
    ` style="pointer-events:auto;cursor:pointer">` +
    `<rect x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}" fill="none" ` +
    `stroke="${style.stroke}" stroke-width="${style.width}" ` +
    `vector-effect="non-scaling-stroke"${dash}/>` +
    _plateSvg(style.plateText, style.plateFg, box.x, box.y, k, opts.frameW || 0) +
    `</g>`
  );
}

/**
 * A track's trail, delegating the ramp to canvas/trail-layer.js.
 *
 * @param {Array<{x,y}>} points  source-pixel points, oldest → newest
 * @param {string} colour
 * @param {object} [opts]  { strokeWidth, scoreScale }
 */
export function buildTrail(points, colour, opts = {}) {
  return buildTrailSvg(
    points,
    colour,
    opts.strokeWidth || 3,
    opts.scoreScale == null ? 1 : opts.scoreScale,
  );
}

/**
 * Paint a set of detections into a layer host.
 *
 * The host owns one <svg> for the life of the layer; only its
 * innerHTML changes per frame. Recreating the element every tick would
 * throw away the browser's own paint state and, on a phone, shows as a
 * flicker at 1 Hz.
 *
 * The viewBox is the SOURCE frame size, so everything inside is
 * authored in source pixels and the browser does the scaling —
 * the same contract both existing overlays use.
 *
 * A record may carry `colour` and `masked` alongside its detection.
 * Both are OPTIONAL and both default to what resolveBox already did:
 * the live path maps detections without either, and its boxes keep
 * taking their hue from the track number and their category from the
 * backend's verdict. They exist for the recorded path, where the hue is
 * the sidecar's own stamped `track.color` — the value the timeline lanes
 * and the object rows read, so all three name one subject in one colour
 * — and where masking is geometry the status vocabulary cannot express.
 *
 * @param {HTMLElement} host       a layer host from _stage.js
 * @param {Array} detections       mapped detections (see _data/_map.js)
 * @param {object} opts            { frameSize, screenW, selectedTrack }
 */
export function renderBoxLayer(host, detections, opts = {}) {
  if (!host) return;
  const fs = opts.frameSize;
  if (!fs || !(fs.w > 0) || !(fs.h > 0)) {
    host.innerHTML = '';
    return;
  }
  let svg = host.firstElementChild;
  if (!svg) {
    svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    host.appendChild(svg);
  }
  svg.setAttribute('viewBox', `0 0 ${fs.w} ${fs.h}`);
  const k = overlayScale(fs.w, opts.screenW || fs.w);
  svg.innerHTML = (detections || [])
    .map((d) =>
      buildBoxSvg(d.raw || d, {
        k,
        frameW: fs.w,
        colour: d.colour || null,
        masked: d.masked === true,
        selected: opts.selectedTrack != null && opts.selectedTrack === d.trackNum,
      }),
    )
    .join('');
}
