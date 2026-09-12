// ─── identities/index.js ───────────────────────────────────────────────────
// Die Identitäten-Karte in den Einstellungen.
//
// „Die Zuordnung der Identitäten … sollte in dem Einstellungsmenü
// Identitäten stattfinden. Dort würde ich auch die Personen dann benennen
// und neue Gesichter vorhandenen Personen zuordnen. … Ich muss da bisschen
// an Google Fotos denken."
//
// Vorher standen hier zwei Namenslisten ohne Bild und ein Protokoll der
// Telegram-Menütipps („menu_root", „menu_wetter") — das Protokoll ist
// ersatzlos weg, es hat nie jemand gelesen und es schrieb bei jedem
// Tastendruck die settings.json neu.
//
// ERST BEIM AUFKLAPPEN. Die Gesichterliste geht das Ereignisarchiv durch;
// das gehört nicht in den loadAll(), der bei jedem Kamerawechsel läuft.
// Die Karte lädt, wenn sie geöffnet wird, und danach nur noch, wenn sich
// durch eine Zuordnung etwas geändert hat.
import { byId } from '../core/dom.js';
import { showToast, showConfirm } from '../core/toast.js';
import * as api from './_api.js';
import { personsHtml, catsHtml } from './_persons.js';
import {
  facesHtml,
  assignBarHtml,
  selectionItems,
  agreedSuggestion,
  confidentCount,
  knownRejectCount,
} from './_faces.js';

const MOUNT = 'identityPanel';
const SECTION = 'set-profiles';

let _data = { persons: [], cats: [], crops: {}, quality: {} };
let _faces = [];
let _loaded = false;
let _busy = false;
const _selected = new Set();

function _mount() {
  return byId(MOUNT);
}

function _names() {
  return _data.persons.map((p) => p.name).filter(Boolean);
}

function _topHtml() {
  const total = _data.quality?.checked ? _data.quality : null;
  const open = _data.crops?.unnamed || 0;
  const auto = _data.crops?.auto || 0;
  const ready = confidentCount(_faces);
  const rejected = _data.crops?.rejected || 0;
  const known = knownRejectCount(_faces);
  const stat = [`${_data.persons.length} benannt`, `${open} offen`];
  // Was die Maschine selbst zugeordnet hat, gehört sichtbar dazu — das
  // ist die Zahl, die man gelegentlich nachprüfen will.
  if (auto) stat.push(`${auto} automatisch`);
  // Und was ausdrücklich keine Person ist. Die zweite Zahl ist die
  // interessantere: so oft hat das Taggen von neulich gerade Arbeit
  // gespart.
  if (rejected) {
    stat.push(`${rejected} × keine Person${known ? ` (${known} hier erkannt)` : ''}`);
  }
  return (
    `<div class="idy-top">` +
    `<div class="idy-stat">${stat.join(' · ')}</div>` +
    `<div class="idy-tools">` +
    `<button type="button" class="idy-btn" data-idy="reload">Aktualisieren</button>` +
    `<button type="button" class="idy-btn" data-idy="sweep">Gesichter suchen</button>` +
    `<button type="button" class="idy-btn idy-btn-go" data-idy="auto"${ready ? '' : ' disabled'}>` +
    `Vorschläge übernehmen${ready ? ` (${ready})` : ''}</button>` +
    `</div></div>` +
    // EINE Zeile, einmal, und dann nie wieder erklärt: was hier
    // verglichen wird, ist der ganze Personen-Ausschnitt — Silhouette,
    // Kleidung, Ort, Licht — und nicht das Gesicht. Wer das nicht weiß,
    // hält eine schwache Quote für einen Fehler statt für die Physik des
    // Verfahrens.
    `<div class="idy-note">Verglichen wird der ganze Personen-Ausschnitt ` +
    `(Silhouette, Kleidung, Ort), nicht das Gesicht. Zuordnungen von ` +
    `verschiedenen Tagen bringen deshalb am meisten.` +
    (total ? ` <b>${total.hits}/${total.checked}</b> wiedererkannt.` : '') +
    `</div>`
  );
}

/** Nur die Zuordnungs-Leiste neu zeichnen.
 *
 *  Das Antippen einer Kachel ändert AUSSCHLIESSLICH sie — würde dabei
 *  das ganze Raster neu geschrieben, dekodierte das Telefon bei jedem
 *  Tipp bis zu sechzig Bilder erneut, und genau während des Auswählens
 *  flackert dann alles, was man gerade vergleicht. */
function _paintBar() {
  const slot = _mount()?.querySelector('.idy-bar-slot');
  if (!slot) return;
  const chosen = selectionItems(_faces, _selected);
  slot.innerHTML = assignBarHtml(chosen.length, _names(), agreedSuggestion(chosen));
  const form = slot.querySelector('.idy-new');
  form?.addEventListener('submit', (e) => {
    e.preventDefault();
    const value = (form.querySelector('.idy-input')?.value || '').trim();
    if (value) _assign(value);
  });
}

function _paint() {
  const el = _mount();
  if (!el) return;
  el.innerHTML =
    _topHtml() +
    personsHtml(_data.persons) +
    catsHtml(_data.cats) +
    `<div class="idy-sub">Neue Gesichter</div>` +
    facesHtml(_faces, _selected) +
    `<div class="idy-bar-slot"></div>`;
  _paintBar();
}

/** Alles neu holen. `keepSelection` nur, wenn die Auswahl noch gilt. */
export async function loadIdentities({ keepSelection = false } = {}) {
  const el = _mount();
  if (!el) return;
  if (!keepSelection) _selected.clear();
  try {
    const [summary, crops] = await Promise.all([api.loadIdentities(), api.loadUnnamedFaces()]);
    _data = {
      persons: summary.persons || [],
      cats: summary.cats || [],
      crops: summary.crops || {},
      quality: summary.quality || {},
    };
    _faces = crops.items || [];
    _loaded = true;
  } catch {
    _data = { persons: [], cats: [], crops: {}, quality: {} };
    _faces = [];
  }
  _paint();
}

async function _guard(label, fn) {
  if (_busy) return;
  _busy = true;
  try {
    await fn();
  } catch (e) {
    showToast(`${label} fehlgeschlagen: ${e?.message || ''}`, 'error');
  } finally {
    _busy = false;
  }
}

async function _assign(name, { anonymous = false } = {}) {
  const items = selectionItems(_faces, _selected);
  if (!items.length || (!name && !anonymous)) return;
  await _guard('Zuordnen', async () => {
    const res = await api.assignFaces(name, items, { anonymous });
    if (!res?.ok) throw new Error(res?.error || 'abgelehnt');
    showToast(`${res.filed} × „${res.name || name}" gemerkt`, 'success');
    await loadIdentities();
  });
}

async function _reject() {
  const items = selectionItems(_faces, _selected);
  if (!items.length) return;
  await _guard('Ablehnen', async () => {
    const res = await api.rejectFaces(items);
    if (!res?.ok) throw new Error(res?.error || 'abgelehnt');
    showToast(`${res.rejected} × „${res.bucket}" gemerkt`, 'success');
    await loadIdentities();
  });
}

async function _autoAssign() {
  await _guard('Übernehmen', async () => {
    const res = await api.autoAssignFaces();
    if (!res?.ok) throw new Error(res?.error || 'abgelehnt');
    showToast(
      res.filed ? `${res.filed} automatisch zugeordnet` : 'Nichts war sicher genug',
      res.filed ? 'success' : 'error',
    );
    await loadIdentities();
  });
}

async function _sweep() {
  await _guard('Suche', async () => {
    const res = await api.sweepFaces();
    showToast(
      res?.ok
        ? 'Suche läuft — die Gesichter erscheinen nach und nach.'
        : 'Ein Lauf ist bereits unterwegs.',
      res?.ok ? 'success' : 'error',
    );
  });
}

async function _toggleWhitelist(name) {
  const profile = _data.persons.find((p) => p.name === name);
  if (!profile) return;
  await _guard('Whitelist', async () => {
    await api.setPersonFlags(name, { whitelisted: !profile.whitelisted });
    await loadIdentities({ keepSelection: true });
  });
}

async function _forget(name) {
  if (!(await showConfirm(`„${name}" vergessen? Die Ausschnitte bleiben erhalten.`))) return;
  await _guard('Vergessen', async () => {
    await api.deletePerson(name);
    await loadIdentities({ keepSelection: true });
  });
}

/** Umbenennen an Ort und Stelle. Ist der neue Name schon vergeben, führt
 *  der Server die beiden Profile zusammen — das ist hier keine Panne,
 *  sondern der einzige Weg, zwei Karten derselben Person zu vereinen. */
function _startRename(card, name) {
  const slot = card?.querySelector('.idy-id');
  if (!slot) return;
  slot.innerHTML =
    `<form class="idy-ren"><input type="text" class="idy-input" aria-label="Neuer Name">` +
    `<button type="submit" class="idy-add">OK</button></form>`;
  const input = slot.querySelector('.idy-input');
  if (input) {
    input.value = name;
    input.focus();
    input.select();
  }
  slot.querySelector('.idy-ren')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const to = (input?.value || '').trim();
    if (!to || to === name) return _paint();
    await _guard('Umbenennen', async () => {
      const res = await api.renamePerson(name, to);
      if (!res?.ok) throw new Error('Name nicht vergeben');
      await loadIdentities({ keepSelection: true });
    });
  });
}

function _toggleFace(tile) {
  const relpath = tile?.dataset.relpath;
  if (!relpath) return;
  if (_selected.has(relpath)) _selected.delete(relpath);
  else _selected.add(relpath);
  tile.setAttribute('aria-pressed', _selected.has(relpath) ? 'true' : 'false');
  _paintBar();
}

const _ACTIONS = {
  sweep: _sweep,
  auto: _autoAssign,
  // Der Nachlauf arbeitet im Hintergrund weiter — hiermit holt man
  // nach, was er seither gefunden hat.
  reload: () => loadIdentities(),
  unselect: () => {
    _selected.clear();
    _mount()
      ?.querySelectorAll('.idy-face[aria-pressed="true"]')
      .forEach((el) => el.setAttribute('aria-pressed', 'false'));
    _paintBar();
  },
};

function _onClick(e) {
  const face = e.target.closest?.('.idy-face');
  if (face) return _toggleFace(face);
  const btn = e.target.closest?.('[data-idy]');
  if (!btn) return;
  const { idy, name } = btn.dataset;
  if (_ACTIONS[idy]) return _ACTIONS[idy]();
  if (idy === 'assign') return _assign(name);
  if (idy === 'assign-anon') return _assign('', { anonymous: true });
  if (idy === 'reject') return _reject();
  if (idy === 'wl') return _toggleWhitelist(name);
  if (idy === 'forget') return _forget(name);
  if (idy === 'rename') return _startRename(btn.closest('.idy-card'), name);
}

/** Erst beim Aufklappen laden, danach nicht wieder von selbst. */
export function initIdentities() {
  const section = byId(SECTION);
  const el = _mount();
  if (!section || !el) return;
  el.addEventListener('click', _onClick);
  section.addEventListener('set-section-open', () => {
    if (!_loaded) loadIdentities();
  });
  if (section.classList.contains('open')) loadIdentities();
}

// Das Modul wird als ES-Modul geladen, also normalerweise VOR
// DOMContentLoaded — aber nicht garantiert. Ist das Dokument schon
// fertig, käme das Ereignis nie mehr, und die Karte bliebe stumm.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initIdentities);
} else {
  initIdentities();
}
window.loadIdentities = loadIdentities;
