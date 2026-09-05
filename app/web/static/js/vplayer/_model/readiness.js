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
// EVERY STATE CARRIES ITS OWN GROUNDS. A verdict used to be a sentence
// and a colour, which is a label rather than an answer: „nichts
// gefunden" never said what the bar was, „keine Quelle" never said what
// was missing, and „noch nicht geladen" rendered as literally nothing —
// indistinguishable from a healthy clip. `facts` and `gate` carry the
// numbers each state genuinely has (derived in _evidence.js), and
// `rebuildable` says whether the reindex route could even succeed.
//
// No DOM, no fetch, no module state — so every rule below is a unit test
// rather than a browser smoke.

import { pctLabel } from '../../core/format.js';
import { drawableTriggerDets, gateEvidence, hasVideo, missingReason } from './_evidence.js';

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
/** The CLIP itself is still being produced. No sidecar can exist yet. */
export const CLIP_BUILDING = 'building';

/** What can be drawn, which is a different question from what is known. */
export const GEOM_PER_FRAME = 'per-frame';
export const GEOM_TRIGGER = 'trigger';
export const GEOM_NONE = 'none';

/**
 * Stages that mean the clip is still being produced.
 *
 * A MIRROR of camera_runtime/_recording/_stages.py::PENDING_STAGES, the
 * way core/camera-id.js mirrors camera_id.py. mediathek/_processing.js
 * holds the same set for the library tile and is deliberately NOT
 * imported here: it publishes a `window.x` bridge at module scope, and
 * this module is node-testable by contract (the same call _helpers.js's
 * header documents for the German age formatter). The FACE of this
 * state does import it — a panel may, a model may not — so the words
 * and the elapsed clock have exactly one source even though the
 * membership test has two.
 */
const _PENDING_STAGES = new Set(['recording', 'queued', 'encoding', 'processing']);

/**
 * Is this clip still on its way through the recorder?
 *
 * `stage` is the fine value; `status` is the coarse one every event
 * written before stages existed carries. An event with neither is
 * finished — that is `_stages.py::stage_of`'s own fallback, and it is
 * what keeps a plain `{}` out of this branch.
 */
function _isBuilding(item) {
  const stage = (item && (item.stage || item.status)) || '';
  return _PENDING_STAGES.has(stage);
}

/** A `{label, value}` chip, dropped entirely when the value is absent. */
function _fact(label, value) {
  return value == null ? null : { label, value };
}

/** The grounds for „die Nachanalyse hat nichts gefunden". */
function _emptyFacts(gate) {
  return [
    _fact('Schwelle', gate.threshold == null ? null : pctLabel(gate.threshold)),
    _fact(
      gate.bestFrom === 'trigger' ? 'bester Auslöse-Wert' : 'bester Live-Wert',
      gate.best == null ? null : pctLabel(gate.best),
    ),
    _fact('geprüft', gate.checkedAt),
  ].filter(Boolean);
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
 * The clip's OWN production outranks all three: while ffmpeg is still
 * writing it there is no video to walk, so „keine Feinspur" would blame
 * a missing sidecar for a clip that does not exist yet — and would offer
 * a rebuild the reindex route answers 404 to.
 *
 * @param {object} item                   the mediathek event item
 * @param {object|null|undefined} tracks  the sidecar, per that contract
 * @returns {{state: string, geometry: string, trigger: Array,
 *            note: string|null, facts: Array, sub: string|null,
 *            gate: object|null, rebuildable: boolean}}
 */
export function clipReadiness(item, tracks) {
  const base = {
    geometry: GEOM_NONE,
    trigger: [],
    facts: [],
    // Free-form backend prose — the recorder's own German for a failure.
    // A sentence, so never a chip; the face renders it as a second line.
    sub: null,
    gate: null,
    rebuildable: false,
  };
  if (_isBuilding(item)) {
    return {
      ...base,
      state: CLIP_BUILDING,
      note: 'Der Clip wird noch erzeugt — die Feinspur entsteht erst danach.',
    };
  }
  if (tracks === undefined) {
    return { ...base, state: CLIP_PENDING, note: 'Die Feinspur wird geladen …' };
  }
  const list = tracks && Array.isArray(tracks.tracks) ? tracks.tracks : null;
  if (list && list.length) {
    // A healthy clip carries no status line at all. Anything else would
    // be chrome that says „alles in Ordnung" over a picture that already
    // shows it.
    return { ...base, state: CLIP_READY, geometry: GEOM_PER_FRAME, note: null };
  }
  if (list) {
    // The sidecar exists and holds nothing.
    //
    // THE TRIGGER BOX IS NOW SHOWN ANYWAY, and the reversal is worth its
    // paragraph. The old rule withheld it on the argument that the
    // indexer walks the whole clip at a lower floor than the live
    // pipeline, so its silence is the more thorough answer and a single
    // rectangle would contradict it. That argument assumed the walk
    // actually looked, and clips on this box demonstrate it does not
    // always: an event whose trigger frame carries a bird at 57 % with a
    // box and an identified species — Hausrotschwanz — has an empty
    // sidecar sitting beside it, and the operator's summary of the
    // result was „Ich hab im Player noch kein einziges Mal eine Box
    // gesehen und auch hier ist 'n Vogel drin."
    //
    // He is right, and withholding evidence to protect a verdict is the
    // wrong way round: the box is a measurement, the empty sidecar is a
    // conclusion, and when they disagree the measurement is shown and
    // the disagreement is named. `triggerBoxVisible` still confines it
    // to a paused clip, so it never claims a position during playback.
    const gate = gateEvidence(item, tracks);
    const trigger = drawableTriggerDets(item);
    if (!trigger.length) {
      // No rebuild: the same walk with the same gates returns the same
      // nothing. The gates themselves are the actionable part, which is
      // why they are on screen.
      return {
        ...base,
        state: CLIP_EMPTY,
        note: 'Die Nachanalyse ist durchgelaufen und hat keine Spur bestätigt.',
        facts: _emptyFacts(gate),
        gate,
      };
    }
    // The one case that is not a judgement call but an outright
    // contradiction: the trigger scored at or above the very threshold
    // the indexer says it applied. Something other than the picture
    // decided this, and the operator is the one who can chase it.
    const contradicts =
      gate.threshold != null && gate.best != null && gate.best >= gate.threshold;
    return {
      ...base,
      state: CLIP_EMPTY,
      geometry: GEOM_TRIGGER,
      trigger,
      // WHOSE VERDICT THIS IS, said out loud. „wieso ist das Video
      // überhaupt noch bei Personen gelistet dann??" — because the label
      // comes from the live pipeline, which is what triggered the
      // recording; the sidecar is a later second opinion and its silence
      // does not retract the first one. The sentence used to omit that
      // and read as the clip's single verdict, which is why the question
      // had to be asked at all.
      note: contradicts
        ? 'Die Nachanalyse fand keine Spur — obwohl der Auslöser über der Schwelle lag.'
        : 'Die Nachanalyse fand keine Spur. Die Erkennung im Auslöse-Bild bleibt bestehen.',
      contradicts,
      facts: [
        ..._emptyFacts(gate),
        _fact('Auslöse-Kästen', String(trigger.length)),
        _fact('sichtbar', 'nur pausiert'),
      ].filter(Boolean),
      gate,
      // A walk that contradicts its own trigger frame is worth running
      // again — unlike the genuinely empty case above.
      rebuildable: contradicts && hasVideo(item),
    };
  }
  const trigger = drawableTriggerDets(item);
  if (trigger.length) {
    const best = gateEvidence(item, null).best;
    return {
      ...base,
      state: CLIP_COARSE,
      geometry: GEOM_TRIGGER,
      trigger,
      note: 'Nur das Auslöse-Bild: ein einziger Augenblick, keine Geometrie pro Bild.',
      facts: [
        _fact('Kästen', String(trigger.length)),
        _fact('sichtbar', 'nur pausiert'),
        _fact('bester Wert', best == null ? null : pctLabel(best)),
      ].filter(Boolean),
      rebuildable: hasVideo(item),
    };
  }
  const why = missingReason(item);
  return {
    ...base,
    state: CLIP_MISSING,
    note: why.note,
    facts: why.facts,
    sub: why.sub,
    rebuildable: why.rebuildable,
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
