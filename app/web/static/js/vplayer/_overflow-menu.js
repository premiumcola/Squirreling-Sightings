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

// ── The item glyphs ───────────────────────────────────────────────────────
// „papierkorb mit gängigem logo irgendwo sinnvoll hin wo man nicht
// ausversehn drauf klickt und es hin passt."
//
// THE PLACE IS THIS MENU, and that is the half of the request that
// matters most. A delete here is a MOTION delete, and _delete-flow.js
// spells out what that means: the motion/photo branch has no arming step
// at all — it fires on the first tap and books correct=False into the
// feedback ledger on the way. A trash can sitting permanently on the
// picture beside prev/next would therefore be one stray finger away from
// destroying a recording, which is precisely what „wo man nicht
// ausversehn drauf klickt" asks to avoid. Behind the ⋮ it takes a
// deliberate open-then-choose, and it costs no screen space on a 375 px
// phone — „es hin passt".
//
// What WAS missing is the glyph. Three rows of German prose in a dark
// box said nothing at a glance; this project's design rule is „less
// text, more flat-design icons", and the delete in particular had no
// visual warning at all. The trash is drawn as the universal one — lid,
// body, two slots — rather than as an × or a bin-shaped invention,
// because a destructive action is the last place to be original.
const _TRASH_SVG =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" ' +
  'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M4 7h16"/>' +
  '<path d="M18.5 7l-.9 12.1A2 2 0 0 1 15.6 21H8.4a2 2 0 0 1-2-1.9L5.5 7"/>' +
  '<path d="M9.5 7V5a2 2 0 0 1 2-2h1a2 2 0 0 1 2 2v2"/>' +
  '<path d="M10 11v6M14 11v6"/></svg>';

const _EXPAND_SVG =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" ' +
  'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';

const _RECORD_SVG =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" ' +
  'stroke-width="1.8" aria-hidden="true">' +
  '<circle cx="12" cy="12" r="8"/>' +
  '<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/></svg>';

/**
 * PURE: which items this player offers.
 *
 * @param {object} cfg  normalised config from _config.js
 * @param {object} [caps]
 * @param {boolean} [caps.nativeAvailable]  the browser can hand a video
 *   to its own player. Feature-detected by the caller, never UA-sniffed
 *   — a UA sniff is what made the detection overlay unreachable on iOS
 *   in the first place.
 * @returns {Array<{id: string, label: string, danger: boolean,
 *   icon: string}>}
 */
export function buildOverflowItems(cfg, caps = {}) {
  const items = [];
  const flags = (cfg && cfg.flags) || {};
  const actions = (cfg && cfg.actions) || {};

  if (caps.nativeAvailable) {
    items.push({
      id: VP_MENU_NATIVE,
      label: 'Im Systemplayer öffnen',
      danger: false,
      icon: _EXPAND_SVG,
    });
  }
  if (flags.canRecordNow) {
    items.push({ id: VP_MENU_RECORD, label: 'Jetzt aufnehmen', danger: false, icon: _RECORD_SVG });
  }
  // A delete needs BOTH the mode's permission and a handler to call.
  // Offering one without a handler is a dead menu row, and offering one
  // in live mode would be an action with no object to act on.
  if (flags.canDelete && typeof actions.onDelete === 'function') {
    items.push({ id: VP_MENU_DELETE, label: 'Aufnahme löschen', danger: true, icon: _TRASH_SVG });
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
        // The glyph is decorative: the label beside it is the accessible
        // name, and a screen reader announcing "Bild Papierkorb" before
        // "Aufnahme löschen" would say the same thing twice.
        `<span class="vp-menu-icon" aria-hidden="true">${it.icon || ''}</span>` +
        `<span class="vp-menu-label">${esc(it.label)}</span></button>`,
    )
    .join('');
}

/**
 * Mount the menu next to its trigger.
 *
 * THE HOST IS THE SHELL ROOT, not the strip the trigger lives in. The
 * strip moved inside `.vp-stage`, and that element is `overflow: hidden`
 * — it has to be, the letterboxed picture and its layers depend on it —
 * so a dropdown anchored in there would be cut off at the bottom of the
 * picture on exactly the short screens it matters on. The root is
 * `position: fixed`, so 36a can pin the menu under the ⋮ from there.
 *
 * @param {HTMLElement} host     the shell root
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
