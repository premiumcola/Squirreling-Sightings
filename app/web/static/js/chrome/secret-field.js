// ─── chrome/secret-field.js ────────────────────────────────────────────────
// One implementation of the "stored secret" input contract, shared by
// the three password fields in the app: the cam-edit RTSP password, the
// Telegram bot token, and the MQTT broker password.
//
// The server never sends a secret back (routes/_secrets.py) — only a
// `<key>_set` boolean. So the input is ALWAYS empty on hydrate, which
// is what stops Chrome offering "Passwort speichern" on the XHR save,
// and the payload has to say which of three things the operator meant:
//
//   nothing typed, not cleared  → omit the key      → keep stored
//   Löschen clicked             → send ""           → clear stored
//   something typed             → send the value    → replace stored
//
// Before this module the middle row did not exist in any UI: both
// `if (typed) payload.x = typed` callsites could only ever keep or
// replace, so an operator who mistyped a bot token had no way to remove
// it short of editing settings.json on the host.
import { byId } from '../core/dom.js';
import { registerAction } from '../core/action-registry.js';

const PLACEHOLDER_STORED = 'Gespeichert · leer lassen = unverändert';
const PLACEHOLDER_CLEARED = 'Wird beim Speichern gelöscht';

function _clearBtnFor(input) {
  return input?.closest('.pw-wrap, .field-wrap')?.querySelector('[data-action="clearSecretField"]');
}

/** Put a secret input into its post-hydrate state: empty value, a
 *  placeholder that says whether something is stored, and a Löschen
 *  button that only exists when there is something to delete. */
export function hydrateSecretField(input, isSet, emptyPlaceholder) {
  if (!input) return;
  input.value = '';
  delete input.dataset.cleared;
  input.placeholder = isSet ? PLACEHOLDER_STORED : emptyPlaceholder || '';
  const btn = _clearBtnFor(input);
  if (btn) btn.hidden = !isSet;
}

/** `{ changed, value }` — `changed:false` means "omit the key". */
export function readSecretField(input) {
  if (!input) return { changed: false, value: '' };
  const typed = input.value || '';
  if (typed) return { changed: true, value: typed };
  if (input.dataset.cleared === '1') return { changed: true, value: '' };
  return { changed: false, value: '' };
}

/** Assign `target[key]` only when the operator actually asked for a
 *  change. Keeps every callsite down to a single line and makes the
 *  omit-means-unchanged rule impossible to forget. */
export function applySecretField(target, key, input) {
  const { changed, value } = readSecretField(input);
  if (changed) target[key] = value;
  return changed;
}

registerAction('clearSecretField', (el) => {
  const input = el.dataset.field
    ? el.closest('form')?.elements[el.dataset.field] || byId(el.dataset.field)
    : el.closest('.pw-wrap, .field-wrap')?.querySelector('input');
  if (!input) return;
  input.value = '';
  input.dataset.cleared = '1';
  input.placeholder = PLACEHOLDER_CLEARED;
  input.classList.add('pw-input--cleared');
});

// Typing anything undoes a pending clear — the operator changed their
// mind and is replacing the secret instead of removing it.
document.addEventListener('input', (ev) => {
  const el = ev.target;
  if (!el || el.type !== 'password' || el.dataset.cleared !== '1') return;
  delete el.dataset.cleared;
  el.classList.remove('pw-input--cleared');
});
