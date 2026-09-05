// ─── vplayer/timeline/_markers.js ──────────────────────────────────────────
// The beads on the rail: one per event, one per roll boundary.
//
// „zeichne die Ereignisse und die Vorläufe in der Timeline des Play
// Elements als Knödel ein, die man auch anwählen kann, wo dann 'n
// kleines Hover over kommt, was anzeigt, was das ist."
//
// So each is a real <button>: it seeks, it takes focus, and it carries
// its own sentence. Focus and not only hover, because a phone has no
// hover — a tap therefore both seeks AND shows the tip, which is the
// only way this is reachable on the device the operator actually uses.
//
// The MODEL half is pure and testable; the render half turns it into
// markup and nothing else. Positions come from _model.js's `pctOf`, so
// a bead and the lane bar it belongs to cannot drift apart.

import { esc } from '../../core/dom.js';
import { subjectLabel } from '../../core/clip-species.js';
import { liveTrackColor } from '../../core/track-color.js';
import { spanLabel } from '../_helpers.js';
import { pctOf } from './_model.js';

const _pct = (v) => `${(v * 100).toFixed(3)}%`;

/** German decimal comma; whole numbers keep no decimal at all. */
function _secs(v) {
  const n = Math.round(v * 10) / 10;
  return `${Number.isInteger(n) ? n : String(n).replace('.', ',')} s`;
}

/**
 * PURE: every bead this clip deserves, left to right.
 *
 * Roll beads sit on the BOUNDARY rather than in the middle of their
 * band: the interesting instant is where the pre-roll ends, because that
 * is the frame the camera actually triggered on. A band's own hatching
 * already shows its extent.
 *
 * Suppressed entirely when the model could not reconcile the rolls —
 * see reconcileRolls. A bead is a claim about a moment, and there is no
 * honest moment to put it on when the numbers do not fit the clip.
 *
 * @param {object} model  the timeline model
 * @returns {Array<{id, kind, t, label, tip, colour}>}
 */
export function buildMarkers(model) {
  const d = model.duration;
  if (!(d > 0)) return [];
  const out = [];

  if (model.preRoll > 0) {
    out.push({
      id: 'roll-pre',
      kind: 'pre',
      t: model.preRoll,
      label: 'Vorlauf',
      tip: `Ende des Vorlaufs · ${_secs(model.preRoll)} vor dem Auslöser aufgezeichnet`,
      colour: null,
    });
  }

  for (const lane of model.lanes) {
    const name = subjectLabel(lane.label, lane.species) || 'Objekt';
    const num = lane.trackNum == null ? '' : `#${lane.trackNum} `;
    out.push({
      id: `lane-${lane.trackNum == null ? name : lane.trackNum}-${lane.dotT.toFixed(3)}`,
      kind: 'event',
      t: lane.dotT,
      label: `${num}${name}`,
      tip: `${num}${name} · erkannt ${spanLabel(lane.barT0, lane.barT1)}`,
      colour: lane.colour || liveTrackColor(lane.trackNum),
    });
  }

  if (model.postRoll > 0) {
    out.push({
      id: 'roll-post',
      kind: 'post',
      t: model.postRollT0,
      label: 'Nachlauf',
      tip: `Beginn des Nachlaufs · ${_secs(model.postRoll)} nach dem Ereignis aufgezeichnet`,
      colour: null,
    });
  }

  out.sort((a, b) => a.t - b.t);
  return out;
}

/**
 * PURE: which side the tip opens to, so it never leaves the player.
 *
 * A tip centred on a bead at 2 % of the rail hangs off the left edge,
 * where the stage's overflow eats it. Returned as a value so the rule is
 * a unit test rather than something to be discovered on a phone.
 */
export function tipSide(frac) {
  if (frac < 0.2) return 'start';
  if (frac > 0.8) return 'end';
  return 'center';
}

/**
 * Make the beads live: a click seeks to the moment, and shows the tip.
 *
 * The tip is CSS on hover and on focus, which covers a mouse and a
 * keyboard. A touch has neither, so a tap adds the class explicitly and
 * the previous one loses it — otherwise the one control a phone user can
 * reach would be the one that never explains itself.
 *
 * Seeking pauses first, the same rule the drag follows: „wenn ich wo hin
 * ziehe soll es ja auch erst mal pausieren".
 *
 * @param {HTMLElement} root  the timeline host
 * @param {object} deps       { onSeek, onPause }
 */
export function wireBeads(root, deps = {}) {
  if (!root) return null;
  const onClick = (ev) => {
    const bead = ev.target?.closest?.('.vp-tl-bead');
    if (!bead || !root.contains(bead)) return;
    ev.preventDefault();
    const t = Number(bead.dataset.t);
    for (const el of root.querySelectorAll('.vp-tl-bead.is-tipped')) {
      if (el !== bead) el.classList.remove('is-tipped');
    }
    bead.classList.add('is-tipped');
    if (!Number.isFinite(t)) return;
    deps.onPause?.();
    deps.onSeek?.(t);
  };
  root.addEventListener('click', onClick);
  return { teardown: () => root.removeEventListener('click', onClick) };
}

/** Render the beads. Empty string when there are none. */
export function markersHtml(model) {
  const marks = buildMarkers(model);
  if (!marks.length) return '';
  const d = model.duration;
  const items = marks
    .map((m) => {
      const frac = pctOf(m.t, d);
      // ONE style attribute. The position rides on the element because a
      // bead can sit anywhere; it is expressed in the same percentage of
      // the same box the playhead uses, so the two share a coordinate
      // space and a bead cannot drift off the moment it marks.
      const colour = m.colour ? `--vp-bead-colour:${esc(m.colour)};` : '';
      return (
        `<button type="button" class="vp-tl-bead" data-kind="${esc(m.kind)}" ` +
        `data-t="${m.t.toFixed(3)}" data-tip-side="${tipSide(frac)}" ` +
        `aria-label="${esc(m.tip)}" style="${colour}left:${_pct(frac)}">` +
        `<span class="vp-tl-bead-tip" aria-hidden="true">${esc(m.tip)}</span>` +
        `</button>`
      );
    })
    .join('');
  return `<div class="vp-tl-beads">${items}</div>`;
}
