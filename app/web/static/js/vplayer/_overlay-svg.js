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
// The density rule owns the plate's on-screen metrics AND the fit test,
// because the two have to agree to the pixel — see _density.js.
import {
  clearOfChrome,
  fitPlateText,
  plateWidthPx,
  VP_PLATE_FONT_PX,
  VP_PLATE_GAP_PX,
  VP_PLATE_H_PX,
  VP_PLATE_PAD_PX,
} from './_density.js';
// The layer positioner and its `inset` ban now live in core, shared
// with both existing painters. Re-exported so package code and the
// overlay-svg test keep one import path.
export { placeOverlay } from '../core/box-model.js';

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
 * Where the plate goes, in viewBox units — or null for "nowhere good".
 *
 * SIX CANDIDATES, in the order a reader expects them. Vertically: above
 * the box, then just inside its top edge, then just inside its bottom
 * edge. Horizontally: flush with the box's left edge, then with its
 * right. Every one of them still names the same rectangle, which is what
 * makes a fallback legitimate — the label never leaves its box's own
 * neighbourhood, it only picks a corner of it that is not under a
 * button.
 *
 * When ALL SIX are buried the answer is null. A label printed under the
 * play disc is not a label, it is a smudge on the button, and the box it
 * belongs to is still drawn and still listed in the panel below.
 *
 * `chrome` is measured in CSS px against the picture (see
 * _density.js::chromeRects), so each candidate is divided by `k` before
 * it is tested. With no chrome measured — every unit test, and every
 * frame while the chrome is faded out during playback — the first
 * candidate always wins, which is exactly where the plate sat before.
 */
function _platePos(w, h, gap, box, frameW, k, chrome) {
  const clampX = (x) => (frameW ? Math.max(0, Math.min(frameW - w, x)) : Math.max(0, x));
  const xs = [clampX(box.x), clampX(box.x + box.w - w)];
  for (const py of [box.y - h - gap, box.y + gap, box.y + box.h - h - gap]) {
    if (py < 0) continue;
    for (const px of xs) {
      if (clearOfChrome({ x: px / k, y: py / k, w: w / k, h: h / k }, chrome)) return { px, py };
    }
  }
  return null;
}

/**
 * The identity plate: dark slab, coloured text. Clamped inside the frame
 * horizontally so a box at the right edge keeps its label.
 *
 * @param {{x,y,w,h}} box  the detection box, in viewBox units
 * @param {object} opts    { k, frameW, chrome }
 */
function _plateSvg(text, colour, box, opts) {
  if (!text) return '';
  const { k, frameW } = opts;
  const font = VP_PLATE_FONT_PX * k;
  const h = VP_PLATE_H_PX * k;
  const pad = VP_PLATE_PAD_PX * k;
  const gap = VP_PLATE_GAP_PX * k;
  const w = Math.min(frameW || Infinity, plateWidthPx(text) * k);
  const at = _platePos(w, h, gap, box, frameW, k, opts.chrome);
  if (!at) return '';
  const { px, py } = at;
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
 * THE LABEL IS NOT `style.plateText`. That is the fullest form; what
 * actually gets printed is whatever rung of it this box is big enough to
 * carry, which _density.js decides from the box's ON-SCREEN size. `k`
 * converts: a 90-unit-wide box on a 640-wide source rendered 375 px wide
 * is 53 CSS px of screen, and 53 px holds „#2", not
 * „⊘ #2 · Katze · 52 % · gefiltert".
 *
 * @param {object} det   detection or tracks.json sample
 * @param {object} opts  { k, frameW, frameH, chrome, selected, holdMul,
 *                         colour }
 * @returns {string} SVG markup, or '' when the box is not drawable
 */
export function buildBoxSvg(det, opts = {}) {
  const box = normalizeBox(det && det.bbox);
  if (!box) return '';
  const k = opts.k || 1;
  const style = resolveBox(det, opts);
  const label = fitPlateText(det, style.cat, {
    boxW: box.w / k,
    boxH: box.h / k,
    pictureH: opts.frameH > 0 ? opts.frameH / k : 0,
  });
  const dash = style.dash.length ? ` stroke-dasharray="${style.dash.join(' ')}"` : '';
  return (
    `<g opacity="${style.alpha.toFixed(2)}" data-label="${esc(det.label || '')}"` +
    ` style="pointer-events:auto;cursor:pointer">` +
    `<rect x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}" fill="none" ` +
    `stroke="${style.stroke}" stroke-width="${style.width}" ` +
    `vector-effect="non-scaling-stroke"${dash}/>` +
    _plateSvg(label, style.plateFg, box, {
      k,
      frameW: opts.frameW || 0,
      chrome: opts.chrome,
    }) +
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
 * @param {object} opts            { frameSize, screenW, chrome,
 *                                   selectedTrack }
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
        // Both source dimensions travel, because the fit test needs the
        // PICTURE height as well as the box: a plate on a 90 px-tall
        // picture is a band across it whatever the box measures.
        frameH: fs.h,
        chrome: opts.chrome,
        colour: d.colour || null,
        masked: d.masked === true,
        selected: opts.selectedTrack != null && opts.selectedTrack === d.trackNum,
      }),
    )
    .join('');
}
