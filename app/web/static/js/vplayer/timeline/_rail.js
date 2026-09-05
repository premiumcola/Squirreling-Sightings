// ─── vplayer/timeline/_rail.js ─────────────────────────────────────────────
// The rail itself: the pre- and post-roll hatching, the white
// first-event marker and the playhead.
//
// EVERY POSITION COMES FROM _model.js. Nothing is computed here — this
// file turns fractions into percentages and nothing else. That split is
// what makes the geometry testable without a browser, and it is the
// thing the 709-line panel this replaces never had.
//
// The playhead moves through ONE CSS custom property, --vp-play-pct,
// set on the rail root. The fill width, the marker and the head all
// read that variable, so one write paints them in lockstep and they
// cannot drift apart mid-drag.

import { clockLabel, remainingLabel } from '../../core/clock-format.js';
import { markersHtml } from './_markers.js';
import { pctOf } from './_model.js';

const _pct = (v) => `${(v * 100).toFixed(3)}%`;

// German decimal comma, and no decimals at all on a whole number — a
// pre-roll reads "4 s", not "4.0 s".
function _secs(v) {
  const n = Math.round(v * 10) / 10;
  return `${Number.isInteger(n) ? n : String(n).replace('.', ',')} s`;
}

/**
 * The words under the rail. Without them the bands are three shades of
 * the same stripe and the operator's own verdict was "der Vorlauf ist
 * nicht ersichtlich" — the hatching was on screen and said nothing.
 *
 * Each caption appears only when it has something to report, so a clip
 * recorded before the pre-roll buffer existed shows no empty label. The
 * row is `aria-hidden`: the rail's own slider already carries the
 * position for a screen reader, and repeating it here would read the
 * same thing twice.
 */
export function railCaptionsHtml(model) {
  const parts = [];
  // The rolls did not fit the clip, so no band was drawn and the reason
  // takes the caption row instead. Saying nothing here is what produced
  // „es passt einfach alles nicht zusammen": the numbers were still in
  // the details fold, contradicting a rail that had quietly given up.
  if (model.rollsUnreliable) {
    return (
      `<div class="vp-tl-caps" aria-hidden="true">` +
      `<span class="vp-tl-cap vp-tl-cap--warn">` +
      `Vor- und Nachlauf passen nicht in diesen Clip — Aufnahme verkürzt</span></div>`
    );
  }
  if (model.preRoll > 0) {
    parts.push(`<span class="vp-tl-cap vp-tl-cap--pre">Vorlauf ${_secs(model.preRoll)}</span>`);
  }
  // POSITIONED AT THE MOMENT IT NAMES, not laid out as a flex item.
  //
  // „wieso erstes Ereignis an Schluss???" — because it was the second of
  // two items in a `justify-content: space-between` row, so with no
  // post-roll caption beside it the free space pushed it to the far
  // right. A caption carrying a ▼ points at something; this one pointed
  // at whatever the flexbox left under it, and only looked correct when
  // all three captions happened to be present.
  //
  // Still only shown WITH a pre-roll: without one the clip starts at the
  // event, and a label on the left edge says nothing that is not already
  // obvious.
  if (model.firstEventT != null && model.preRoll > 0) {
    const at = pctOf(model.firstEventT, model.duration);
    // „Vorlauf ist zeitlich NACH der Erkennung der Person???" — it can
    // be, and that is not a fault: the pre-roll is footage from before
    // the MOTION TRIGGER, and a subject already standing in frame is
    // legitimately detected inside it. Left unsaid it reads as a
    // contradiction, so the caption says it.
    const inside = model.firstEventT < model.preRoll;
    const text = inside ? '▼ erstes Ereignis · noch im Vorlauf' : '▼ erstes Ereignis';
    parts.push(
      `<span class="vp-tl-cap vp-tl-cap--first" style="left:${_pct(at)}">${text}</span>`,
    );
  }
  if (model.postRoll > 0) {
    parts.push(`<span class="vp-tl-cap vp-tl-cap--post">Nachlauf ${_secs(model.postRoll)}</span>`);
  }
  if (!parts.length) return '';
  return `<div class="vp-tl-caps" aria-hidden="true">${parts.join('')}</div>`;
}

/**
 * The clock, under the rail — elapsed on the left, −remaining on the
 * right. It lives HERE and not in the transport overlay because there is
 * only room for one of them: the overlay's own strip is centred on the
 * picture and printed straight through these captions, "Vorlauf 3 s"
 * over "0:00", at every width including desktop. One readout, in the
 * row that already owns the time axis.
 */
export function railClockHtml() {
  return (
    `<div class="vp-tl-clock mono" aria-hidden="true">` +
    `<span data-tl-elapsed>0:00</span><span data-tl-remain>−0:00</span></div>`
  );
}

/**
 * The playhead — which IS the play button.
 *
 * „Timeline button mit play in gross fehlt noch" and, before that, „der
 * play button in der abspiel timeline". One object, two jobs: it marks
 * where you are and it starts and stops you being there. A separate disc
 * floating over the middle of the picture said the same thing a second
 * time, in the one place that covers the subject.
 *
 * Both glyphs ship and CSS shows one, so a play/pause flip is a class on
 * an ancestor and never a re-render under the finger mid-drag.
 */
function _headHtml() {
  return (
    `<button type="button" class="vp-tl-head" aria-label="Abspielen oder anhalten">` +
    `<svg class="vp-tl-head-icon vp-tl-head-icon--play" viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">` +
    `<path fill="currentColor" d="M8 5v14l11-7z"/></svg>` +
    `<svg class="vp-tl-head-icon vp-tl-head-icon--pause" viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">` +
    `<path fill="currentColor" d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg>` +
    `</button>`
  );
}

/**
 * Render the rail's static furniture for a model. The playhead is NOT
 * included: it moves every frame and is written through the custom
 * property instead of being re-rendered.
 */
export function railHtml(model) {
  const d = model.duration;
  const pre = pctOf(model.preRoll, d);
  const postFrom = pctOf(model.postRollT0, d);
  const bands =
    (pre > 0 ? `<div class="vp-tl-band vp-tl-band--pre" style="width:${_pct(pre)}"></div>` : '') +
    (model.postRoll > 0
      ? `<div class="vp-tl-band vp-tl-band--post" style="left:${_pct(postFrom)};` +
        `width:${_pct(1 - postFrom)}"></div>`
      : '');
  // Suppressed at duration 0, where every position would collapse onto
  // the left edge and read as "the event began immediately".
  const marker =
    model.firstEventT != null
      ? `<div class="vp-tl-marker" style="left:${_pct(pctOf(model.firstEventT, d))}"` +
        ` title="Erste Erkennung"></div>`
      : '';
  return (
    railCaptionsHtml(model) +
    `<div class="vp-tl-track">${bands}${marker}` +
    `<div class="vp-tl-fill"></div>${markersHtml(model)}${_headHtml()}` +
    // The drag surface. Transparent, the rail's full width, and tall
    // enough to meet the 44 px touch minimum around a 6 px rail.
    //
    // INSIDE THE TRACK, which is the fix. It used to be a sibling —
    // absolutely positioned with `bottom: 0` inside `.vp-timeline`,
    // which is explicitly `position: static`. So its containing block
    // was some ancestor further up and the band was pinned to the bottom
    // of THAT, not centred on the rail: the one element whose whole job
    // is to make a hairline scrubber grabbable was not over the
    // scrubber. Only the 44 px disc actually answered a drag, which is
    // what „ich kann den Button nur extrem buggy hin- und herschieben"
    // describes. The track is `position: relative`, so in here the band
    // lands on the rail by construction — and on the SAME box
    // `attachScrub` measures the pointer against.
    `<div class="vp-tl-hit" role="slider" aria-label="Wiedergabeposition" tabindex="0"></div>` +
    `</div>` +
    railClockHtml()
  );
}

/**
 * Move the playhead. One property write; the fill, the head and any
 * future reader all follow it.
 */
export function setPlayhead(root, t, duration) {
  if (!root) return;
  root.style.setProperty('--vp-play-pct', pctOf(t, duration).toFixed(5));
  // Guarded writes: `tick` runs every animation frame, and re-assigning
  // identical text would still dirty the layout four times a second.
  const el = root.querySelector?.('[data-tl-elapsed]');
  const rem = root.querySelector?.('[data-tl-remain]');
  if (el) {
    const s = clockLabel(t);
    if (el.textContent !== s) el.textContent = s;
  }
  if (rem) {
    const s = remainingLabel(t, duration);
    if (rem.textContent !== s) rem.textContent = s;
  }
}
