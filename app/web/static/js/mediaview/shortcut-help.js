// ─── mediaview/shortcut-help.js ────────────────────────────────────────────
// Pure DOM builder for the '?' shortcut-help panel. Rendering only — the
// active-binding list (lightbox-bindings.js) and the open/close STATE +
// key-dispatch (keyboard.js) live elsewhere; this file never imports
// keyboard.js back, matching keyboard.js's own header note on avoiding
// import cycles between the two (it already avoids reaching into
// lightbox.js for the same reason).
//
// Desktop-only feature (gated by isShortcutHelpAvailable in
// lightbox-bindings.js before this is ever called) — a centred fixed
// panel, not a bottom sheet, since it never has to fit a phone viewport.
import { esc } from '../core/dom.js';

function _rowHtml(binding) {
  const keys = binding.keys
    .map((k) => `<kbd class="mv-shhelp-key">${esc(k)}</kbd>`)
    .join('<span class="mv-shhelp-or">/</span>');
  return (
    `<li class="mv-shhelp-row">` +
    `<span class="mv-shhelp-keys">${keys}</span>` +
    `<span class="mv-shhelp-label">${esc(binding.label)}</span>` +
    `</li>`
  );
}

/**
 * Mount the shortcut-help overlay into document.body.
 *
 * @param {Array<{keys: string[], label: string}>} bindings  Already
 *   filtered to the current context (getActiveLightboxBindings).
 * @param {Function} onRequestClose  Fired on backdrop click / × click.
 *   Escape is NOT handled here — keyboard.js's single document keydown
 *   listener owns that so the overlay can never eat a keystroke the
 *   operator needs to close it (see keyboard.js's `_help` gate).
 * @returns {{ el: HTMLElement, teardown(): void }}
 */
export function mountShortcutHelp(bindings, onRequestClose) {
  const root = document.createElement('div');
  root.className = 'mv-shhelp';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-label', 'Tastenkürzel');
  root.innerHTML =
    `<div class="mv-shhelp-backdrop" data-close="1"></div>` +
    `<div class="mv-shhelp-panel">` +
    `<div class="mv-shhelp-head">` +
    `<span class="mv-shhelp-title">Tastenkürzel</span>` +
    `<button type="button" class="mv-shhelp-x" data-close="1" aria-label="Schließen">✕</button>` +
    `</div>` +
    `<ul class="mv-shhelp-list">${bindings.map(_rowHtml).join('')}</ul>` +
    `</div>`;
  root.addEventListener('click', (e) => {
    if (e.target && e.target.closest && e.target.closest('[data-close="1"]')) {
      onRequestClose();
    }
  });
  document.body.appendChild(root);
  return {
    el: root,
    teardown: () => root.remove(),
  };
}
