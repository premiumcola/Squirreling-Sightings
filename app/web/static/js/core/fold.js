// ─── core/fold.js ──────────────────────────────────────────────────────────
// One collapsible section, with PER-KEY persistence.
//
// The per-key part is the whole reason this exists. The fold this was
// extracted from hardcoded a single storage key, which was correct
// while there was one fold. The player needs three independent ones
// (Aufnahme-Details, Rohe Erkennungen, Debug-Log), and three
// hand-rolled copies of a single-key fold would give all three ONE
// shared open state: opening the debug log would open the other two.
//
// THE THREE-STATE RULE lives here too, moved rather than reimplemented
// so there is exactly one answer to "should this fold start open".
//
// The class prefix is a parameter so each surface keeps its own CSS
// family — this is a behaviour helper, not a style opinion.

import { TIER_FULL } from '../mediaview/device-tier.js';

const _CHEVRON_SVG =
  '<svg viewBox="0 0 12 12" width="12" height="12" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M3 4.5l3 3 3-3"/></svg>';

/**
 * Pure decision — split from the storage read so the RULE is testable
 * without a localStorage mock, mirroring device-tier.js's
 * resolveDeviceTier / getDeviceTier split.
 *
 * Three-state storage read: '1' = explicitly open, '0' = explicitly
 * closed — either ALWAYS wins, regardless of tier, because an
 * operator's past choice must keep winning on both. Only a key that was
 * never touched (raw === null) falls back: on the 'full' tier (a
 * permanently-visible desktop with room to spare) a fold defaults open;
 * otherwise the caller's per-mode default stands.
 *
 * @param {string|null} raw        localStorage.getItem(key)
 * @param {boolean} defaultOpen    caller's per-mode fallback
 * @param {string} [tier]          'full' | 'compact' | undefined
 * @returns {boolean}
 */
export function resolveFoldOpen(raw, defaultOpen, tier) {
  if (raw === '1') return true;
  if (raw === '0') return false;
  if (tier === TIER_FULL) return true;
  return !!defaultOpen;
}

/** Read one fold's persisted state. Never throws — private mode does. */
export function isFoldOpen(key, defaultOpen, tier) {
  try {
    return resolveFoldOpen(localStorage.getItem(key), defaultOpen, tier);
  } catch {
    return !!defaultOpen;
  }
}

/**
 * Persist one fold's state. Writes an explicit '0' rather than removing
 * the key, so a user-closed fold stays closed even where the caller's
 * default (or the device tier) would otherwise reopen it.
 */
export function saveFoldOpen(key, open) {
  try {
    localStorage.setItem(key, open ? '1' : '0');
  } catch {
    /* quota / private mode — the fold still works for this session */
  }
}

/**
 * Render a fold's chrome into `host` and return handles to it.
 *
 * The caller owns the body's contents; this owns the header, the open
 * state and its persistence.
 *
 * @param {HTMLElement} host
 * @param {object} opts
 * @param {string} opts.key             storage key, unique per fold
 * @param {string} opts.title
 * @param {string} [opts.subtitle]      muted text beside the title
 * @param {string} [opts.icon]          inline SVG shown before the title
 * @param {boolean} [opts.defaultOpen]
 * @param {string} [opts.tier]
 * @param {string} [opts.prefix]        CSS class family
 * @param {string} [opts.mode]          value for data-mode on the root
 * @returns {{root, header, body, setTitle, isOpen, teardown}|null}
 */
export function renderFold(host, opts = {}) {
  if (!host) return null;
  const p = opts.prefix || 'ui-fold';
  const open0 = isFoldOpen(opts.key, opts.defaultOpen, opts.tier);
  host.innerHTML =
    `<div class="${p}-root" data-open="${open0 ? '1' : '0'}"` +
    `${opts.mode ? ` data-mode="${opts.mode}"` : ''}>` +
    `<button type="button" class="${p}-header" aria-expanded="${open0 ? 'true' : 'false'}">` +
    `<span class="${p}-chevron" aria-hidden="true">${_CHEVRON_SVG}</span>` +
    (opts.icon ? `<span class="${p}-icon" aria-hidden="true">${opts.icon}</span>` : '') +
    `<span class="${p}-title">${opts.title || ''}</span>` +
    (opts.subtitle ? `<span class="${p}-sub">${opts.subtitle}</span>` : '') +
    `</button>` +
    `<div class="${p}-body" ${open0 ? '' : 'hidden'}></div>` +
    `</div>`;

  const root = host.querySelector(`.${p}-root`);
  const header = host.querySelector(`.${p}-header`);
  const body = host.querySelector(`.${p}-body`);

  const onClick = () => {
    const willOpen = body.hidden;
    body.hidden = !willOpen;
    header.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    root.dataset.open = willOpen ? '1' : '0';
    saveFoldOpen(opts.key, willOpen);
    opts.onToggle?.(willOpen);
  };
  header?.addEventListener('click', onClick);

  return {
    root,
    header,
    body,
    isOpen: () => !body.hidden,
    setTitle: (text) => {
      const el = host.querySelector(`.${p}-title`);
      if (el) el.textContent = text;
    },
    teardown: () => header?.removeEventListener('click', onClick),
  };
}
