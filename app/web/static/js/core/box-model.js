// ─── core/box-model.js ─────────────────────────────────────────────────────
// The one answer to "what shape is this box, how is it painted, and
// where does its layer go" — shared by every surface that draws a
// detection over a picture.
//
// It lives in core, not beside any one player, because THREE painters
// need it: the recorded SVG overlay, the live overlay, and the new
// unified player. A shared primitive parked inside one of them would
// make the other two depend on the player they are replacing.
//
// ── The three things this ends ─────────────────────────────────────────
//
// TWO BOX SHAPES. A recorded clip's tracks.json sidecar stores a box as
// {x1, y1, x2, y2} in source pixels; the live endpoint reports
// [x, y, w, h] against its frame_size. Same meaning, different shape —
// which is why every painter, interpolator, centroid and mask test in
// this tree was written twice, and fixed once. normalizeBox folds both.
//
// TWO STYLE RESOLVERS. Dash, alpha and the status marker come from
// mediaview/status-legend.js's MV_STATUS_STYLE, the one table the
// legend swatches also read, so a painted box and the row explaining it
// cannot drift. What each painter added on top of that table is what
// diverged, and resolveBox is now the single answer.
//
// THREE COPIES OF THE LAYER POSITIONER, each of which had to remember
// the same trap independently. See placeOverlayBox.

import { OBJ_LABEL } from './icons.js';
import { pctLabel } from './format.js';
import { liveTrackColor } from './track-color.js';
import { MV_STATUS_STYLE, mvStatusCategory } from '../mediaview/status-legend.js';

/**
 * The masked grey. This is the value status-legend.js paints its own
 * "⊘ Maskiert" swatch with, so a masked stroke and the legend row
 * explaining it finally agree.
 */
export const MASKED_STROKE = '#64748b';

/** Plate ground. Dark and translucent — readable over any picture. */
export const PLATE_BG = 'rgba(8,12,18,0.85)';

/** Fallback stroke when a detection carries no track number yet. */
const _FALLBACK_STROKE = '#22c55e';

/**
 * Fold either bbox schema into {x, y, w, h} in source pixels.
 *
 * @param {{x1,y1,x2,y2}|number[]} bbox
 * @returns {{x:number,y:number,w:number,h:number}|null} null when the
 *   box is absent, malformed or has no area. A zero-area box is not
 *   drawable and every caller would otherwise need its own guard —
 *   which is how a 0x0 rect ends up painted as a dot.
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
 * The identity string a box carries: marker · #track · class · score.
 *
 * Every part is optional except the score, because a detection can
 * arrive before the tracker has numbered it and a label can be missing
 * from the German table. Absent parts are dropped rather than printed
 * as a gap or as "undefined".
 */
export function plateText(det, cat) {
  const marker = MV_STATUS_STYLE[cat]?.marker || '';
  const num = Number.isFinite(det.track_num) && det.track_num > 0 ? `#${det.track_num}` : '';
  const cls = det.label ? OBJ_LABEL[det.label] || det.label : '';
  const pct = det.score == null ? '' : pctLabel(det.score);
  const body = [num, cls, pct].filter(Boolean).join(' · ');
  // A masked box says so in words as well as in colour: the grey alone
  // has been read as "low confidence" before.
  const tail = cat === 'masked' && body ? `${body} · gefiltert` : body;
  return `${marker ? `${marker} ` : ''}${tail}`.trim();
}

/**
 * Resolve every paint parameter for one detection or tracks.json
 * sample.
 *
 * @param {object} det  { verdict|status, score, label, track_num }
 * @param {object} [opts]
 * @param {string} [opts.colour]    explicit stroke, else the track hue
 * @param {boolean} [opts.masked]   force the masked category — the
 *   recorded painter decides masking geometrically, outside the status
 *   vocabulary, and passes the answer in
 * @param {boolean} [opts.selected] thicker stroke while focused
 * @param {number} [opts.holdMul]   hold-time fade multiplier, 0..1
 * @returns {{cat, stroke, dash, alpha, width, marker, plateText,
 *   plateBg, plateFg}}
 */
export function resolveBox(det, opts = {}) {
  const d = det || {};
  // Recorded samples carry `status`, live detections carry `verdict`.
  // Both vocabularies fold through the same categoriser.
  const raw = d.verdict != null ? d.verdict : d.status;
  const cat = opts.masked ? 'masked' : mvStatusCategory(raw);
  const style = MV_STATUS_STYLE[cat] || MV_STATUS_STYLE.confirmed;
  const masked = cat === 'masked';
  const base = opts.colour || liveTrackColor(d.track_num) || _FALLBACK_STROKE;
  const stroke = masked ? MASKED_STROKE : base;
  const hold = opts.holdMul == null ? 1 : opts.holdMul;
  return {
    cat,
    stroke,
    dash: style.dash,
    alpha: style.alpha * hold,
    width: opts.selected ? 5 : 3,
    marker: style.marker,
    plateText: plateText(d, cat),
    plateBg: PLATE_BG,
    plateFg: stroke,
  };
}

function _px(v) {
  return typeof v === 'number' ? `${v}px` : v;
}

/**
 * Pin an absolutely positioned overlay to an explicit rect.
 *
 * CRITICAL · writes left / top / right / bottom as LONGHANDS and never
 * the `inset` shorthand. `inset` expands to all four, so assigning it
 * after the longhands resets left and top to `auto`; the overlay then
 * falls to its static position below the picture and is clipped away by
 * the host's overflow:hidden. That is the documented "no bboxes in the
 * simulation view" bug — it was independently rediscovered by three
 * different layer positioners, which is exactly why there is now one.
 *
 * Width and height accept a number (taken as px) or a string, so a
 * caller that wants a plain '100%' fill still gets one.
 */
export function placeOverlayBox(el, left, top, width, height) {
  if (!el) return;
  const s = el.style;
  s.left = _px(left);
  s.top = _px(top);
  s.right = 'auto';
  s.bottom = 'auto';
  s.width = _px(width);
  s.height = _px(height);
}

/** placeOverlayBox, taking the rect shape the geometry helpers emit. */
export function placeOverlay(el, rect) {
  if (!el || !rect) return;
  placeOverlayBox(el, rect.x, rect.y, rect.w, rect.h);
}
