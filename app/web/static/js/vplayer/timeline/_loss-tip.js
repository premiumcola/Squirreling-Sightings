// ─── vplayer/timeline/_loss-tip.js ─────────────────────────────────────────
// The × that marks a track the tracker LOST, and the popover explaining
// why — score against threshold, bbox against the size floor, class
// against the object filter, and the tracker's own end_reason.
//
// This is the only place in the app that answers "why did the box stop
// following it", and it is the single most easily dropped thing in a
// timeline rewrite: nothing else references it, so it disappears
// silently and nobody notices until they need it.
//
// WHEN AN × IS SHOWN. Only when the track ended EARLY — end_reason
// 'timeout' (or a legacy sidecar with none at all) and the bar ending
// more than 0.4 s before the clip does. A track that ran to the end of
// the clip was not lost, it ran out of clip, and marking that as a loss
// would put an × on almost every track.

import { esc } from '../../core/dom.js';
import { OBJ_LABEL } from '../../core/icons.js';
import { pctLabel, PLACEHOLDER } from '../_helpers.js';

/** How far before the clip end a track must stop to count as lost. */
const _EARLY_GAP_S = 0.4;

/**
 * German for each end_reason the tracker can write.
 *
 * Only 'timeout' and 'ended_at_clip' are actually emitted today —
 * app/app/tracker_core says so in its own docstring. The other three
 * are the vocabulary for per-track gates the worker does not run after
 * the detector; they are kept because a sidecar written by a future
 * version must not render as a raw token. 'merged' and 'stitched' ARE
 * written (by _merge.py and _stitch.py) but never reach here, because
 * neither is 'timeout' and so neither draws an ×.
 */
const _END_REASON_LABEL = {
  conf_drop: 'Konfidenz unter Schwelle gefallen',
  class_filter: 'Klasse aus Filter entfernt',
  bbox_too_small: 'Bbox unter Mindestgröße',
  timeout: 'Tracker verloren · keine Detektion',
  ended_at_clip: 'Spielzeit-Ende erreicht',
  merged: 'Mit einer anderen Spur zusammengeführt',
  stitched: 'An eine frühere Spur angenäht',
};

/**
 * Per-class minimum box size. Mirrors detectors/coral_object.py's
 * _LABEL_MIN_BBOX — a copy, because the browser cannot read it, and
 * therefore a place two values can drift apart. Only 'person' has a
 * floor today, so every other class always reads as passing.
 */
export const BBOX_FLOORS = {
  person: { min_h_frac: 0.15, min_area_frac: 0.02 },
};

/**
 * PURE: does this track get an × ?
 *
 * @param {object} track     tracks.json track, carrying end_reason
 * @param {number} endT      the track's last sample time
 * @param {number} duration  clip length
 */
export function shouldShowLostMarker(track, endT, duration) {
  if (!track || !(duration > 0)) return false;
  const reason = track.end_reason;
  // A legacy sidecar predates end_reason entirely; the gap rule is all
  // the evidence there is, and it is the rule that shipped.
  const known = reason === undefined || reason === null || reason === 'timeout';
  if (!known) return false;
  return duration - endT > _EARLY_GAP_S;
}

/** The confidence threshold that applied to this track's class. */
function _thresholdFor(label, rs) {
  const perClass = (rs && rs.conf_thresh_per_class) || {};
  if (Object.prototype.hasOwnProperty.call(perClass, label)) return perClass[label];
  return rs && rs.conf_thresh_general != null ? rs.conf_thresh_general : null;
}

/** Score row: the last score, and the bar it had to clear. */
function _scoreRow(track, rs) {
  const last = track.last_score;
  if (last == null) return { key: 'Score', value: PLACEHOLDER, tone: null };
  const thresh = _thresholdFor(track.label, rs);
  if (thresh == null) return { key: 'Score', value: pctLabel(last), tone: 'ok' };
  const bad = parseFloat(last) < parseFloat(thresh);
  return {
    key: 'Score',
    value: `${pctLabel(last)} ${bad ? '<' : '≥'} ${pctLabel(thresh)}`,
    tone: bad ? 'bad' : 'ok',
  };
}

/** Bbox row: the last box size against its class floor. */
function _bboxRow(track) {
  const size = track.last_bbox_size_px;
  if (!Array.isArray(size) || size.length !== 2) {
    return { key: 'Bbox', value: PLACEHOLDER, tone: null };
  }
  const floors = BBOX_FLOORS[track.label];
  let bad = false;
  if (floors) {
    const fh = track.last_bbox_frac_h == null ? 0 : track.last_bbox_frac_h;
    const fa = track.last_bbox_frac_area == null ? 0 : track.last_bbox_frac_area;
    bad = fh < floors.min_h_frac || fa < floors.min_area_frac;
  }
  return {
    key: 'Bbox',
    value: `${size[0]} × ${size[1]} px ${bad ? '✗' : '✓'}`,
    tone: bad ? 'bad' : 'ok',
  };
}

/** Class row: was this class even in the operator's object filter? */
function _classRow(track, rs) {
  const label = OBJ_LABEL[track.label] || track.label || '?';
  const filter = rs && rs.object_filter;
  if (!Array.isArray(filter)) return { key: 'Klasse', value: label, tone: null };
  const ok = filter.includes(track.label);
  return { key: 'Klasse', value: `${label} ${ok ? '✓' : '✗'}`, tone: ok ? 'ok' : 'bad' };
}

/**
 * PURE: the popover's contents for one lost track.
 *
 * @returns {{title: string, rows: Array, summary: string}}
 */
export function buildLossReport(track, rs = {}) {
  const t = track || {};
  const samples = t.samples || [];
  const span =
    samples.length >= 2 ? (samples[samples.length - 1].t - samples[0].t).toFixed(1) : '0.0';
  const reason = t.end_reason;
  const summary = reason
    ? _END_REASON_LABEL[reason] || `Grund: ${reason}`
    : 'Grund unbekannt — Re-Index empfohlen';
  return {
    title: `× Track #${t._num == null ? '?' : t._num} verloren · ${span} s`,
    rows: [_scoreRow(t, rs), _bboxRow(t), _classRow(t, rs)],
    summary,
  };
}

/** Render a report as the popover's markup. */
export function lossTipHtml(report) {
  const rows = report.rows
    .map(
      (r) =>
        `<div class="vp-tl-tip-row"><span class="vp-tl-tip-key">${esc(r.key)}:</span> ` +
        `<span class="vp-tl-tip-val${r.tone ? ` is-${r.tone}` : ''}">${esc(r.value)}</span></div>`,
    )
    .join('');
  return (
    `<div class="vp-tl-tip-title">${esc(report.title)}</div>${rows}` +
    `<div class="vp-tl-tip-summary">${esc(report.summary)}</div>`
  );
}
