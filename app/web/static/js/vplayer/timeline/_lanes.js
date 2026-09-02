// ─── vplayer/timeline/_lanes.js ────────────────────────────────────────────
// One row per detected object, above the rail: a thick dot at the first
// detection and a bar for as long as the track was held.
//
// COLOUR IS THE OBJECT, LINE STYLE IS THE STATUS. The hue comes from
// core/track-color.js keyed on the track number, so the same subject is
// the same colour in the lane, in its box and in the panel row. The
// texture comes from the model's per-sample segments, so a dashed
// stretch means something specific — weak, predicted or masked — rather
// than "roughly uncertain".
//
// Each segment paints as its own overlay strip on top of the bar. That
// is the only way a viewer learns WHY part of a track is dashed, and it
// is the piece a rewrite drops most easily because nothing else
// references it.

import { esc } from '../../core/dom.js';
import { liveTrackColor } from '../../core/track-color.js';
import { OBJ_LABEL } from '../../core/icons.js';
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

/** The German name for a lane, falling back to the raw class. */
function _laneLabel(lane) {
  const cls = lane.label ? OBJ_LABEL[lane.label] || lane.label : 'Objekt';
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
    `<span class="vp-tl-bar" style="left:${_pct(t0)};width:${_pct(Math.max(0, t1 - t0))}">` +
    `${_segmentsHtml(lane, duration)}</span>` +
    // The dot is painted after the bar so a single-sample track — whose
    // bar has no width at all — still shows something.
    `<span class="vp-tl-dot" style="left:${_pct(dot)}"></span>` +
    `<span class="vp-tl-lane-label">${esc(_laneLabel(lane))}</span>` +
    `</div>`
  );
}

/** Render every lane. Empty string when there is nothing to show. */
export function lanesHtml(model) {
  if (!model.lanes.length) return '';
  return model.lanes.map((lane) => _laneHtml(lane, model.duration)).join('');
}
