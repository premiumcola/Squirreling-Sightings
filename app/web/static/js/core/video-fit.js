// ─── core/video-fit.js ─────────────────────────────────────────────────────
// One helper for the "where do the pixels actually land inside the
// <video> / <img> element" question. Every read-only overlay
// (zones, bboxes, trails, masks) needs this — without it, polygons
// drawn in source-resolution coords land in the wrong place once
// the media element is letterboxed by `object-fit: contain`.
//
// Returns the inner rect, in CSS pixels relative to the element's
// content box, that actually displays media. The four sides of that
// rect plus the rect's width/height are everything an overlay needs
// to map source coords (srcW × srcH) → on-screen coords.

/**
 * The numeric core: reproduce object-fit:contain as pure arithmetic.
 * No DOM, no element — just "a srcW×srcH picture inside a boxW×boxH
 * box". Every letterbox question in the app reduces to this, so it
 * lives in exactly one place; a player with two letterbox solvers is
 * how overlays and their video drift apart by half a gutter.
 *
 * Degenerate input (unknown source dimensions, an unmeasured box)
 * yields the full box at scale 1 rather than NaN or a zero-size rect,
 * which is what lets callers mount an overlay before the first frame
 * decodes and simply redraw when metadata lands.
 *
 * @param {number} srcW  source width in source pixels
 * @param {number} srcH  source height in source pixels
 * @param {number} boxW  destination box width in CSS pixels
 * @param {number} boxH  destination box height in CSS pixels
 * @returns {{x:number, y:number, w:number, h:number, scale:number}}
 */
export function containRect(srcW, srcH, boxW, boxH) {
  const bw = boxW > 0 ? boxW : 0;
  const bh = boxH > 0 ? boxH : 0;
  if (!(srcW > 0) || !(srcH > 0) || bw <= 0 || bh <= 0) {
    return { x: 0, y: 0, w: bw, h: bh, scale: 1 };
  }
  const scale = Math.min(bw / srcW, bh / srcH);
  const w = srcW * scale;
  const h = srcH * scale;
  return { x: (bw - w) / 2, y: (bh - h) / 2, w, h, scale };
}

/**
 * Compute the visible pixel rect inside a <video> or <img> that
 * uses object-fit:contain. Falls back to the element's full content
 * box when source dimensions are unknown (e.g. before first frame
 * decode) so callers never get a zero-size rect.
 *
 * @param {HTMLVideoElement|HTMLImageElement} el
 * @returns {{x:number, y:number, w:number, h:number}}
 */
export function fittedRect(el) {
  if (!el) return { x: 0, y: 0, w: 0, h: 0 };
  const box = el.getBoundingClientRect();
  const srcW = el.videoWidth || el.naturalWidth || 0;
  const srcH = el.videoHeight || el.naturalHeight || 0;
  const { x, y, w, h } = containRect(srcW, srcH, box.width, box.height);
  return { x, y, w, h };
}

/**
 * Compute the scale factor object-fit:contain applies, decoupled from
 * the centring offset. Handy for stroke widths that need to track
 * the displayed size without being pulled inside the letterbox rect.
 */
export function fitScale(el) {
  if (!el) return 1;
  const box = el.getBoundingClientRect();
  const srcW = el.videoWidth || el.naturalWidth || 0;
  const srcH = el.videoHeight || el.naturalHeight || 0;
  return containRect(srcW, srcH, box.width, box.height).scale;
}
