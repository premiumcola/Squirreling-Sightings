// ─── mediaview/retrigger-button.js ─────────────────────────────────────────
// F4 · The ONE re-trigger button across MediaView modes. Replaces the
// recorded-mode "Neu indexieren" (tracking re-index) and the live-mode
// "Nach-Erkennung starten" with a single "Neu erkennen" pill — same
// label, same look everywhere; only the wired action differs per mode
// (the caller supplies onClick).
//
// The button itself is a neutral accent pill; the per-mode colour
// accent (gelb=live · grau=recorded · blau=weather) is owned by the
// surrounding chrome via its data-mode attribute, not re-declared here.

import { byId, esc } from '../core/dom.js';

// Circular-arrows glyph — the same "re-run" icon the legacy reindex
// button used, kept inline so the pill has no asset dependency.
const _ICON =
  `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" ` +
  `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
  `<path d="M2.5 8A5.5 5.5 0 0 1 13 5M13.5 8A5.5 5.5 0 0 1 3 11"/>` +
  `<polyline points="12,2 12,5.5 8.5,5.5"/><polyline points="4,14 4,10.5 7.5,10.5"/></svg>`;

/**
 * Mount the "Neu erkennen" re-trigger button.
 *
 * @param {HTMLElement|string} host
 * @param {Object} [opts]
 * @param {Function} [opts.onClick]  () => void
 * @param {string} [opts.label]  Override the visible label.
 * @param {string} [opts.title]  Override the tooltip / aria-label.
 * @param {boolean} [opts.busy]  Start in the disabled "running" state.
 * @returns {{ el, setBusy(on, runningLabel?), teardown() }}
 */
export function renderRetriggerButton(host, opts = {}) {
  const el = typeof host === 'string' ? byId(host) : host;
  if (!el) return null;
  const label = opts.label || 'Neu erkennen';
  const title = opts.title || 'Erkennung erneut ausführen';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'mv-retrigger';
  btn.title = title;
  btn.setAttribute('aria-label', title);
  btn.innerHTML = `${_ICON}<span class="mv-retrigger-label">${esc(label)}</span>`;
  btn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    if (btn.disabled) return;
    if (typeof opts.onClick === 'function') opts.onClick();
  });
  el.appendChild(btn);

  const setBusy = (on, runningLabel) => {
    btn.disabled = !!on;
    btn.dataset.busy = on ? '1' : '0';
    const lbl = btn.querySelector('.mv-retrigger-label');
    if (lbl) lbl.textContent = on ? runningLabel || 'Läuft…' : label;
  };
  if (opts.busy) setBusy(true);

  return {
    el: btn,
    setBusy,
    teardown: () => btn.remove(),
  };
}
