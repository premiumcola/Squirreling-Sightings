// ─── vplayer/timeline/_basis.js ────────────────────────────────────────────
// PURE. WHICH population the rail draws, and how a whole-clip row becomes
// something _model.js can lay out.
//
// THE BUG THIS CLOSES. The rail was fed `data.tracks.tracks` and nothing
// else, while the objects list below it has preferred `whole_clip` since
// 65a51e5. A clip whose sidecar confirmed nothing but whose aggregate
// holds subjects therefore listed rows in the panel with an empty grey
// line above them — "die farbigen Markierungen auf der Playline sind
// nicht vorhanden", with "Vogel 57 %" printed directly underneath.
//
// ONE BASIS PER RENDER, NEVER BOTH. The two populations are not
// interchangeable and are never merged into one lane list. `whole_clip`
// is spawn-gated — it is what the live pipeline ACTED on. The sidecar
// walks at the raw floor (`tracking_worker/__init__.py`, `replay/_run.py`)
// and deliberately sees more, at lower confidence. Lanes drawn from both
// would put subjects the pipeline believed next to ones it rejected with
// nothing to tell them apart, and a wrongly-attributed lane is worse than
// a missing one.
//
// THE PRECEDENCE IS THE OPPOSITE OF THE OBJECT LIST'S, ON PURPOSE.
// `_data/_map.js::objectRowsFor` prefers the clip aggregate, because a
// LIST wants the completest answer to "what was in this clip" and only
// the aggregate carries species. A RAIL wants timing: the sidecar holds
// per-sample `t`, `source` and `score`, so it can say WHEN a subject was
// weak or predicted, and its `_num` / colour are the ones the boxes on
// the picture and the `#N` chips already share. The aggregate has two
// timestamps and no per-frame anything. So the rail takes the sidecar
// whenever there is one and falls back to the aggregate — which is
// exactly the case the operator photographed.

import { classColor } from '../../core/class-colors.js';

/** The sidecar's tracks — per-sample timing, shared numbering. */
export const TL_BASIS_SIDECAR = 'sidecar';
/** `whole_clip.detections` — one row per subject, two timestamps. */
export const TL_BASIS_CLIP = 'clip';
/** Neither key held anything. The rail draws no lanes. */
export const TL_BASIS_NONE = 'none';
/** The rolling live buffer. Not a recorded population at all. */
export const TL_BASIS_LIVE = 'live';

/**
 * PURE: one `whole_clip.detections` row → one pseudo-track, or null.
 *
 * The row (see `camera_runtime/_clip_tally.py`) carries `first_s`,
 * `last_s`, `label`, `species`, `score`, `track_id`, `model` and
 * `frames`. Only the first two place it on a rail, so a row without a
 * usable `first_s` produces no lane rather than a lane at zero.
 *
 * WHAT THE SYNTHESISED SAMPLES DELIBERATELY OMIT. `classifySample` reads
 * four fields off a sample, and getting either of the two omitted ones
 * wrong would paint a bar that states something false:
 *
 *   · `bbox` — LEFT OUT. Without it the mask probe never runs, so a clip
 *     lane can never land in the `masked` bucket. That is correct twice
 *     over: the aggregate is fed the detections that SURVIVED the masks
 *     (`_clip_tally.add_frame`), so nothing in it is masked; and the row's
 *     single bbox is its best-scoring FRAME's, which says nothing about
 *     where the subject stood at `first_s` or `last_s`. Painting a lane
 *     "masked" tells the operator their mask is not working — it must
 *     never be said by accident.
 *   · `source` — SET to 'detect'. It is in `_model.js`'s `_DETECTED` set,
 *     so the lane cannot fall into the `predicted` bucket. Honest: every
 *     row here is a detection the pipeline kept, never a box the tracker
 *     carried forward.
 *
 * `score` IS carried, and is the row's best over the whole clip. So a
 * subject that never once beat the spawn threshold reads `weak` for its
 * whole bar — a true statement, and the one case where a clip lane
 * SHOULD be dashed. Rows the wildlife stage appends after association
 * are not spawn-gated at all, which is exactly where this fires.
 */
function _trackForClipRow(row) {
  // Number.isFinite WITHOUT a Number() coercion, deliberately: the
  // backend writes a rounded float, and `Number(null)` is 0 — coercing
  // would give a row whose `first_s` is missing a lane pinned to the
  // start of the clip, which is the one placement that reads as a fact.
  const t0 = row?.first_s;
  if (!Number.isFinite(t0)) return null;
  const last = row.last_s;
  const t1 = Number.isFinite(last) && last > t0 ? last : t0;
  const label = row.label || '';
  const at = (t) => ({ t, score: row.score, source: 'detect' });
  return {
    // No number. The `#N` chip, the box strokes and the sidecar's lanes
    // all read the SIDECAR's numbering; this row's `track_id` comes from
    // the live tracker's own run and joining the two would number a lane
    // after something else. Same rule `_data/_map.js::_clipRows` follows.
    _num: null,
    label,
    species: row.species || null,
    // Colour by CLASS, from the palette core/class-colors.js already owns
    // and 00-class-tokens.css already mirrors — not from
    // `liveTrackColor`, which keys on the sidecar's per-clip numbering.
    // Two lanes coloured out of the same palette by two different track
    // spaces would read as the same subject. As a bonus the two palettes
    // cannot collide: LIVE_PALETTE deliberately excludes green, which is
    // exactly where `bird` sits here.
    color: classColor(label),
    // One sample for a one-frame subject, so `_laneFor` keeps its dot and
    // gives it a zero-length bar; two for a span, which `segmentTrack`
    // collapses into a single honest run from `first_s` to `last_s`.
    samples: t1 > t0 ? [at(t0), at(t1)] : [at(t0)],
  };
}

/**
 * PURE: the population this render draws, and the tracks to draw.
 *
 * @param {object} item     the event, possibly widened by loadRecorded
 * @param {object} tracks   the tracks.json sidecar, or null
 * @returns {{basis: string, tracks: Array}}
 */
export function timelineBasis(item, tracks) {
  const sidecar = tracks && Array.isArray(tracks.tracks) ? tracks.tracks : null;
  if (sidecar && sidecar.length) return { basis: TL_BASIS_SIDECAR, tracks: sidecar };
  const clip = item?.whole_clip?.detections;
  if (Array.isArray(clip) && clip.length) {
    const built = clip.map(_trackForClipRow).filter(Boolean);
    if (built.length) return { basis: TL_BASIS_CLIP, tracks: built };
  }
  // An event predating the aggregate has neither key, and lands here
  // with an empty list — the same argument the rail was given before
  // any of this existed, so it renders exactly as it always has.
  return { basis: TL_BASIS_NONE, tracks: [] };
}
