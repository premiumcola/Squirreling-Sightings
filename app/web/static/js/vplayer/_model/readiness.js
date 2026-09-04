// ─── vplayer/_model/readiness.js ───────────────────────────────────────────
// PURE. What do we actually know about this clip, and how good is it?
//
// The player had no answer to that question, and every surface suffered
// the same way: a clip with no `tracks.json` painted nothing, listed
// nothing on the rail, and said nothing about why. The operator's report
// was „warum ist da überall nichts" — and the honest answer was that the
// overlay only ever read one of the three sources this system stores.
//
// THE THREE SOURCES, and what each can and cannot answer:
//
//   tracks.json      per-frame geometry. The only source that can put a
//                    box on a moving subject, and the one the lane
//                    colours and numbering come from.
//   whole_clip       one row per subject over the WHOLE recording, with
//                    first/last seconds — but NO geometry. It can fill a
//                    lane; it can never draw a box.
//   event.detections the trigger frame alone. It HAS boxes, but for one
//                    instant, so painting them during playback would
//                    claim the subject is somewhere it has left.
//
// That last rule is not new — it is what the legacy renderer worked out
// and encoded in `_drawNoTracksBranch`: show the trigger box while
// paused, clear it the moment the clip runs. This module states it once
// so both the painter and the panel obey the same rule instead of each
// re-deriving it.
//
// No DOM, no fetch, no module state — so every rule below is a unit test
// rather than a browser smoke.

import { normalizeBox } from '../../core/box-model.js';

/** Per-frame geometry: the sidecar ran and found subjects. */
export const CLIP_READY = 'ready';
/** No sidecar, but the trigger frame carries drawable boxes. */
export const CLIP_COARSE = 'coarse';
/** The indexer ran and confirmed nothing. An answer, not a gap. */
export const CLIP_EMPTY = 'empty';
/** No sidecar and nothing drawable. The one state that offers a rebuild. */
export const CLIP_MISSING = 'missing';
/** The sidecar request has not come back yet. */
export const CLIP_PENDING = 'pending';

/** What can be drawn, which is a different question from what is known. */
export const GEOM_PER_FRAME = 'per-frame';
export const GEOM_TRIGGER = 'trigger';
export const GEOM_NONE = 'none';

/** Trigger-frame detections that actually carry a drawable box. */
function _drawableTriggerDets(item) {
  const list = (item && item.detections) || [];
  return list.filter((d) => d && normalizeBox(d.bbox));
}

/**
 * Classify one clip's evidence.
 *
 * `tracks` follows mediathek/bbox-overlay/fetcher.js's contract exactly:
 * `undefined` while the request is in flight, `null` when the sidecar is
 * absent (404 or error), and an object once it lands — whose `tracks`
 * array may legitimately be empty.
 *
 * Those three are NOT the same state and must never render the same way.
 * Collapsing "not fetched yet", "no sidecar exists" and "the indexer
 * found nothing" into one blank picture is precisely the defect.
 *
 * @param {object} item                   the mediathek event item
 * @param {object|null|undefined} tracks  the sidecar, per that contract
 * @returns {{state: string, geometry: string, trigger: Array, note: string|null}}
 */
export function clipReadiness(item, tracks) {
  if (tracks === undefined) {
    return { state: CLIP_PENDING, geometry: GEOM_NONE, trigger: [], note: null };
  }
  const list = tracks && Array.isArray(tracks.tracks) ? tracks.tracks : null;
  if (list && list.length) {
    return { state: CLIP_READY, geometry: GEOM_PER_FRAME, trigger: [], note: null };
  }
  if (list) {
    // The sidecar exists and holds nothing. The trigger box is deliberately
    // NOT offered as a consolation here: the indexer walked the whole clip
    // at a lower floor than the live pipeline and still found nothing, so a
    // single trigger-frame rectangle would contradict the more thorough
    // answer we already have.
    return {
      state: CLIP_EMPTY,
      geometry: GEOM_NONE,
      trigger: [],
      note: 'Die Nachanalyse hat in diesem Clip nichts gefunden.',
    };
  }
  const trigger = _drawableTriggerDets(item);
  if (trigger.length) {
    return {
      state: CLIP_COARSE,
      geometry: GEOM_TRIGGER,
      trigger,
      note: 'Keine Feinspur — die Kästen stammen aus dem Auslöse-Bild und stehen still.',
    };
  }
  return {
    state: CLIP_MISSING,
    geometry: GEOM_NONE,
    trigger: [],
    note: 'Für diesen Clip gibt es keine Feinspur.',
  };
}

/**
 * May a trigger-frame box be on screen right now?
 *
 * Only while the clip is not running. A trigger detection is one instant;
 * leaving it painted through playback claims the subject is somewhere it
 * left seconds ago, which is worse than showing nothing. The legacy
 * renderer reached the same conclusion — this is that rule, stated once.
 */
export function triggerBoxVisible(readiness, playing) {
  return readiness.geometry === GEOM_TRIGGER && !playing;
}
