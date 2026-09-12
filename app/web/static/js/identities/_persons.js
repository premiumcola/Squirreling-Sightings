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
  if (profile?.anonymous) parts.push('ohne Namen');
  if (profile?.whitelisted) parts.push('Whitelist');
  if (profile?.notes) parts.push(String(profile.notes));
  return parts.join(' · ');
}

/** PURE: was der Güte-Balken sagt.
 *
 *  „Vielleicht das Halbieren, die Menge, und die eine Menge mit der
 *  anderen erkennen und sagen, wie gut Du's schon erkennst." Genau das
 *  rechnet der Server (identity_quality.py); hier steht nur, wie man es
 *  liest — und was man tun kann, wenn es noch nichts zu lesen gibt.
 *
 *  Eine 0 % zu zeigen, wo nichts gemessen werden KONNTE, wäre die
 *  unehrlichste Variante: sie sähe aus wie ein schlechtes Profil statt
 *  wie ein ungeprüftes. */
export function qualityLine(quality) {
  if (!quality) return null;
  if (quality.state !== 'gemessen') {
    return {
      pct: null,
      text: 'noch nicht messbar',
      hint: 'Ordne Ausschnitte aus einem zweiten Auftritt zu — aus einem einzigen Clip lässt sich nichts prüfen.',
    };
  }
  const pct = Math.round((Number(quality.rate) || 0) * 100);
  const parts = [`${quality.hits} von ${quality.checked} wiedererkannt`];
  if (quality.confused) parts.push(`${quality.confused}× verwechselt`);
  return { pct, text: parts.join(' · '), hint: '' };
}

function _qualityHtml(profile) {
  const q = qualityLine(profile?.quality);
  if (!q) return '';
  if (q.pct === null) {
    return `<span class="idy-q idy-q--none" title="${esc(q.hint)}">${esc(q.text)}</span>`;
  }
  const tone = q.pct >= 80 ? 'good' : q.pct >= 50 ? 'mid' : 'weak';
  return (
    `<span class="idy-q idy-q--${tone}" title="${esc(q.text)}">` +
    `<span class="idy-q-track"><span class="idy-q-fill" style="width:${q.pct}%"></span></span>` +
    `<span class="idy-q-num">${q.pct}\u00a0%</span></span>`
  );
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
    `<div class="idy-card${profile?.whitelisted ? ' is-wl' : ''}` +
    `${profile?.anonymous ? ' is-anon' : ''}">` +
    `<span class="idy-av">${personAvatar(profile)}</span>` +
    `<span class="idy-id"><span class="idy-name">${esc(name)}</span>` +
    `<span class="idy-meta">${esc(personMeta(profile))}</span>` +
    _qualityHtml(profile) +
    `</span>` +
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

//: Deutsche Namen der Vergleichsbereiche. Spiegel von
//: cat_identity.REGIONS — steht hier, weil nur die Oberfläche sie
//: ausspricht.
const _REGION_DE = { full: 'Ganze Person', upper: 'Oberkörper', head: 'Kopf' };

/** PURE: die Bereiche als Zeilen, beste Quote zuerst.
 *
 *  „ich würde sagen du solltest eher auf die köpfe gehen die müssen ja
 *  wiedererkannt werden! - komplett weis ich nicht ob das sinn macht!"
 *  — die Zeilen sind die Antwort darauf. Bereiche ohne geprüfte Probe
 *  fallen raus statt mit 0 % dazustehen. */
export function regionRows(regions, active) {
  return Object.entries(regions || {})
    .filter(([, r]) => r && r.checked)
    .map(([key, r]) => ({
      key,
      label: _REGION_DE[key] || key,
      pct: Math.round((Number(r.rate) || 0) * 100),
      checked: r.checked,
      hits: r.hits,
      active: key === active,
    }))
    .sort((a, b) => b.pct - a.pct);
}

/** Der Vergleich als kleine Tabelle. Leer, solange nichts gemessen ist. */
export function regionsHtml(regions, active) {
  const rows = regionRows(regions, active);
  if (!rows.length) return '';
  return (
    `<div class="idy-sub">Was besser wiedererkennt</div>` +
    `<div class="idy-regions">` +
    rows
      .map(
        (r) =>
          `<div class="idy-reg${r.active ? ' is-active' : ''}">` +
          `<span class="idy-reg-name">${esc(r.label)}${r.active ? ' ·&nbsp;aktiv' : ''}</span>` +
          `<span class="idy-q-track"><span class="idy-q-fill" style="width:${r.pct}%"></span></span>` +
          `<span class="idy-reg-num">${r.pct}\u00a0%</span>` +
          `<span class="idy-reg-of">${r.hits}/${r.checked}</span></div>`,
      )
      .join('') +
    `</div>`
  );
}
