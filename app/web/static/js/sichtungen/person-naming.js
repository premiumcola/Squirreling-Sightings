// ─── sichtungen/person-naming.js ───────────────────────────────────────────
// „kannst du fotos der personen aus allen videos extrahieren damit ich die
// dann auf individuen branden kann? ... die genehmigung habe ich!"
//
// One portrait at a time, a row of names, next. The crops themselves are
// cut out of the CLIPS by app/app/person_crops.py — read that module's
// header for why the pre-existing register-from-snapshot path could not
// do this (the snapshot and the rectangle live in different pixel
// spaces, so it answered „Crop leer" for nearly every clip event).
//
// SHAPE BORROWED, NOT INVENTED. Two existing surfaces already settled the
// questions this one would otherwise re-litigate:
//   * the species picker (mediaview/panels/species-picker.js) — a sheet
//     appended to document.body so it works with or without a player
//     open, a module-level singleton so a second open replaces rather
//     than stacks, and a pure submit split out from the click.
//   * the dossier clips gallery (sichtungen/_clips-gallery.js) — its
//     header records that a grid of small cards was tried and rejected
//     for a "look at one, act on it, move on" column. Naming faces is
//     exactly that shape.
//
// A NAME IS CREATED BY USING IT. The registry has no "create person"
// call: `IdentityRegistry.register_crop` makes the profile on the first
// crop filed under a name. So the UI offers the known names as chips and
// a free-text field, and nothing else.
import { esc } from '../core/dom.js';
import { apiGet, apiPost } from '../core/api.js';
import { showToast } from '../core/toast.js';

let _sheet = null;
let _items = [];
let _at = 0;
let _names = [];

/** PURE: what the counter under the portrait says. */
export function namingCounter(at, total) {
  if (!total) return '';
  return `${Math.min(at + 1, total)} / ${total}`;
}

/** PURE: the name list to offer, newest-used first and without blanks.
 *  `profiles` is what GET /api/persons returns. */
export function nameChoices(profiles) {
  const seen = new Set();
  const out = [];
  for (const p of profiles || []) {
    const n = (p && p.name ? String(p.name) : '').trim();
    if (!n || seen.has(n)) continue;
    seen.add(n);
    out.push(n);
  }
  return out;
}

function _shellHtml() {
  return (
    `<div class="pn-card panel">` +
    `<button type="button" class="pn-close" title="Schließen" aria-label="Schließen">` +
    `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ` +
    `stroke-width="2.2" stroke-linecap="round" aria-hidden="true">` +
    `<path d="M6 6l12 12M18 6L6 18"/></svg></button>` +
    `<div class="pn-body"></div>` +
    `</div>`
  );
}

function _emptyHtml(msg) {
  return `<div class="pn-empty">${esc(msg)}</div>`;
}

function _bodyHtml() {
  const total = _items.length;
  if (!total) {
    return _emptyHtml(
      'Keine unbenannten Personen-Ausschnitte. Der Nachlauf holt sie aus den Aufnahmen — ' +
        'starte ihn über „Ausschnitte suchen".',
    );
  }
  const it = _items[Math.min(_at, total - 1)];
  const when = String(it.time || '')
    .replace('T', ' ')
    .slice(0, 16);
  return (
    `<div class="pn-stage">` +
    `<img class="pn-shot" src="${esc(it.url)}" alt="Personen-Ausschnitt" loading="lazy">` +
    `<span class="pn-count">${esc(namingCounter(_at, total))}</span>` +
    `</div>` +
    `<div class="pn-meta">${esc(when)}</div>` +
    `<div class="pn-names">` +
    _names
      .map((n) => `<button type="button" class="pn-name" data-name="${esc(n)}">${esc(n)}</button>`)
      .join('') +
    `</div>` +
    `<form class="pn-new"><input type="text" class="pn-input" placeholder="Neue Person…" ` +
    `aria-label="Neue Person" autocomplete="off">` +
    `<button type="submit" class="pn-add">Zuordnen</button></form>` +
    `<div class="pn-nav">` +
    `<button type="button" class="pn-skip">Überspringen</button>` +
    `</div>`
  );
}

function _paint() {
  const body = _sheet?.querySelector('.pn-body');
  if (!body) return;
  body.innerHTML = _bodyHtml();
  body
    .querySelectorAll('.pn-name')
    .forEach((b) => b.addEventListener('click', () => _assign(b.dataset.name)));
  body.querySelector('.pn-skip')?.addEventListener('click', () => {
    _at += 1;
    if (_at >= _items.length) _at = _items.length;
    _paint();
  });
  const form = body.querySelector('.pn-new');
  form?.addEventListener('submit', (e) => {
    e.preventDefault();
    const input = form.querySelector('.pn-input');
    const name = (input?.value || '').trim();
    if (name) _assign(name);
  });
}

/** PURE-ish: the payload for one assignment. Split out so the network
 *  step is testable without a click. */
export function assignPayload(item, name) {
  return {
    relpath: item?.relpath || '',
    name: String(name || '').trim(),
    cam_id: item?.cam_id || '',
    event_id: item?.event_id || '',
  };
}

async function _assign(name) {
  const it = _items[_at];
  if (!it || !name) return;
  try {
    const res = await apiPost('/api/person-crops/assign', assignPayload(it, name));
    if (!res?.ok) throw new Error(res?.error || 'abgelehnt');
    _names = nameChoices(res.profiles);
    // Every crop of the SAME clip is the same person — naming one names
    // them all, so they do not come back one by one.
    _items = _items.filter((x) => x.event_id !== it.event_id);
    if (_at >= _items.length) _at = Math.max(0, _items.length - 1);
    showToast(`Als „${name}" gemerkt`, 'success');
    _paint();
  } catch (e) {
    showToast('Zuordnen fehlgeschlagen: ' + (e?.message || ''), 'error');
  }
}

export function closePersonNaming() {
  _sheet?.remove();
  _sheet = null;
}

/** Open the naming sheet, loading the unnamed crops and the known names. */
export async function openPersonNaming() {
  closePersonNaming();
  _sheet = document.createElement('div');
  _sheet.className = 'modal pn-modal';
  _sheet.setAttribute('role', 'dialog');
  _sheet.setAttribute('aria-modal', 'true');
  _sheet.setAttribute('aria-label', 'Personen benennen');
  _sheet.innerHTML = _shellHtml();
  document.body.appendChild(_sheet);
  _sheet.querySelector('.pn-close')?.addEventListener('click', closePersonNaming);
  _sheet.addEventListener('click', (e) => {
    if (e.target === _sheet) closePersonNaming();
  });
  const onKey = (e) => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    document.removeEventListener('keydown', onKey, true);
    closePersonNaming();
  };
  document.addEventListener('keydown', onKey, true);

  const body = _sheet.querySelector('.pn-body');
  if (body) body.innerHTML = _emptyHtml('Lade Ausschnitte…');
  try {
    const [crops, persons] = await Promise.all([
      apiGet('/api/person-crops?only_unnamed=1&limit=200'),
      apiGet('/api/persons'),
    ]);
    _items = (crops && crops.items) || [];
    _names = nameChoices(persons && persons.profiles);
    _at = 0;
  } catch {
    _items = [];
    _names = [];
  }
  _paint();
}

/** Kick off the background sweep that cuts crops out of the archive. */
export async function startPersonCropSweep() {
  try {
    const res = await apiPost('/api/person-crops/sweep', {});
    showToast(
      res?.ok
        ? 'Suche läuft — die Ausschnitte erscheinen nach und nach.'
        : 'Ein Lauf ist bereits unterwegs.',
      res?.ok ? 'success' : 'error',
    );
  } catch (e) {
    showToast('Suche konnte nicht starten: ' + (e?.message || ''), 'error');
  }
}

window.openPersonNaming = openPersonNaming;
window.startPersonCropSweep = startPersonCropSweep;
