// ─── vplayer/timeline/_lanes.js ────────────────────────────────────────────
// One row per detected object, above the rail: a thick dot at the first
// detection and a bar for as long as the track was held.
//
// COLOUR IS THE OBJECT, LINE STYLE IS THE STATUS. The hue is stamped by
// whichever basis built the lane and only fallen back on here: a sidecar
// lane is coloured by core/track-color.js keyed on the track number, so
// the same subject is the same colour in the lane, in its box and in the
// panel row; a clip-aggregate lane is coloured by CLASS instead
// (_basis.js), because its track ids come from a different tracker run
// and reusing the numbering palette would claim an identity it has not
// got. The texture comes from the model's per-sample segments, so a
// dashed stretch means something specific — weak, predicted or masked —
// rather than "roughly uncertain".
//
// Each segment paints as its own overlay strip on top of the bar. That
// is the only way a viewer learns WHY part of a track is dashed, and it
// is the piece a rewrite drops most easily because nothing else
// references it.

import { subjectLabel } from '../../core/clip-species.js';
import { esc } from '../../core/dom.js';
import { liveTrackColor } from '../../core/track-color.js';
import { spanLabel } from '../_helpers.js';
import { pctOf } from './_model.js';

const _pct = (v) => `${(v * 100).toFixed(3)}%`;

/** Segments worth painting: a confirmed run is the bar's own texture. */
const _TEXTURED = new Set(['weak', 'predicted', 'masked']);

function _segmentsHtml(lane, duration) {
  return lane.segments
    .filter((s) => _TEXTURED.has(s.status))
    .map((s) => {
      const t0 = pctOf(s.t0, duration);
      const t1 = pctOf(s.t1, duration);
      const w = Math.max(0, t1 - t0);
      return (
        `<span class="vp-tl-seg" data-status="${esc(s.status)}" ` +
        `style="left:${_pct(t0)};width:${_pct(w)}"></span>`
      );
    })
    .join('');
}

/**
 * The name for a lane, prefixed with its track number when it has one.
 *
 * A named bird is called by its species, so two birds in one clip read
 * as two birds rather than as "Vogel" twice — the same rule the objects
 * list and the Mediathek card badge follow. core/clip-species.js owns
 * it; this does not restate it. A sidecar lane carries no species and
 * comes back out with the plain German class name it always had.
 */
function _laneLabel(lane) {
  const cls = subjectLabel(lane.label, lane.species) || 'Objekt';
  return lane.trackNum == null ? cls : `#${lane.trackNum} ${cls}`;
}

function _laneHtml(lane, duration) {
  const colour = lane.colour || liveTrackColor(lane.trackNum);
  const dot = pctOf(lane.dotT, duration);
  const t0 = pctOf(lane.barT0, duration);
  const t1 = pctOf(lane.barT1, duration);
  const title = `${_laneLabel(lane)} · ${spanLabel(lane.barT0, lane.barT1)}`;
  return (
    `<div class="vp-tl-lane" data-status="${esc(lane.status)}" ` +
    `data-track="${lane.trackNum == null ? '' : esc(String(lane.trackNum))}" ` +
    `style="--vp-lane-colour:${esc(colour)}" title="${esc(title)}">` +
    // THE TIME AXIS IS ITS OWN BOX. The bar and the dot are positioned
    // as a percentage of it, so it — not the whole row — has to be the
    // element the label is beside rather than on top of. Without this
    // wrapper a lane whose subject stayed to the end of the clip has a
    // bar running the full width and the label printed straight through
    // it, which is what „#2 Katze" over its own green bar was.
    `<span class="vp-tl-lane-track">` +
    `<span class="vp-tl-bar" style="left:${_pct(t0)};width:${_pct(Math.max(0, t1 - t0))}">` +
    `${_segmentsHtml(lane, duration)}</span>` +
    // The dot is painted after the bar so a single-sample track — whose
    // bar has no width at all — still shows something.
    `<span class="vp-tl-dot" style="left:${_pct(dot)}"></span>` +
    `</span>` +
    `<span class="vp-tl-lane-label">${esc(_laneLabel(lane))}</span>` +
    `</div>`
  );
}

/** Render every lane. Empty string when there is nothing to show. */
export function lanesHtml(model) {
  if (!model.lanes.length) return '';
  return model.lanes.map((lane) => _laneHtml(lane, model.duration)).join('');
}
