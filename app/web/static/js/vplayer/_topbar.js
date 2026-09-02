// ─── vplayer/_topbar.js ────────────────────────────────────────────────────
// prev · title · next, then the overflow trigger and close.
//
// The chevrons and the close are 36 px of PAINT carrying a 44 px
// TOUCH TARGET, via a transparent ::before in 36a. Painting them at
// 44 px would put four heavy discs across the top of a 375 px screen;
// shrinking the target to the paint is the iOS failure this project
// keeps re-fixing. The row also carries safe-area-inset-top, because
// it is the first thing under the notch.
//
// Navigation buttons render only when the caller supplied a handler.
// A permanently disabled chevron on a phone is a 44 px slot spent
// saying "no".

import { esc } from '../core/dom.js';
import { overflowTriggerHtml } from './_overflow-menu.js';

const _CHEVRON_LEFT =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M15 5l-7 7 7 7"/></svg>';
const _CHEVRON_RIGHT =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M9 5l7 7-7 7"/></svg>';
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

function _navHtml(cfg) {
  const { onPrev, onNext } = cfg.actions;
  const canNav = cfg.flags.canNavigate;
  const prev =
    canNav && onPrev
      ? `<button type="button" class="vp-top-btn vp-top-prev" aria-label="Vorherige Aufnahme">${_CHEVRON_LEFT}</button>`
      : '';
  const next =
    canNav && onNext
      ? `<button type="button" class="vp-top-btn vp-top-next" aria-label="Nächste Aufnahme">${_CHEVRON_RIGHT}</button>`
      : '';
  return { prev, next };
}

/**
 * Mount the top bar.
 *
 * @param {HTMLElement} host  the shell's [data-slot="topbar"]
 * @param {object} cfg        normalised config from _config.js
 * @param {object} handlers   { onClose, onPrev, onNext, onMore }
 * @returns {{trigger: HTMLElement|null, setTitle: (t: string) => void,
 *   teardown: () => void}|null}
 */
export function mountTopbar(host, cfg, handlers = {}) {
  if (!host) return null;
  const { prev, next } = _navHtml(cfg);
  host.innerHTML =
    prev +
    `<span class="vp-top-title">${esc(titleFor(cfg))}</span>` +
    next +
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
  wire('.vp-top-prev', handlers.onPrev);
  wire('.vp-top-next', handlers.onNext);
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
