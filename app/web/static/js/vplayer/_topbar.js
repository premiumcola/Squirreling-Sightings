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
import { overflowTriggerHtml } from './_overflow-menu.js';

const _CLOSE =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" aria-hidden="true">' +
  '<path d="M6 6l12 12M18 6L6 18"/></svg>';

/**
 * PURE: the title the bar shows for this config. Camera name when there
 * is one, then the item's own label, then a mode fallback — never an
 * empty bar and never the literal "undefined".
 */
export function titleFor(cfg) {
  const item = cfg.item || {};
  const name = item.camera_name || item.cam_name || '';
  if (name) return String(name);
  if (item.label) return String(item.label);
  return cfg.flags.live ? 'Live' : 'Aufnahme';
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
