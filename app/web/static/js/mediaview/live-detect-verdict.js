// ─── mediaview/live-detect-verdict.js ──────────────────────────────────────
// The verdict band: the ONE thing a diagnostic screen must say first.
//
// THE BUG THIS FIXES. Every failure message the poll loop produced went
// through live-detect-stall.js's `_banner()`, which hosted itself in
// `zoneEl('video') || #lightboxMediaWrap` — the legacy 5-zone modal. The
// unified player replaced that surface and builds its own DOM under
// `.vp-root`; it never touches those ids (vplayer/index.js says so in its
// header). So during a real outage the band was created, filled with the
// right German, and appended to a node that is not on screen. The panel
// just sat there looking idle. Measured on the screenshot harness: a
// forced 503 produced zero visible text in `.vp-root`.
//
// HOST RESOLUTION, in order:
//   1. the unified player's panel slot — where the operator is looking;
//   2. the legacy zone-video / #lightboxMediaWrap, which is still the
//      surface behind `?vplayer=off`.
// One implementation for both, rather than a second banner system: the
// duplicate is what let the two paths drift apart in the first place.
//
// PLACEMENT is `insertBefore(host.firstChild)`, and that is what gives the
// panel its hierarchy — the verdict on top, the chips and tracks under it,
// the raw folds last. `renderLiveTracks` assigns `host.innerHTML` once at
// mount and afterwards only writes into its own children, so a node
// prepended here survives every tick. It is re-created lazily on each
// paint, so a re-mounted panel gets it back on the next frame.

import { byId, esc, qs } from '../core/dom.js';
import { S } from './live-detect-state.js';
import { ZONE_IDS } from './live-detect-skeleton-consts.js';
import { classifyOutage, describeHealth } from './_live-detect-outage.js';

/** The band's own id. Stable, so a repaint finds the node it wrote. */
export const VERDICT_ID = 'mvSimVerdict';

/** Flat glyphs, one per tone — fewer words, per CLAUDE.md's design rules. */
const _ICONS = {
  ok: '<path d="M20 6L9 17l-5-5"/>',
  wait: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  warn: '<path d="M12 3l9 16H3z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
  bad: '<path d="M18.4 5.6a9 9 0 1 1-12.8 0"/><path d="M12 3v9"/>',
};

/**
 * Handlers the band's one button may fire, registered by the modules that
 * own the recovery. Registration rather than import because both owners
 * (the poll loop's mode fallback, the stall watchdog's retry) already
 * import each other; a third edge here would close the cycle.
 */
const _actions = new Map();

/**
 * Register the function behind one action id ('retry', 'mode-off').
 *
 * @param {string} id
 * @param {() => void} fn
 */
export function registerVerdictAction(id, fn) {
  if (typeof fn === 'function') _actions.set(id, fn);
}

/**
 * The surface the operator is actually looking at, or null.
 *
 * The legacy fallback is gated on the session NOT being headless. A
 * headless producer (live-detect-session.js) owns no chrome, and its own
 * header spells out why writing into #lightboxMediaWrap anyway is not
 * harmless: those nodes belong to the recorded player, which is still
 * mounted. No player panel and a headless session means nobody is looking
 * — say nothing rather than say it into someone else's furniture.
 */
function _host() {
  const panel =
    qs('.vp-root[data-mode="sim"] [data-slot="panel"]') ||
    qs('.vp-root[data-mode="live"] [data-slot="panel"]');
  if (panel) return panel;
  if (S.session?.headless) return null;
  return byId(ZONE_IDS.video) || byId('lightboxMediaWrap');
}

/**
 * PURE: one verdict → the band's inner markup.
 *
 * Exported so every string can be pinned under `node --test`, where there
 * is no DOM to read them back out of.
 *
 * @param {object} v a record from classifyOutage / describeHealth
 * @returns {string}
 */
export function verdictBandHtml(v) {
  const icon =
    `<svg class="vp-sv-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
    `${_ICONS[v.tone] || _ICONS.warn}</svg>`;
  const hint = v.hint ? `<div class="vp-sv-hint">${esc(v.hint)}</div>` : '';
  const btn = v.action
    ? `<button type="button" class="vp-sv-btn" data-vaction="${esc(v.action.id)}">` +
      `${esc(v.action.label)}</button>`
    : '';
  return (
    `${icon}<div class="vp-sv-body">` +
    `<div class="vp-sv-title">${esc(v.title)}</div>` +
    `<div class="vp-sv-detail">${esc(v.detail)}</div>` +
    `${hint}</div>${btn}`
  );
}

/** What is on screen right now, so a repaint can be skipped. */
let _shownId = null;

/** Find or create the band inside the current host. */
function _band(host) {
  let el = host.querySelector(`#${VERDICT_ID}`);
  if (el) return el;
  el = document.createElement('div');
  el.id = VERDICT_ID;
  el.className = 'vp-sv';
  el.setAttribute('role', 'status');
  // Politely, not assertively: the band repaints on a cadence and an
  // assertive live region would interrupt VoiceOver on every tick.
  el.setAttribute('aria-live', 'polite');
  host.insertBefore(el, host.firstChild);
  return el;
}

/**
 * Paint one verdict. Idempotent — the same verdict twice touches no DOM,
 * which matters because the hold loop asks four times a second.
 *
 * @param {object|null} v
 */
function _paint(v) {
  if (!v) return;
  const host = _host();
  if (!host) return;
  const el = _band(host);
  // The id alone is not enough: `contact` carries a counting seconds
  // figure and `running` a cadence, so the body decides.
  const html = verdictBandHtml(v);
  if (el.dataset.body === html && el.dataset.vid === v.id) return;
  el.dataset.body = html;
  el.dataset.vid = v.id;
  el.dataset.tone = v.tone;
  el.innerHTML = html;
  el.querySelector('[data-vaction]')?.addEventListener('click', _onAction);
  _shownId = v.id;
}

function _onAction(ev) {
  ev.stopPropagation();
  _actions.get(ev.currentTarget?.dataset?.vaction)?.();
}

/**
 * Show the verdict for one failure.
 *
 * @param {object} input see classifyOutage
 */
export function showOutage(input) {
  _paint(classifyOutage(input));
}

/**
 * Show the healthy (or CPU-fallback) verdict.
 *
 * @param {object} info see describeHealth
 */
export function showHealth(info) {
  _paint(describeHealth(info));
}

/**
 * Take one outage down.
 *
 * `only` guards the two watchdogs against each other: the CONTACT
 * watchdog clearing on recovery must not wipe a `busy` notice the poll
 * loop put up half a second ago, which is the exact way the old
 * `_hideStallBanner()` and `_showBusyNotice()` used to fight.
 *
 * @param {string} [only] clear only when this verdict is the one showing
 * @param {object} [health] what to fall back to; omitted leaves the band
 *   empty rather than claiming health nobody measured
 */
export function clearOutage(only, health) {
  if (only && _shownId !== only) return;
  if (health) {
    _paint(describeHealth(health));
    return;
  }
  _shownId = null;
  const el = _host()?.querySelector(`#${VERDICT_ID}`);
  el?.remove();
}

/** Drop the band and forget what was showing. Called on session teardown. */
export function teardownVerdict() {
  _shownId = null;
  _host()?.querySelector(`#${VERDICT_ID}`)?.remove();
}
