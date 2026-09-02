// ─── vplayer/panels/_helpers.js ────────────────────────────────────────────
// PURE row formatters, shared by both panel families.
//
// THIS FILE AND _geometry.js ARE THE ONLY TWO PLACES A BACKEND FIELD
// NAME APPEARS. That is deliberate: the backend these panels read is
// growing alongside them, so when a key is renamed or finally lands,
// exactly one file changes.
//
// EVERY ROW DEGRADES. A field that is not there yet renders as a
// labelled placeholder row, never as a blank, never as "undefined", and
// never as a thrown error that takes the whole fold with it. Two of the
// fields below are known-missing today and are marked as such.

import { PLACEHOLDER, ageLabel, pctLabel, valueOr } from '../_helpers.js';

/**
 * The cascade STAGE a detection's label came from.
 *
 * This is what the backend actually reports per detection — a stage
 * token, not a model file. The file name (coco_ssd vs efficientdet) is
 * only recorded per EVENT, in provenance.models[stage].file, so naming
 * the actual model needs the join in modelLabel() below and is simply
 * unavailable on the live surface.
 */
export const MODEL_STAGE_DE = {
  detector: 'Objekt-Detektor',
  bird_classifier: 'Vogel-Klassifikator',
  wildlife_classifier: 'Wildtier-Klassifikator',
  cat_reid: 'Katzen-Wiedererkennung',
  person_reid: 'Personen-Wiedererkennung',
};

/**
 * Which model produced this label.
 *
 * @param {string|null} stage        detection.model — a stage token
 * @param {object} [models]          provenance.models, when available
 * @returns {string} the stage in German, with the model FILE appended
 *   when the event's provenance can supply it. A pre-provenance clip,
 *   or the live view (whose rows carry no stage at all), degrades to
 *   the placeholder rather than to a guess.
 */
export function modelLabel(stage, models) {
  if (!stage) return PLACEHOLDER;
  const human = MODEL_STAGE_DE[stage] || stage;
  const file = models && models[stage] && models[stage].file;
  return file ? `${human} · ${file}` : human;
}

/**
 * The TPU busy ratio, as a percent.
 *
 * The backend reports a 0..1 fraction over a ~10 s window, capped at
 * 1.0. A camera with no stage on the TPU reports null rather than 0 —
 * those are different facts and must not render the same way.
 *
 * @param {object} tpu   status.tpu, or one camera's tpu_util
 * @returns {string}
 */
export function tpuBusyLabel(tpu) {
  if (!tpu || typeof tpu !== 'object') return PLACEHOLDER;
  const busy = tpu.busy;
  if (typeof busy !== 'number') return PLACEHOLDER;
  return pctLabel(busy);
}

/** Pull one camera's utilisation out of the fleet block, else the total. */
export function tpuFor(status, camId) {
  const tpu = status && status.tpu;
  if (!tpu) return null;
  const perCam = tpu.cameras && camId ? tpu.cameras[camId] : null;
  return perCam || tpu.total || null;
}

/** Compute device as a short chip: TPU, CPU or off. */
export function computeChip(modes) {
  const device = modes?.inference?.device;
  if (device === 'tpu') return 'TPU';
  if (device === 'cpu') return 'CPU';
  if (device === 'off') return 'Erkennung aus';
  return PLACEHOLDER;
}

/** One track row's display fields, all of them degrading independently. */
export function trackRow(t) {
  const track = t || {};
  return {
    num: track.id == null ? null : track.id,
    label: track.label || '',
    state: track.state || PLACEHOLDER,
    age: ageLabel(track.age_s),
    idle: ageLabel(track.idle_s),
    misses: Number.isFinite(track.misses) ? String(track.misses) : PLACEHOLDER,
    // null IoU means the newborn DISTANCE gate matched, not that the
    // boxes failed to overlap. Rendering it as "0 %" would say the
    // opposite of what happened.
    iou: typeof track.last_iou === 'number' ? pctLabel(track.last_iou) : PLACEHOLDER,
    score: track.score == null ? PLACEHOLDER : pctLabel(track.score),
    model: modelLabel(track.model),
  };
}

/** A labelled row. `tone` is optional and purely presentational. */
function _row(key, value, tone) {
  return { key, value: value == null ? PLACEHOLDER : value, tone: tone || null };
}

/** Zones/masks: how many, and are they actually in play. */
function _polyValue(block) {
  if (!block || typeof block !== 'object') return PLACEHOLDER;
  const n = block.count;
  if (!Number.isFinite(n)) return PLACEHOLDER;
  return n === 0 ? 'keine' : String(n);
}

/**
 * The 'Aufnahme-Details' rows, in display order.
 *
 * Reads event.provenance, falling back to the older and narrower
 * event.recording_settings for clips recorded before provenance
 * existed — every clip in the archive from before that change has
 * `provenance: null`, and so does any recording whose snapshot threw.
 *
 * @param {object} item  the event
 * @returns {Array<{key: string, value: string, tone: string|null}>}
 */
export function provenanceRows(item) {
  const ev = item || {};
  const p = ev.provenance || null;
  const rs = ev.recording_settings || {};
  const eff = (p && p.effective) || {};
  const timing = (p && p.timing) || {};
  const models = (p && p.models) || {};

  return [
    // Known-MISSING today: nothing records which revision of a tuning
    // profile an event was recorded under. The alarm profile NAME is
    // all there is, so the row says the name and nothing more rather
    // than implying a version it cannot show.
    _row('Profil', valueOr(p?.camera?.alarm_profile)),
    _row('Rolle', valueOr(p?.camera?.role)),
    _row(
      'Rechenwerk',
      p ? (models.tpu_active ? 'TPU' : 'CPU') : PLACEHOLDER,
      models.tpu_active ? 'ok' : null,
    ),
    // The model FILE, not the stage name — the row label already says
    // which stage this is, so repeating it would fill the row without
    // answering it. Unknown file degrades to the placeholder.
    _row('Detektor', valueOr(models.detector?.file)),
    _row('Vogel-Modell', valueOr(models.bird_classifier?.file)),
    _row('ROI-Modus', valueOr(eff.roi_mode ?? eff.det_mode)),
    _row('Zonen', _polyValue(p?.zones)),
    _row('Masken', _polyValue(p?.masks)),
    _row(
      'Schwelle',
      eff.min_score == null ? valueOr(rs.conf_thresh_general) : pctLabel(eff.min_score),
    ),
    _row('Spawn-Schwelle', eff.spawn_default == null ? PLACEHOLDER : pctLabel(eff.spawn_default)),
    _row(
      'Vorlauf',
      timing.pre_roll_s == null
        ? valueOr(rs.pre_motion_seconds, 's')
        : valueOr(timing.pre_roll_s, 's'),
    ),
    _row(
      'Nachlauf',
      timing.post_roll_s == null
        ? valueOr(rs.post_motion_seconds, 's')
        : valueOr(timing.post_roll_s, 's'),
    ),
    _row('Analyse-Takt', valueOr(timing.analysis_interval_ms, 'ms')),
    _row('Build', valueOr(p?.build?.commit)),
  ];
}
