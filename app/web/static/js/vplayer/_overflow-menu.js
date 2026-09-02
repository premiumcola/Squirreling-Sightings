// ─── vplayer/_overflow-menu.js ─────────────────────────────────────────────
// The "…" menu in the top bar. Everything that is a real action but not
// frequent enough to earn a permanent 44 px slot on a 375 px screen.
//
// The item SET is a pure function of the config, which is the part
// worth testing: which actions a mode offers is a decision that has
// been got wrong before (a delete offered on a live view, a system-
// player switch offered for a photo), and it is far cheaper to pin as
// arithmetic than to rediscover in a browser.

import { esc } from '../core/dom.js';

/** Menu item ids. Exported so the caller's switch cannot drift. */
export const VP_MENU_NATIVE = 'native';
export const VP_MENU_DELETE = 'delete';
export const VP_MENU_RECORD = 'record';

const _DOTS_SVG =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">' +
  '<circle cx="12" cy="5" r="1.9"/><circle cx="12" cy="12" r="1.9"/>' +
  '<circle cx="12" cy="19" r="1.9"/></svg>';

/**
 * PURE: which items this player offers.
 *
 * @param {object} cfg  normalised config from _config.js
 * @param {object} [caps]
 * @param {boolean} [caps.nativeAvailable]  the browser can hand a video
 *   to its own player. Feature-detected by the caller, never UA-sniffed
 *   — a UA sniff is what made the detection overlay unreachable on iOS
 *   in the first place.
 * @returns {Array<{id: string, label: string, danger: boolean}>}
 */
export function buildOverflowItems(cfg, caps = {}) {
  const items = [];
  const flags = (cfg && cfg.flags) || {};
  const actions = (cfg && cfg.actions) || {};

  if (caps.nativeAvailable) {
    items.push({ id: VP_MENU_NATIVE, label: 'Im Systemplayer öffnen', danger: false });
  }
  if (flags.canRecordNow) {
    items.push({ id: VP_MENU_RECORD, label: 'Jetzt aufnehmen', danger: false });
  }
  // A delete needs BOTH the mode's permission and a handler to call.
  // Offering one without a handler is a dead menu row, and offering one
  // in live mode would be an action with no object to act on.
  if (flags.canDelete && typeof actions.onDelete === 'function') {
    items.push({ id: VP_MENU_DELETE, label: 'Aufnahme löschen', danger: true });
  }
  return items;
}

/** The trigger button's markup, so the top bar and the menu agree. */
export function overflowTriggerHtml() {
  return (
    `<button type="button" class="vp-top-btn vp-top-more" aria-haspopup="menu" ` +
    `aria-expanded="false" aria-label="Weitere Aktionen">${_DOTS_SVG}</button>`
  );
}

function _itemsHtml(items) {
  return items
    .map(
      (it) =>
        `<button type="button" role="menuitem" class="vp-menu-item` +
        `${it.danger ? ' vp-menu-item--danger' : ''}" data-item="${esc(it.id)}">` +
        `${esc(it.label)}</button>`,
    )
    .join('');
}

/**
 * Mount the menu next to its trigger.
 *
 * @param {HTMLElement} host     the top bar
 * @param {HTMLElement} trigger  the "…" button
 * @param {Array} items          from buildOverflowItems
 * @param {(id: string) => void} onPick
 * @returns {{close: () => void, teardown: () => void}|null}
 */
export function mountOverflowMenu(host, trigger, items, onPick) {
  if (!host || !trigger || !items.length) return null;

  const menu = document.createElement('div');
  menu.className = 'vp-menu';
  menu.setAttribute('role', 'menu');
  menu.hidden = true;
  menu.innerHTML = _itemsHtml(items);
  host.appendChild(menu);

  const close = () => {
    menu.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
  };
  const open = () => {
    menu.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
  };

  const onTrigger = (ev) => {
    ev.stopPropagation();
    if (menu.hidden) open();
    else close();
  };
  const onPick_ = (ev) => {
    const btn = ev.target.closest?.('[data-item]');
    if (!btn) return;
    ev.stopPropagation();
    close();
    onPick(btn.dataset.item);
  };
  // Any tap outside dismisses, which is the behaviour a menu on a phone
  // needs far more than a close button inside it.
  const onAway = () => close();

  trigger.addEventListener('click', onTrigger);
  menu.addEventListener('click', onPick_);
  document.addEventListener('click', onAway);

  return {
    close,
    teardown: () => {
      trigger.removeEventListener('click', onTrigger);
      menu.removeEventListener('click', onPick_);
      document.removeEventListener('click', onAway);
      menu.remove();
    },
  };
}
