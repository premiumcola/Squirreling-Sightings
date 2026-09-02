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
import { effectiveTuning } from './_state.js';

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

/** The ghost glyph, shared with the header switch (ghostToggleHtml in
 *  _cards.js) so the icon in the key and the icon on the button cannot
 *  drift apart — the key only means anything if it shows the same shape. */
export function ghostIconSvg(px) {
  return (
    `<svg viewBox="0 0 24 24" width="${px}" height="${px}" aria-hidden="true" fill="none" ` +
    `stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">` +
    `<path d="M12 3a7 7 0 0 0-7 7v11l2.5-2 2.5 2 2-2 2 2 2.5-2 2.5 2V10a7 7 0 0 0-7-7Z"/>` +
    `<path d="M9.5 10.5h.01M14.5 10.5h.01"/></svg>`
  );
}

/** What the ghost switch is currently doing — the STATE, not the lesson.
 *
 *  It used to carry the full definition ("Spur ohne Objekt — läuft nur
 *  noch in der Gnadenfrist weiter…") because the operator had asked twice
 *  what a ghost was and a tooltip on a phone is a sentence nobody sees.
 *  That sentence has now done its job: „Nehme die Erklärung raus, ich weiß
 *  es jetzt." An explanation earns its space until it is understood, and
 *  then it is just text. The definition survives where it belongs — on the
 *  header button's tooltip and aria-label, for whoever needs it next. */
export function ghostKeyText(camId) {
  const hidden = effectiveTuning(camId).track_filter_ghosts !== false;
  return hidden ? 'Ghost aus' : 'Ghost an';
}

function _item(swatch, text) {
  return `<span class="netz-key-i">${swatch}${esc(text)}</span>`;
}

/** The whole key as one wrapping row of chips: the five group colours,
 *  the three line/dot meanings, and the ghost switch's current state.
 *
 *  Every entry is a chip now — no sentence on its own line. The row had
 *  grown to three lines under a chart whose height it takes directly from,
 *  and the verdict was "Legende verringern, das ist zu viel Text". Short
 *  labels: what a solid line and a dashed line mean is the kind of thing
 *  you learn once. */
export function netKeyHtml(camId) {
  return (
    `<div class="netz-key" aria-label="Zeichenerklärung">` +
    Object.values(TUNE_GROUPS)
      .map((g) => _item(`<i style="background:${esc(g.color)}"></i>`, g.label))
      .join('') +
    _item(_lineSwatch(false), 'Profil') +
    _item(_lineSwatch(true), 'Werk') +
    _item(_dotSwatch(), 'Geändert') +
    `<span class="netz-key-i netz-key-ghost">${ghostIconSvg(13)}` +
    `${esc(ghostKeyText(camId))}</span>` +
    `</div>`
  );
}
