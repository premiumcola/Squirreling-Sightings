// ─── mediaview/title-bar.js ────────────────────────────────────────────────
// Top strip of the MediaView shell: prev/next chevrons, mode title
// (camera name + timestamp), close button. Config-driven and mode
// agnostic — H/I lift the recorded/live-specific action buttons
// (confirm-haken, download, delete) on top of this base.
//
// Nav buttons render disabled when the matching action handler is
// absent (e.g. live mode has no prev/next), so the same markup serves
// every mode without per-mode branching in the shell.

import { byId, esc } from '../core/dom.js';

const _CHEVRON_L =
  `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>`;
const _CHEVRON_R =
  `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>`;
const _CLOSE =
  `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>`;

function _titleFrom(config) {
  const item = (config && config.item) || {};
  const cam = item.camera_name || item.cam_name || item.camera_id || item.cam_id || '';
  const time = item.time_label || item.started_at || '';
  return { cam: String(cam), time: String(time) };
}

/**
 * Render the title bar into ``host``.
 *
 * @param {HTMLElement|string} host
 * @param {Object} config  openMediaView config (item + actions read).
 * @returns {{ el, setTitle(cam, time), teardown() }}
 */
export function renderTitleBar(host, config = {}) {
  const el = typeof host === 'string' ? byId(host) : host;
  if (!el) return null;
  const actions = config.actions || {};
  const hasPrev = typeof actions.onPrev === 'function';
  const hasNext = typeof actions.onNext === 'function';
  const { cam, time } = _titleFrom(config);
  el.className = 'mv-titlebar';
  el.innerHTML =
    `<button type="button" class="mv-tb-nav" data-nav="prev"${hasPrev ? '' : ' disabled'} aria-label="Vorheriges">${_CHEVRON_L}</button>` +
    `<div class="mv-tb-titles"><span class="mv-tb-cam">${esc(cam)}</span>` +
    `<span class="mv-tb-time">${esc(time)}</span></div>` +
    `<div class="mv-tb-actions">` +
    `<button type="button" class="mv-tb-nav" data-nav="next"${hasNext ? '' : ' disabled'} aria-label="Nächstes">${_CHEVRON_R}</button>` +
    `<button type="button" class="mv-tb-close" data-act="close" aria-label="Schließen">${_CLOSE}</button>` +
    `</div>`;
  const wire = (sel, fn) => {
    const b = el.querySelector(sel);
    if (b && typeof fn === 'function') b.addEventListener('click', fn);
  };
  wire('[data-nav="prev"]', actions.onPrev);
  wire('[data-nav="next"]', actions.onNext);
  wire('[data-act="close"]', actions.onClose);
  return {
    el,
    setTitle: (c, t) => {
      const camEl = el.querySelector('.mv-tb-cam');
      const timeEl = el.querySelector('.mv-tb-time');
      if (camEl) camEl.textContent = c || '';
      if (timeEl) timeEl.textContent = t || '';
    },
    teardown: () => {
      el.innerHTML = '';
    },
  };
}
