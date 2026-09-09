// ─── vplayer/_topbar.js ────────────────────────────────────────────────────
// title, then the overflow trigger and close. That is all.
//
// PREV/NEXT MOVED TO THE PICTURE (_stage-chrome.js). Beside a camera
// name they read as menu items rather than as navigation — „das links,
// rechts vielleicht eher links, rechts am Video, oben ist son bisschen
// verwirrend in der Zettelleiste. Und die drei Punkte und das x, das
// passt da oben." At the picture's own edges there is no ambiguity, and
// the title row goes from five controls to two.
//
// The close is 36 px of PAINT carrying a 44 px TOUCH TARGET, via a
// transparent ::before in 36a. Painting it at 44 px would put heavy
// discs across the top of a 375 px screen; shrinking the target to the
// paint is the iOS failure this project keeps re-fixing. The row also
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
 * Mount the top bar.
 *
 * @param {HTMLElement} host  the shell's [data-slot="topbar"]
 * @param {object} cfg        normalised config from _config.js
 * @param {object} handlers   { onClose, onMore }
 * @returns {{trigger: HTMLElement|null, setTitle: (t: string) => void,
 *   teardown: () => void}|null}
 */
export function mountTopbar(host, cfg, handlers = {}) {
  if (!host) return null;
  host.innerHTML =
    cameraIconHtml(cfg) +
    `<span class="vp-top-title">${esc(titleFor(cfg))}</span>` +
    overflowTriggerHtml() +
    `<button type="button" class="vp-top-btn vp-top-close" aria-label="Schließen">${_CLOSE}</button>`;

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
    setTitle: (t) => {
      const el = pick('.vp-top-title');
      if (el) el.textContent = t;
    },
    teardown: () => {
      for (const [el, fn] of wired) el.removeEventListener('click', fn);
      host.innerHTML = '';
    },
  };
}
