// ─── vplayer/_topbar.js ────────────────────────────────────────────────────
// The strip ON the top edge of the picture: camera glyph, title, then
// the speed button, the overflow trigger and close.
//
// IT IS NOT A ROW ANY MORE. „systemplayer oben weg … achte auf keinen
// sinnfreien platz fresserei!" — as the root's first child this bar was
// a full-width band of --vp-chrome that cost ~48 px of a 375 px screen
// to say five things, above a picture only 211 px tall. It now lives
// inside the stage and is absolutely positioned over the picture (36a),
// so it costs no layout at all and the ✕ sits exactly where it always
// did. Nothing was deleted to get there: the title, the camera glyph,
// the ⋮ and the ✕ are all still here.
//
// WHAT FADES AND WHAT DOES NOT. The glyph, the title and the strip's
// scrim are chrome over footage and go with the rest of it on the idle
// auto-hide — „wenn ich drüber hover einblenden, wenn ich weghover
// schnell wieder ausblenden, damit ich das Video ordentlich sehen kann".
// The ACTIONS stay: a ✕ you have to summon before you can press it is a
// close button the operator has to go looking for, and the speed button
// exists precisely to be pressed mid-playback („den will ich auch
// während dem videolauf anpassen können"), which is the one moment the
// chrome is faded out.
//
// PREV/NEXT ARE ON THE PICTURE TOO (_stage-chrome.js), at its sides —
// „das links, rechts vielleicht eher links, rechts am Video, oben ist
// son bisschen verwirrend in der Zettelleiste. Und die drei Punkte und
// das x, das passt da oben."
//
// The buttons are 36 px of PAINT carrying a 44 px TOUCH TARGET, via a
// transparent ::before in 36a. Painting them at 44 px would put heavy
// discs across the top of a 375 px screen; shrinking the target to the
// paint is the iOS failure this project keeps re-fixing. The strip also
// carries safe-area-inset-top, because it is the first thing under the
// notch.

import { esc } from '../core/dom.js';
import { getCameraIcon } from '../core/icons.js';
import { clockLabel } from '../core/clock-format.js';
import { overflowTriggerHtml } from './_overflow-menu.js';

const _CLOSE =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" aria-hidden="true">' +
  '<path d="M6 6l12 12M18 6L6 18"/></svg>';

/** German date + time for an event timestamp, or '' when there is none.
 *  Own formatter rather than mediathek/_cards.js's: importing that would
 *  pull the whole card builder — and its colour tables and icon sets —
 *  into the player shell for two `toLocaleString` calls. */
function _stamp(ts) {
  if (!ts) return '';
  const d = new Date(String(ts).replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return '';
  return (
    d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }) +
    ' · ' +
    d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })
  );
}

/**
 * PURE: the title the bar shows for this config.
 *
 * WHEN the clip is, not WHERE it is from — „Titel also date und time und
 * duration im titel davor reicht das logo der kamera als kamera-hinweis!
 * Der name muss nicht drüber also von der kamera!". The camera is
 * already named twice on the way in (the tile you tapped, the drilldown
 * you were in) and once more here, in the icon beside this text; what
 * the bar could not tell you before is which recording you are looking
 * at.
 *
 * Falls back through the item's own label to a mode word, so the bar is
 * never empty and never reads "undefined".
 */
export function titleFor(cfg) {
  const item = cfg.item || {};
  if (cfg.flags.live) return 'Live';
  const parts = [_stamp(item.time)];
  const dur = Number(item.duration_s);
  if (Number.isFinite(dur) && dur > 0) parts.push(clockLabel(dur));
  const text = parts.filter(Boolean).join(' · ');
  if (text) return text;
  return item.label ? String(item.label) : 'Aufnahme';
}

/** PURE: the camera glyph that replaces the camera NAME in the bar. */
export function cameraIconHtml(cfg) {
  const item = cfg.item || {};
  const name = item.camera_name || item.cam_name || '';
  return (
    `<span class="vp-top-cam" role="img" aria-label="${esc(name || 'Kamera')}">` +
    `${getCameraIcon(name)}</span>`
  );
}

/**
 * Mount the top strip.
 *
 * `hasMenu` is the caller's answer to "does the ⋮ have anything behind
 * it": the item set is a pure function of the config (_overflow-menu.js)
 * and mountOverflowMenu refuses to mount an empty one, so rendering the
 * trigger unconditionally is how a dead button ends up on the picture.
 *
 * @param {HTMLElement} host  the shell's [data-slot="topbar"]
 * @param {object} cfg        normalised config from _config.js
 * @param {object} handlers   { onClose, hasMenu }
 * @returns {{trigger: HTMLElement|null, speedHost: HTMLElement|null,
 *   teardown: () => void}|null}
 */
export function mountTopbar(host, cfg, handlers = {}) {
  if (!host) return null;
  host.innerHTML =
    cameraIconHtml(cfg) +
    `<span class="vp-top-title">${esc(titleFor(cfg))}</span>` +
    // An explicit spacer, NOT `margin-left: auto` on the action group.
    // That pairing — an auto margin against an inline-flex box — is the
    // one CLAUDE.md names as the recurring root cause of this project's
    // Live-Pill / Live-Chrome layout bugs on iOS. A flex child that eats
    // the slack cannot misbehave: it is the same push, expressed as
    // layout rather than as a margin.
    `<span class="vp-top-gap"></span>` +
    `<span class="vp-top-actions">` +
    // Filled by _speed.js, and left empty on a live surface — an empty
    // flex box with no padding occupies nothing, so nothing has to be
    // conditionally rendered around it.
    `<span class="vp-top-speed"></span>` +
    (handlers.hasMenu ? overflowTriggerHtml() : '') +
    `<button type="button" class="vp-top-btn vp-top-close" aria-label="Schließen">${_CLOSE}</button>` +
    `</span>`;

  const pick = (sel) => host.querySelector(sel);
  const wired = [];
  const wire = (sel, fn) => {
    const el = pick(sel);
    if (!el || typeof fn !== 'function') return;
    el.addEventListener('click', fn);
    wired.push([el, fn]);
  };
  wire('.vp-top-close', handlers.onClose);

  return {
    trigger: pick('.vp-top-more'),
    speedHost: pick('.vp-top-speed'),
    // No `setTitle`. It shipped with this module and nothing ever called
    // it: the title is a pure function of the config (titleFor) and a
    // config change opens a new player. A setter for a string that only
    // one mount can produce is a second way to write it, which is how
    // the two drift.
    teardown: () => {
      for (const [el, fn] of wired) el.removeEventListener('click', fn);
      host.innerHTML = '';
    },
  };
}
