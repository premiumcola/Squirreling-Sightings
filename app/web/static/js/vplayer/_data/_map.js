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

import { clipSpeciesNames } from '../../core/clip-species.js';
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

/** Detected, but below the spawn threshold — so it starts no track.
 *
 * ITS OWN BUCKET, and the reason is the operator's report: the panel
 * said "1 übernommen" while nothing at all was drawn on the picture. A
 * tentative detection is not discarded (the tracker still uses it to
 * sustain an existing track, which is why it was never in
 * DISCARDED_VERDICTS) — but it is not "übernommen" either. It produced
 * no track, and a box on this picture comes from a track.
 *
 * The asymmetry was already visible in this file: DISCARD_REASON_DE has
 * carried an entry for `tentative` all along — „Unter der Spawn-Schwelle
 * · hält nur die Spur" — while the set beside it did not. The table knew
 * what the counter did not.
 */
export const TENTATIVE_VERDICTS = new Set(['tentative']);

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
    // The cascade stage that produced the label. Joined against the
    // frame's `models` table to name the actual model file; on its own
    // it still names the stage, which is what a pre-table payload has.
    model: det.model || null,
    verdict: det.verdict || null,
    // The backend's own reason wins; the table is the fallback for a
    // verdict it did not explain.
    reason: det.reason || DISCARD_REASON_DE[det.verdict] || null,
    discarded: DISCARDED_VERDICTS.has(det.verdict),
    tentative: TENTATIVE_VERDICTS.has(det.verdict),
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
    // Three buckets, not two. `kept` is what actually became something.
    kept: detections.filter((x) => !x.discarded && !x.tentative),
    tentative: detections.filter((x) => x.tentative),
    discarded: detections.filter((x) => x.discarded),
    diag: d.diag || null,
    // Stage → {file, sha256}, sent once per payload rather than on every
    // box. The SAME shape as an event's provenance.models, so one
    // modelLabel() join serves the live surface and a recorded clip.
    // A payload from before this table existed simply has none, and
    // every row then names its stage without a file.
    models: d.models || null,
    trace: Array.isArray(d.decision_trace) ? d.decision_trace : [],
    raw: d,
  };
}

/**
 * PURE: one `whole_clip.detections` row → one panel row.
 *
 * `num` and `colour` stay NULL, deliberately. The `#N` chip and the
 * lane colour exist so a row, its lane on the timeline and its box on
 * the picture are visibly the same subject — and all three of those
 * read the SIDECAR's numbering. This block comes from the live
 * tracker's own pass, whose `track_id` space is a different run of a
 * different tracker; joining the two would number a row after a lane
 * that shows something else. No number is honest, a wrong one is not.
 */
function _clipRows(list) {
  return list.map((d, i) => ({
    key: `clip:${i}`,
    basis: 'clip',
    num: null,
    label: d.label || '',
    colour: null,
    score: d.score,
    model: d.model || null,
    species: d.species || null,
    t0: d.first_s == null ? null : d.first_s,
    t1: d.last_s == null ? null : d.last_s,
  }));
}

/** PURE: one tracks.json track → one panel row. */
function _sidecarRows(list) {
  return list.map((tr) => {
    const samples = tr.samples || [];
    return {
      key: `track:${tr._num}`,
      basis: 'sidecar',
      num: tr._num == null ? null : tr._num,
      label: tr.label || '',
      colour: tr.color || null,
      score: tr.best_score == null ? tr.score : tr.best_score,
      // Per-detection model attribution is a cascade STAGE token and
      // is recorded per TRACK, not per sample.
      model: tr.model || null,
      // The sidecar names a class, never a species — nothing in
      // tracks.json carries one.
      species: null,
      t0: samples.length ? samples[0].t : null,
      t1: samples.length ? samples[samples.length - 1].t : null,
    };
  });
}

/**
 * PURE: one trigger-frame detection → one panel row.
 *
 * `species` stays NULL even though the detection often carries one.
 * This branch is what every clip recorded before the whole-clip
 * aggregate falls back to, and those clips must render exactly as they
 * always have. Naming the species here would be a change to the whole
 * existing archive smuggled in under a feature about new clips — a
 * one-word change if it is ever wanted deliberately.
 */
function _frameRows(dets) {
  return dets.map((d, i) => ({
    key: `det:${i}`,
    basis: 'frame',
    num: null,
    label: d.label || '',
    colour: null,
    score: d.score,
    model: d.model || null,
    species: null,
    // A raw detection is one frame. Saying so beats inventing a span.
    t0: null,
    t1: null,
  }));
}

/**
 * PURE: the detected-object rows for an item, newest schema first.
 *
 * THREE SOURCES, ONE LIST. They are not interchangeable and are never
 * merged — the list is built from exactly one of them, and every row
 * says which in `basis`, so a reader can tell what it is looking at:
 *
 *   `clip`     `whole_clip.detections` — one row per subject over the
 *              WHOLE recording, from the live tracker's own pass.
 *              Preferred, because it is the only source that answers
 *              "what was in this clip" rather than "what was in one
 *              frame of it", and the only one carrying species.
 *   `sidecar`  tracks.json — a post-clip re-walk. Carries timing and
 *              the numbering the timeline and boxes share, but no
 *              species. The answer for every event recorded before
 *              `whole_clip` existed.
 *   `frame`    `event.detections` — the trigger frame alone. No span,
 *              because it never observed one.
 *
 * MIXING THEM WOULD LIE. `whole_clip` is spawn-gated — it holds what
 * the live pipeline acted on. The sidecar walks at the raw floor
 * (`tracking_worker/__init__.py`, `replay/_run.py`), which sees more,
 * at lower confidence, on purpose. One list drawn from both would put
 * rows the pipeline believed next to rows it rejected with nothing to
 * tell them apart, and any count taken off it would be meaningless.
 */
export function objectRowsFor(item, tracks) {
  const clip = item?.whole_clip?.detections;
  if (Array.isArray(clip) && clip.length) return _clipRows(clip);
  const list = tracks && Array.isArray(tracks.tracks) ? tracks.tracks : null;
  if (list && list.length) return _sidecarRows(list);
  return _frameRows((item && item.detections) || []);
}

/**
 * PURE: the one-line footnote under the object list, or null.
 *
 * Only the `clip` basis ever has anything to say, so an event recorded
 * before `whole_clip` existed renders byte-identically to before.
 *
 * It says at most three things, each only when true:
 *   · that these rows cover the whole recording rather than one frame;
 *   · that a cap bit, so the list is PARTIAL — `truncated` must never
 *     be allowed to read as completeness;
 *   · any species the tally identified that no visible row names. That
 *     is only reachable when the row caps refused a subject whose
 *     species still made the species list, and it is exactly the case
 *     where a silent list would hide the answer the operator wanted.
 *
 * @returns {string|null}
 */
export function objectsNote(rows, item) {
  const clip = item?.whole_clip;
  if (!clip || !Array.isArray(rows) || !rows.length || rows[0].basis !== 'clip') return null;
  const parts = ['Ganzer Clip'];
  if (clip.truncated) parts.push('Liste gekürzt');
  const named = new Set(rows.map((r) => r.species).filter(Boolean));
  const missing = clipSpeciesNames(item).filter((name) => !named.has(name));
  if (missing.length) parts.push(`auch: ${missing.join(', ')}`);
  return parts.join(' · ');
}
