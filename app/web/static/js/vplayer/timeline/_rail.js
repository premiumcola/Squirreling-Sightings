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

import { pctOf } from './_model.js';

const _pct = (v) => `${(v * 100).toFixed(3)}%`;

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
    `<div class="vp-tl-track">${bands}${marker}` +
    `<div class="vp-tl-fill"></div><div class="vp-tl-head"></div></div>` +
    // The drag surface. Transparent, full width, and tall enough to
    // meet the 44 px touch minimum around a 6 px rail — see 36b.
    `<div class="vp-tl-hit" role="slider" aria-label="Wiedergabeposition" tabindex="0"></div>`
  );
}

/**
 * Move the playhead. One property write; the fill, the head and any
 * future reader all follow it.
 */
export function setPlayhead(root, t, duration) {
  if (!root) return;
  root.style.setProperty('--vp-play-pct', pctOf(t, duration).toFixed(5));
}
