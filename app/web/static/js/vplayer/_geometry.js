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
import { _pointInPoly, _polyPoints } from '../shape-editor/geometry.js';
// normalizeBox moved to core/box-model.js when the two existing
// painters adopted it — neither may import from this package. Nothing
// in this file calls it (overlayRectFor takes an already-normalised
// box), so a plain re-export is correct here; a caller that DID use it
// locally would need the import statement as well.
export { normalizeBox } from '../core/box-model.js';

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

/**
 * Is this source-pixel point inside any exclusion mask?
 *
 * The polygon test itself is shape-editor/geometry.js's _pointInPoly —
 * the same one the mask editor uses to decide what it drew, so what the
 * operator outlined and what the pipeline excludes cannot diverge.
 *
 * A mask may have been drawn against a DIFFERENT source resolution than
 * the clip being tested (the camera's main stream changed, or the mask
 * came from the sub stream), so each polygon carries its own source_w /
 * source_h and the point is scaled into that polygon's space before the
 * test. Dropping that scale silently shifts every mask on any camera
 * whose resolution ever changed.
 */
export function pointInAnyMask(px, py, srcW, srcH, masks) {
  if (!masks || !masks.length) return false;
  for (const m of masks) {
    const points = _polyPoints(m);
    if (points.length < 3) continue;
    const msrcW = (m && typeof m === 'object' && m.source_w) || srcW;
    const msrcH = (m && typeof m === 'object' && m.source_h) || srcH;
    const sx = msrcW > 0 && srcW > 0 ? msrcW / srcW : 1;
    const sy = msrcH > 0 && srcH > 0 ? msrcH / srcH : 1;
    if (_pointInPoly({ x: px * sx, y: py * sy }, points)) return true;
  }
  return false;
}

/**
 * The point a mask test uses for a box: the centre of its BOTTOM edge,
 * not its centroid. A mask marks ground the operator does not care
 * about — a pavement, a neighbour's drive — and what decides whether a
 * subject is standing there is where its feet are.
 */
export function maskProbePoint(box) {
  if (!box) return null;
  return { x: box.x + box.w / 2, y: box.y + box.h };
}
