// ─── vplayer/_box-model.js ─────────────────────────────────────────────────
// PURE. ONE resolver from (detection | sample) to paint parameters.
//
// Today there are two, and they disagree in three visible ways. This
// file is the single answer, and each choice below is the one with
// evidence behind it rather than a preference:
//
//   THE PILL. Recorded prints "⊘ ↓ #2 · 87%" — marker, track number,
//   score, and NO class name, on the reasoning that the timeline badge
//   names the class. Live prints "↓ #1 Person · 82 %" — with the class.
//   The picture wins: an operator looking at a box should not have to
//   look somewhere else to learn what it is. One convention, class
//   included, and the German "87 %" spacing the rest of the chrome uses.
//
//   THE PLATE. Recorded fills the plate with the track colour and
//   darkens the text; live uses a dark slab with coloured text. The
//   dark slab wins on a stated reason: it stays readable over bright
//   sky AND over a dark hedge, and it survives the hold-time fade.
//
//   THE MASKED GREY. Recorded strokes #94a3b8, live strokes #64748b —
//   and status-legend.js's own swatch paints #64748b. So recorded's
//   painted stroke has never matched the legend row that explains it.
//   One grey, the legend's.
//
// Line style, alpha and the status marker are NOT decided here. They
// are read from mediaview/status-legend.js's MV_STATUS_STYLE through
// its mvStatusCategory(), the one table the legend swatches also read,
// so a painted box and the row explaining it cannot drift.

import { OBJ_LABEL } from '../core/icons.js';
import { liveTrackColor } from '../core/track-color.js';
import { MV_STATUS_STYLE, mvStatusCategory } from '../mediaview/status-legend.js';
import { pctLabel } from './_helpers.js';

/**
 * The masked grey. Same value status-legend.js paints its "⊘ Maskiert"
 * swatch with, so the stroke and its legend row agree.
 */
export const VP_MASKED_STROKE = '#64748b';

/** Plate ground. Dark and translucent, readable over any picture. */
export const VP_PLATE_BG = 'rgba(8,12,18,0.85)';

/** Fallback stroke when a detection carries no track number yet. */
const _FALLBACK_STROKE = '#22c55e';

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
  const parts = [num, cls, pct].filter(Boolean);
  const body = parts.join(' · ');
  // A masked box says so in words as well as in colour: the grey alone
  // has been read as "low confidence" before.
  const tail = cat === 'masked' && body ? `${body} · gefiltert` : body;
  return `${marker ? `${marker} ` : ''}${tail}`.trim();
}

/**
 * Resolve every paint parameter for one detection or sample.
 *
 * @param {object} det  { verdict|status, score, label, track_num }
 * @param {object} [opts]
 * @param {string} [opts.colour]    explicit stroke, else the track hue
 * @param {boolean} [opts.selected] thicker stroke while focused
 * @param {number} [opts.holdMul]   hold-time fade multiplier, 0..1
 * @returns {{cat, stroke, dash, alpha, width, marker, plateText,
 *   plateBg, plateFg}}
 */
export function resolveBox(det, opts = {}) {
  const d = det || {};
  // Recorded samples carry `status`, live detections carry `verdict`.
  // Both vocabularies fold through the same categoriser.
  const cat = mvStatusCategory(d.verdict != null ? d.verdict : d.status);
  const style = MV_STATUS_STYLE[cat] || MV_STATUS_STYLE.confirmed;
  const masked = cat === 'masked';
  const base = opts.colour || liveTrackColor(d.track_num) || _FALLBACK_STROKE;
  const stroke = masked ? VP_MASKED_STROKE : base;
  const hold = opts.holdMul == null ? 1 : opts.holdMul;
  return {
    cat,
    stroke,
    dash: style.dash,
    alpha: style.alpha * hold,
    width: opts.selected ? 5 : 3,
    marker: style.marker,
    plateText: plateText(d, cat),
    plateBg: VP_PLATE_BG,
    plateFg: stroke,
  };
}
