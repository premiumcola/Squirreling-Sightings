// ─── netz/_key.js ──────────────────────────────────────────────────────────
// The key to one camera's SETTINGS net: the group colours plus what the
// solid line, the dashed line and the ringed dot mean on the chart. Named
// for the `.netz-key` row it renders — `.netz-legend` is the confidence
// radar's own key next door (netz/_radar.js) and is a different thing.
//
// It has moved twice, and both moves were the same complaint. It started
// as a multi-line block repeated byte-for-byte inside EVERY panel, so it
// was hoisted to one page-level render under the section header — which
// parked it above the FIRST camera tile, nowhere near any net: "die
// Legende steht ganz oben über der ersten Videokachel, dort ergibt sie
// keinen Sinn". So it is per panel again, but as ONE compact wrapping row
// pinned to the BOTTOM of the panel, directly under the net it explains.
//
// One row, not a block: the panel's height is the neighbouring Live-Feed
// tile's height (32-netz.css), so every px this row takes is a px the net
// loses. netz/_panel.js measures the chart box with this row already laid
// out (see netProbeHtml in _cards.js), so the radar is drawn for the space
// that is actually left rather than for the space before the legend
// existed.

import { esc } from '../core/dom.js';
import { TUNE_GROUPS } from './_settings_axes.js';

// A short line/dot glyph for each of the three shape meanings on the
// chart — "was ist die gestrichelte Linie, was die feste?" gets answered
// under the chart itself instead of only once in chat.
function _lineSwatch(dashed) {
  const stroke = dashed ? '#ffffff' : 'rgba(120,200,255,.85)';
  const dash = dashed ? ' stroke-dasharray="3 3" stroke-opacity=".65"' : '';
  return (
    `<svg width="18" height="10" viewBox="0 0 18 10" aria-hidden="true">` +
    `<line x1="1" y1="5" x2="17" y2="5" stroke="${stroke}" stroke-width="2"${dash}/></svg>`
  );
}

function _dotSwatch() {
  return (
    `<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">` +
    `<circle cx="7" cy="7" r="4.5" fill="#7ac8ff" stroke="rgba(255,255,255,.85)" ` +
    `stroke-width="1.5"/></svg>`
  );
}

function _item(swatch, text) {
  return `<span class="netz-key-i">${swatch}${esc(text)}</span>`;
}

/** The whole key as one wrapping row: the five group colours, then the
 *  three line/dot meanings. */
export function netKeyHtml() {
  return (
    `<div class="netz-key" aria-label="Zeichenerklärung">` +
    Object.values(TUNE_GROUPS)
      .map((g) => _item(`<i style="background:${esc(g.color)}"></i>`, g.label))
      .join('') +
    _item(_lineSwatch(false), 'Aktuelles Profil') +
    _item(_lineSwatch(true), 'Werkseinstellung') +
    _item(_dotSwatch(), 'Geändert') +
    `</div>`
  );
}
