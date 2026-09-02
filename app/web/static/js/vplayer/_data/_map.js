// ─── vplayer/_data/_map.js ─────────────────────────────────────────────────
// PURE. One backend live frame → the shape the panel and the overlays
// read. Split from live.js so it can be unit-tested at all: live.js
// imports the poll loop, which publishes a `window` bridge at module
// scope and therefore cannot be loaded outside a browser.
//
// Everything here degrades rather than throwing. The backend's response
// is growing concurrently with this player, so a key that is not there
// yet must produce a labelled gap in one row — never an exception, and
// never a panel that renders empty because one field was missing.

import { normalizeBox } from '../_geometry.js';
import { resolveBox } from '../_box-model.js';

/**
 * Verdicts that mean "this detection was NOT acted on".
 *
 * The vocabulary is production's own gate sequence, which the live
 * endpoint reports so every box can say which gate decided it:
 *   pass          at or above the label's spawn threshold
 *   tentative     holds its track, does not count toward confirmation
 *   no_track      the tracker dropped it
 *   filtered      class not in the object filter
 *   masked        inside an exclusion mask
 *   outside_zone  outside every inclusion zone
 */
export const DISCARDED_VERDICTS = new Set(['filtered', 'masked', 'outside_zone', 'no_track']);

/** German for each discard verdict — why this box was not acted on. */
export const DISCARD_REASON_DE = {
  filtered: 'Klasse nicht im Objekt-Filter',
  masked: 'In einer Ausschluss-Maske',
  outside_zone: 'Außerhalb jeder Erkennungs-Zone',
  no_track: 'Vom Tracker verworfen · keine Zuordnung',
  tentative: 'Unter der Spawn-Schwelle · hält nur die Spur',
};

/**
 * PURE: one backend detection → one painter-ready record.
 *
 * The untouched detection is kept alongside, so a panel row can still
 * surface fields this mapping does not know about. A backend that grows
 * a field must not have it silently dropped here.
 */
export function mapDetection(d) {
  const det = d || {};
  return {
    raw: det,
    box: normalizeBox(det.bbox),
    label: det.label || '',
    score: det.score,
    trackNum: det.track_num == null ? null : det.track_num,
    verdict: det.verdict || null,
    // The backend's own reason wins; the table is the fallback for a
    // verdict it did not explain.
    reason: det.reason || DISCARD_REASON_DE[det.verdict] || null,
    discarded: DISCARDED_VERDICTS.has(det.verdict),
    style: resolveBox(det),
  };
}

/**
 * PURE: one backend frame → the shape the panel and overlays read.
 */
export function mapFrame(data) {
  const d = data || {};
  const detections = Array.isArray(d.detections) ? d.detections.map(mapDetection) : [];
  return {
    ok: d.ok !== false,
    frameSize: d.frame_size || null,
    snapshot: d.snapshot || null,
    detections,
    kept: detections.filter((x) => !x.discarded),
    discarded: detections.filter((x) => x.discarded),
    diag: d.diag || null,
    trace: Array.isArray(d.decision_trace) ? d.decision_trace : [],
    raw: d,
  };
}
