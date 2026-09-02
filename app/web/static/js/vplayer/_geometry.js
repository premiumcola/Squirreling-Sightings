// ─── vplayer/_geometry.js ──────────────────────────────────────────────────
// PURE. One box shape, from either of the two the backend speaks.
//
// THIS IS THE SINGLE BIGGEST SOURCE OF DUPLICATION IN THE OLD CODE.
// A recorded clip's tracks.json sidecar stores a box as
// {x1, y1, x2, y2} in SOURCE pixels; the live detection endpoint
// reports [x, y, w, h] against its own frame_size. Both are source-
// pixel coordinates and they mean exactly the same thing, but because
// they are SHAPED differently every painter, interpolator, centroid
// and mask test in the tree was written twice — and then fixed twice,
// or (more often) once.
//
// normalizeBox folds both into {x, y, w, h}. Everything downstream —
// the box model, the SVG builders, the panels — sees one shape and is
// written once.

import { containRect } from '../core/video-fit.js';

/**
 * Fold either bbox schema into {x, y, w, h} in source pixels.
 *
 * @param {{x1:number,y1:number,x2:number,y2:number}|number[]} bbox
 * @returns {{x:number,y:number,w:number,h:number}|null} null when the
 *   box is absent, malformed or has no area. A zero-area box is not
 *   drawable and every caller would otherwise need its own guard —
 *   which is precisely how a 0×0 rect ends up painted as a dot.
 */
export function normalizeBox(bbox) {
  if (!bbox) return null;
  let x;
  let y;
  let w;
  let h;
  if (Array.isArray(bbox)) {
    if (bbox.length < 4) return null;
    [x, y, w, h] = bbox;
  } else if (typeof bbox === 'object') {
    // The corner form. Normalise the winding too: a box stored with
    // its corners the other way round is still a box.
    const { x1, y1, x2, y2 } = bbox;
    if (![x1, y1, x2, y2].every((v) => Number.isFinite(v))) return null;
    x = Math.min(x1, x2);
    y = Math.min(y1, y2);
    w = Math.abs(x2 - x1);
    h = Math.abs(y2 - y1);
  } else {
    return null;
  }
  if (![x, y, w, h].every((v) => Number.isFinite(v))) return null;
  if (w <= 0 || h <= 0) return null;
  return { x, y, w, h };
}

/**
 * Map a source-pixel box onto the letterboxed picture.
 *
 * Built on containRect, so the box lands on exactly the same rect the
 * stage pinned its overlay layers to. An overlay that solves the
 * letterbox a second time, slightly differently, is how boxes end up
 * half a gutter off their subject.
 *
 * @param {{x,y,w,h}} box   source-pixel box, from normalizeBox
 * @param {number} srcW     source width
 * @param {number} srcH     source height
 * @param {number} boxW     destination box width, CSS px
 * @param {number} boxH     destination box height, CSS px
 * @returns {{x,y,w,h}|null} rect in destination coordinates
 */
export function overlayRectFor(box, srcW, srcH, boxW, boxH) {
  if (!box) return null;
  if (!(srcW > 0) || !(srcH > 0)) return null;
  const fit = containRect(srcW, srcH, boxW, boxH);
  if (!(fit.w > 0) || !(fit.h > 0)) return null;
  const k = fit.w / srcW;
  return {
    x: fit.x + box.x * k,
    y: fit.y + box.y * k,
    w: box.w * k,
    h: box.h * k,
  };
}

/**
 * The centre of a box, in the same space the box is in. Used for
 * trail points and for the nearest-box hit test.
 */
export function boxCenter(box) {
  if (!box) return null;
  return { x: box.x + box.w / 2, y: box.y + box.h / 2 };
}

/**
 * Is this point inside the box? Half-open on the far edges so two
 * adjacent boxes cannot both claim the same pixel.
 */
export function pointInBox(box, px, py) {
  if (!box) return false;
  return px >= box.x && px < box.x + box.w && py >= box.y && py < box.y + box.h;
}
