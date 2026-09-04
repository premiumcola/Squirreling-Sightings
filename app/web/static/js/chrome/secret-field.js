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

// Dots, not prose. A stored secret should LOOK like a masked password —
// „ich will da einfach diese Punkte haben, diese Anonymisierungspunkte" —
// and a sentence in the box reads as a value that is somehow already
// there. The rule the sentence used to state is unchanged and now lives
// in the field's tooltip, where it is available without occupying the
// one place the eye is supposed to fill.
const PLACEHOLDER_STORED = '••••••••••';
const TITLE_STORED = 'Gespeichert · leer lassen = unverändert · Auge öffnen zeigt es an';
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
  if (isSet) input.title = TITLE_STORED;
  else input.removeAttribute('title');
  const btn = _clearBtnFor(input);
  if (btn) {
    btn.hidden = !isSet;
    // A fresh hydrate disarms any half-pressed delete from the last open.
    delete btn.dataset.armed;
    btn.textContent = btn.dataset.label || btn.textContent;
  }
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

// TWO PRESSES, not one. This button sits beside the eye, and a stored
// password is not recoverable from the browser — „sonst drücken wir aus,
// ist das Passwort weg. Das macht keinen Sinn." The first press arms it
// and says so; the second does it. Anything else the operator touches
// disarms it again, so an armed button cannot survive to ambush a later
// click.
registerAction('clearSecretField', (el) => {
  const input = el.dataset.field
    ? el.closest('form')?.elements[el.dataset.field] || byId(el.dataset.field)
    : el.closest('.pw-wrap, .field-wrap')?.querySelector('input');
  if (!input) return;
  if (el.dataset.armed !== '1') {
    el.dataset.armed = '1';
    if (!el.dataset.label) el.dataset.label = el.textContent;
    el.textContent = 'Wirklich?';
    el.classList.add('pw-clear--armed');
    return;
  }
  delete el.dataset.armed;
  el.textContent = el.dataset.label || el.textContent;
  el.classList.remove('pw-clear--armed');
  input.value = '';
  input.dataset.cleared = '1';
  input.placeholder = PLACEHOLDER_CLEARED;
  input.classList.add('pw-input--cleared');
});

/** Disarm every half-pressed delete as soon as attention moves. */
function _disarmClears(except) {
  for (const btn of document.querySelectorAll('[data-action="clearSecretField"][data-armed="1"]')) {
    if (btn === except) continue;
    delete btn.dataset.armed;
    btn.textContent = btn.dataset.label || btn.textContent;
    btn.classList.remove('pw-clear--armed');
  }
}
document.addEventListener('pointerdown', (ev) => {
  _disarmClears(ev.target?.closest?.('[data-action="clearSecretField"]'));
});

// Typing anything undoes a pending clear — the operator changed their
// mind and is replacing the secret instead of removing it.
document.addEventListener('input', (ev) => {
  const el = ev.target;
  if (!el || el.type !== 'password' || el.dataset.cleared !== '1') return;
  delete el.dataset.cleared;
  el.classList.remove('pw-input--cleared');
});
