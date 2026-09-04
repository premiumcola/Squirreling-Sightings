// ─── chrome/password-toggle.js ─────────────────────────────────────────────
// Stage 10 of the legacy.js → ES modules refactor — single source of
// truth for the eye-glyph variants and the password-field reveal
// helpers used across the cam-edit form, the Telegram tab, and the
// global Settings panel. Inline onclicks (togglePwField,
// togglePwFieldById) keep their window bridges; camedit/rtsp.js
// imports _setEyeState directly.
import { byId } from '../core/dom.js';

// SVG (not emoji) so size + centring stay pixel-stable across browsers.
export const EYE_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
export const EYE_OFF_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a18.66 18.66 0 0 1 4.16-4.93"/><path d="M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a18.66 18.66 0 0 1-1.66 2.66"/><path d="M14.12 14.12a3 3 0 0 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;

/**
 * Paint the eye for the field's CURRENT state.
 *
 * The glyph describes what you are looking at, not what a click would
 * do. Revealed password → open eye. Masked password → struck-through
 * eye. It used to be the other way round (the "click me to hide"
 * convention), and the operator's verdict was unambiguous: „die Anzeige
 * mit durchgestrichen und nicht ist verwirrend — Augen auf, PW sichtbar;
 * Auge zu, dann Passwort nur Punkte."
 *
 * The accessible name still names the ACTION, because that is what a
 * button's name is for, and `aria-pressed` carries the state — so a
 * screen reader gets both halves without the two contradicting each
 * other the way icon-as-action and label-as-action did on screen.
 */
export function _setEyeState(btn, revealed) {
  if (!btn) return;
  btn.innerHTML = revealed ? EYE_SVG : EYE_OFF_SVG;
  btn.classList.toggle('revealed', revealed);
  btn.setAttribute('aria-pressed', revealed ? 'true' : 'false');
  btn.setAttribute('aria-label', revealed ? 'Passwort verbergen' : 'Passwort anzeigen');
}

/**
 * How to obtain a stored secret that the browser was never given.
 *
 * THIS IS THE WHOLE BUG. A camera's password is deliberately never sent
 * with `/api/cameras` — `routes/_secrets.py::redact_camera` swaps it for
 * a `password_set` boolean, because that collection is polled every few
 * seconds by every open dashboard and the secret would land in every
 * response body, every cache and Chrome's password manager. So the field
 * in the form is EMPTY, and flipping `input.type` on an empty field
 * reveals an empty field: „Auge offen, soll das Passwort anzeigen, zeigt
 * aber nix an. Das Passwort ist einfach nicht da." The eye was doing
 * exactly what it was written to do, and that was never enough.
 *
 * The fetch itself already exists (camedit/rtsp.js's `_fetchSecret`, on
 * POST /api/cameras/<id>/reveal-secret) and is used for the URL field's
 * eye. Rather than have this generic module import a camera concern — or,
 * worse, grow a second copy of that request — the owner installs its
 * resolver here at load. A surface with no resolver behaves exactly as
 * before.
 *
 * @param {(form: HTMLFormElement) => Promise<string>} fn
 */
let _secretResolver = null;
export function setSecretResolver(fn) {
  _secretResolver = typeof fn === 'function' ? fn : null;
}

/** Reveal one field, fetching the stored secret if the box is empty. */
async function _reveal(input, btn) {
  if (!input.value && _secretResolver) {
    const form = btn.closest('form');
    try {
      const secret = await _secretResolver(form);
      if (secret) {
        input.value = secret;
        // Remember EXACTLY what was fetched, so hiding again can tell a
        // look from an edit — see _hide.
        input.dataset.revealed = secret;
      }
    } catch {
      /* an unreachable box must still flip the field, not throw */
    }
  }
  input.type = 'text';
  _setEyeState(btn, true);
}

/**
 * Hide the field again — and put a merely-LOOKED-at secret back.
 *
 * chrome/secret-field.js's contract is that an untouched box means "keep
 * what is stored" and the key is omitted from the payload entirely.
 * Leaving a fetched secret sitting in the input would break that: the
 * next save would report it as typed and write the same password back
 * over itself, re-encoding URLs and touching settings.json for a change
 * nobody made. So a value that is still byte-for-byte what the reveal
 * fetched is cleared; a value the operator edited is theirs and stays.
 */
function _hide(input, btn) {
  if (input.dataset.revealed != null && input.value === input.dataset.revealed) {
    input.value = '';
  }
  delete input.dataset.revealed;
  input.type = 'password';
  _setEyeState(btn, false);
}

// data-action="togglePwField" (core/action-registry.js) — toggles the
// password input nearest to the eye button via form-element lookup.
window.togglePwField = function (btn, fieldName) {
  const f = btn.closest('form');
  const input = f?.elements[fieldName];
  if (!input) return;
  if (input.type === 'password') _reveal(input, btn);
  else _hide(input, btn);
};

window.togglePwFieldById = function (id) {
  const input = byId(id);
  if (!input) return;
  input.type = input.type === 'password' ? 'text' : 'password';
  const btn = input.parentElement?.querySelector('.pw-eye');
  _setEyeState(btn, input.type === 'text');
};

// Window bridge was kept while rtsp.js used the global lookup; now
// rtsp.js imports _setEyeState directly via ES modules so the bridge
// is no longer reached from any callsite — dropped at stage 32.
