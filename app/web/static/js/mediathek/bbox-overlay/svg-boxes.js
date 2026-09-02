// ─── mediathek/bbox-overlay/svg-boxes.js ───────────────────────────────────
// SVG sibling of the canvas trail layer — detection BOXES for recorded
// playback render as SVG (`<rect>` + a label plate), never burned into the
// video, so the browser can express crisp non-scaling strokes at any zoom
// and the box layer can be toggled/inspected like any other DOM overlay.
// Trails stay canvas (mediaview/canvas/trail-layer.js) — this task was
// scoped to detection boxes only.
//
// Follows the canvas/trail-layer.js precedent: ./_box-style.js is the ONE
// shared style/text resolver; this file is the thin SVG-specific painter,
// mirroring drawTrackBoxCanvas in the (now-retired) _canvas-shapes.js.
//
// Positioning reuses core/video-fit.js's fittedRect() for the letterbox
// math — the SAME technique mediaview/live-detect-bbox-fit.js's
// _positionSvgOverImage uses for the live view — WITHOUT importing that
// module directly: it also pulls in live's own session singleton
// (live-detect-state.js's `S`) and a zone-video fast path that has no
// meaning here, so re-deriving the ~4 lines of delta math against
// fittedRect() keeps recorded's package free of live-detect's state.
import { byId } from '../../core/dom.js';
import { fittedRect } from '../../core/video-fit.js';
import { normalizeBox } from '../../core/box-model.js';
import { _overlayScale } from '../../mediaview/live-detect-bbox-shapes.js';
import { resolveBoxStyle } from './_box-style.js';

function _ensureBboxSvg(wrap) {
  let svg = byId('lightboxBboxSvg');
  if (svg) {
    if (svg.parentNode !== wrap) wrap.appendChild(svg);
    return svg;
  }
  if (!wrap) return null;
  svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'lightboxBboxSvg';
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  // Longhands only — never the `inset` shorthand. _positionBboxSvg below
  // rewrites left/top/right/bottom on every draw; a stray `inset` in this
  // seed would silently reset them back to `auto` (the exact "no bboxes"
  // bug live-detect-bbox-fit.js's header comment documents).
  // Same z-index as the trails canvas (#lightboxDetections, z-index 3 via
  // modals.html) — z-index 4 is already taken by the zone/mask overlay
  // (zone-overlay-mount.js) + #lightboxLabels, and the pre-existing
  // stacking has detections BELOW zones/masks. Appending this SVG after
  // the (already-in-DOM) trails canvas is what puts boxes visually on
  // top of trails within that same z-index tier, without disturbing the
  // zones-above-detections relationship.
  svg.style.cssText =
    'position:absolute;left:0;top:0;right:auto;bottom:auto;' +
    'width:100%;height:100%;pointer-events:none;z-index:3';
  wrap.appendChild(svg);
  return svg;
}

function _positionBboxSvg(svg, media, wrap) {
  const wrapRect = wrap.getBoundingClientRect();
  const mediaRect = media.getBoundingClientRect();
  const fit = fittedRect(media);
  svg.style.left = `${mediaRect.left - wrapRect.left + fit.x}px`;
  svg.style.top = `${mediaRect.top - wrapRect.top + fit.y}px`;
  svg.style.right = 'auto';
  svg.style.bottom = 'auto';
  svg.style.width = `${fit.w}px`;
  svg.style.height = `${fit.h}px`;
}

// Identity plate above the box — same visual convention as the canvas
// pill (_canvas-shapes.js, retired): dark-enough fill from resolveBoxStyle,
// darkened text. `k` is viewBox units per CSS pixel (_overlayScale, shared
// with the live SVG painter) so the plate is a constant on-screen size
// regardless of the clip's native resolution.
function _plateMarkup(style, x, y, k, frameW) {
  const fontPx = 12,
    plateH = 18,
    padX = 6,
    gap = 3,
    glyphW = 0.58;
  const font = fontPx * k;
  const h = plateH * k;
  const pad = padX * k;
  const w = Math.min(frameW, style.text.length * font * glyphW + pad * 2);
  const py = y - h - gap * k >= 0 ? y - h - gap * k : y + gap * k;
  const px = Math.max(0, Math.min(frameW - w, x));
  return (
    `<rect x="${px.toFixed(1)}" y="${py.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="${(4 * k).toFixed(1)}" fill="${style.pillBg}" opacity="${style.alpha}"/>` +
    `<text x="${(px + pad).toFixed(1)}" y="${(py + h - pad * 0.9).toFixed(1)}" fill="${style.pillTextColor}" font-size="${font.toFixed(1)}" font-family="system-ui, sans-serif" font-weight="600">${style.text}</text>`
  );
}

function _boxMarkup(sample, style, k, frameW) {
  // One box shape for every surface. tracks.json stores corners, the
  // live endpoint stores origin+size; normalizeBox folds both and
  // carries the zero-area guard that used to live inline here.
  const box = normalizeBox(sample.bbox);
  if (!box) return '';
  const { x, y, w, h } = box;
  const dash = style.dash.length ? ` stroke-dasharray="${style.dash.join(' ')}"` : '';
  const rect =
    `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" ` +
    `fill="none" stroke="${style.stroke}" stroke-width="2" opacity="${style.alpha}" ` +
    `vector-effect="non-scaling-stroke"${dash}/>`;
  const plate = style.text ? _plateMarkup(style, x, y, k, frameW) : '';
  return `<g>${rect}${plate}</g>`;
}

/**
 * Repaint the SVG box layer for the current frame. `boxes` is an array of
 * `{ sample, trackColor, status, masked, trackNum }` — one entry per
 * track/detection that passed the visibility gate this render. Pass an
 * empty array to clear the layer (still positions/sizes it so the next
 * populated frame doesn't have to).
 */
export function drawTrackBoxesSvg(media, wrap, natW, natH, boxes) {
  const svg = _ensureBboxSvg(wrap);
  if (!svg) return;
  svg.setAttribute('viewBox', `0 0 ${natW} ${natH}`);
  _positionBboxSvg(svg, media, wrap);
  const screenW = media.getBoundingClientRect().width || 1;
  const k = _overlayScale(natW, screenW);
  svg.innerHTML = boxes
    .map(({ sample, trackColor, status, masked, trackNum }) =>
      _boxMarkup(sample, resolveBoxStyle(sample, trackColor, status, masked, trackNum), k, natW),
    )
    .join('');
}

/** Empty the box layer without touching its position/size. */
export function clearBboxSvg() {
  const svg = byId('lightboxBboxSvg');
  if (svg) svg.innerHTML = '';
}
