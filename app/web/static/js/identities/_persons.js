// ─── identities/_persons.js ────────────────────────────────────────────────
// Die benannten Identitäten als Karten: Gesicht, Name, wie viele Proben
// dahinterstehen, und die drei Handgriffe, die es dazu gibt —
// umbenennen (das ist zugleich das Zusammenführen), Whitelist an/aus,
// vergessen.
//
// KATZEN STEHEN DANEBEN, NICHT DARUNTER. Beide kommen aus derselben
// Registry-Form, aber Ausschnitte schneidet nur der Personen-Nachlauf, und
// eine Katzenkarte ohne Bild neben einer Personenkarte mit Bild sähe nach
// einem Fehler aus. Deshalb: Personen mit Gesicht, Katzen als schlichte
// Zeile.
import { esc } from '../core/dom.js';

/** PURE: die Zeile unter dem Namen. „12 Proben · Whitelist" */
export function personMeta(profile) {
  const n = Number(profile?.samples || 0);
  const parts = [`${n} ${n === 1 ? 'Probe' : 'Proben'}`];
  if (profile?.whitelisted) parts.push('Whitelist');
  if (profile?.notes) parts.push(String(profile.notes));
  return parts.join(' · ');
}

/** PURE: das Avatar einer Person — ihr erster Ausschnitt, sonst Initiale. */
export function personAvatar(profile) {
  const url = (profile?.crops || [])[0];
  if (url) return `<img class="idy-av-img" src="${esc(url)}" alt="" loading="lazy">`;
  const initial = String(profile?.name || '?')
    .trim()
    .charAt(0)
    .toUpperCase();
  return `<span class="idy-av-txt">${esc(initial || '?')}</span>`;
}

function _iconBtn(action, name, label, path) {
  return (
    `<button type="button" class="idy-act" data-idy="${action}" data-name="${esc(name)}" ` +
    `title="${esc(label)}" aria-label="${esc(label)}">` +
    `<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" ` +
    `stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
    `${path}</svg></button>`
  );
}

const _PENCIL = '<path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z"/>';
const _TRASH = '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/>';
const _SHIELD = '<path d="M12 3l7 3v6c0 4-3 6.5-7 9-4-2.5-7-5-7-9V6z"/>';

function _personCard(profile) {
  const name = profile?.name || '';
  return (
    `<div class="idy-card${profile?.whitelisted ? ' is-wl' : ''}">` +
    `<span class="idy-av">${personAvatar(profile)}</span>` +
    `<span class="idy-id"><span class="idy-name">${esc(name)}</span>` +
    `<span class="idy-meta">${esc(personMeta(profile))}</span></span>` +
    `<span class="idy-acts">` +
    _iconBtn('wl', name, profile?.whitelisted ? 'Whitelist aus' : 'Whitelist an', _SHIELD) +
    _iconBtn('rename', name, 'Umbenennen oder zusammenführen', _PENCIL) +
    _iconBtn('forget', name, 'Profil vergessen', _TRASH) +
    `</span></div>`
  );
}

/** Die Personenliste. Leer heißt: es wurde noch nichts benannt. */
export function personsHtml(persons) {
  if (!persons || !persons.length) {
    return (
      `<div class="idy-empty">Noch niemand benannt. Ordne unten ein paar Gesichter zu — ` +
      `ab dann schlägt die Erkennung die nächsten von selbst vor.</div>`
    );
  }
  return `<div class="idy-cards">${persons.map(_personCard).join('')}</div>`;
}

/** Die Katzen: dieselbe Registry, aber ohne Ausschnitte — also eine Zeile. */
export function catsHtml(cats) {
  if (!cats || !cats.length) return '';
  return (
    `<div class="idy-sub">Katzen</div><div class="idy-tags">` +
    cats.map((c) => `<span class="idy-tag">${esc(c?.name || '')}</span>`).join('') +
    `</div>`
  );
}
