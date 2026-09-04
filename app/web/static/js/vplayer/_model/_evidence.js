// ─── vplayer/_model/_evidence.js ───────────────────────────────────────────
// PURE. The numbers behind each verdict — the half of readiness that is
// not "which state" but "on what grounds".
//
// A state that only has a different colour is labelled, not designed:
// „nichts gefunden" without saying what the bar was is unactionable, and
// „keine Quelle" without a reason is a shrug. Everything below is read
// off what the backend genuinely writes; nothing here invents a field.
//
// WHERE EACH NUMBER COMES FROM:
//
//   tracks.gates          tracking_worker/_payload.py, sidecar schema 4.
//                         `min_confidence` is the spawn floor the worker
//                         actually applied to THIS clip (per-camera
//                         overrides resolved), `raw_floor` the detector
//                         threshold below which a box is not even
//                         returned for association.
//   tracks.built_at       when that walk finished. The tell that the
//                         answer is an answer and not a gap.
//   whole_clip.detections camera_runtime/_clip_tally.py — one row per
//                         subject the LIVE tracker held, with its best
//                         score. A DIFFERENT run from the sidecar's, so
//                         it is labelled as the live value, never mixed
//                         into the sidecar's own numbers.
//   item.detections       the trigger frame alone.
//   status / encode_error the recorder's terminal verdict.
//
// No DOM, no fetch, no module state.

import { normalizeBox } from '../../core/box-model.js';

/** Highest finite `score` in a list of detection-shaped rows. */
function _bestScore(list) {
  let best = null;
  for (const d of Array.isArray(list) ? list : []) {
    const s = d && typeof d.score === 'number' ? d.score : NaN;
    if (Number.isFinite(s) && (best === null || s > best)) best = s;
  }
  return best;
}

/** `2026-08-30T14:35:02` → `14:35`. Anything else → null. */
function _hhmm(stamp) {
  const m = /T(\d{2}:\d{2})/.exec(String(stamp || ''));
  return m ? m[1] : null;
}

/** Does this event point at a video at all? The reindex route refuses
 *  without one (routes/tracking.py: „Event nicht gefunden oder ohne
 *  Video"), so it decides whether a rebuild may even be offered. */
export function hasVideo(item) {
  return !!(item && (item.video_relpath || item.video_url));
}

/** Trigger-frame detections that actually carry a drawable box. */
export function drawableTriggerDets(item) {
  const list = (item && item.detections) || [];
  return list.filter((d) => d && normalizeBox(d.bbox));
}

/**
 * The gate the indexer applied, and the best score the clip ever
 * produced — the two numbers that turn „nichts gefunden" into a verdict
 * a person can act on.
 *
 * `best` is deliberately attributed: it is the LIVE pipeline's own
 * high-water mark for this clip, not something the sidecar reported.
 * The two runs are different passes and must not be presented as one.
 *
 * @param {object} item                the mediathek event item
 * @param {object} tracks              the sidecar (already known to exist)
 * @returns {{threshold: number|null, rawFloor: number|null,
 *            best: number|null, bestFrom: string|null,
 *            checkedAt: string|null}}
 */
export function gateEvidence(item, tracks) {
  const gates = (tracks && tracks.gates) || null;
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const clip = _bestScore(item && item.whole_clip && item.whole_clip.detections);
  const trig = clip === null ? _bestScore(item && item.detections) : null;
  return {
    threshold: gates ? num(gates.min_confidence) : null,
    rawFloor: gates ? num(gates.raw_floor) : null,
    best: clip !== null ? clip : trig,
    bestFrom: clip !== null ? 'clip' : trig !== null ? 'trigger' : null,
    checkedAt: _hhmm(tracks && tracks.built_at),
  };
}

/**
 * Why there is no sidecar and nothing drawable — and whether a rebuild
 * could possibly help.
 *
 * The rebuild flag is not cosmetic. POST /api/tracking/reindex/<id>
 * answers 404 for an event with no video, so offering the button on one
 * is offering a failure; the honest face says what is missing instead.
 *
 * `sub` is free-form backend text (the recorder's own German), which is
 * a sentence rather than a value and therefore never a chip: a
 * three-line string in a slot built for „50 %" is a layout, not a fact.
 *
 * @param {object} item
 * @returns {{note: string, facts: Array<{label: string, value: string}>,
 *            sub: string|null, rebuildable: boolean}}
 */
export function missingReason(item) {
  const ev = item || {};
  const failed = ev.status === 'error' || ev.stage === 'failed';
  const video = hasVideo(ev);
  if (failed) {
    return {
      note: 'Die Umwandlung dieses Clips ist fehlgeschlagen — es gibt nichts zu durchsuchen.',
      facts: [],
      sub: ev.encode_error ? String(ev.encode_error) : null,
      rebuildable: video,
    };
  }
  if (!video) {
    return {
      note: 'Zu diesem Ereignis liegt keine Videodatei — die Nachanalyse hat nichts zum Ablaufen.',
      facts: [{ label: 'Videodatei', value: 'fehlt' }],
      sub: null,
      rebuildable: false,
    };
  }
  const dets = (ev.detections || []).length;
  if (dets) {
    return {
      note: 'Keine der Erkennungen im Auslöse-Bild trägt einen Kasten.',
      facts: [{ label: 'Erkennungen ohne Kasten', value: String(dets) }],
      sub: null,
      rebuildable: true,
    };
  }
  return {
    note: 'Für diesen Clip wurde nie eine Feinspur gebaut.',
    facts: [],
    sub: null,
    rebuildable: true,
  };
}
