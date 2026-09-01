// ─── netz/_archive_list.js ─────────────────────────────────────────────────
// Verlauf — the list, its filters, and the header stat. ONE camera's
// history: the panel that mounts this already knows which camera it is
// (its own `fetchArchive({cam: camId, …})` call), so there is no camera
// picker here any more — that only made sense back when one shared
// Verlauf view covered every camera at once.
//
// Structure copied from storms/_list.js (list → detail → one section,
// one state in the DOM at a time, so the back button navigates for free
// and there is no modal-in-modal on iOS). storms/ itself is NOT extended:
// its state, its class vocabulary and its compare slots are all
// weather-specific.
//
// storms/_list.js's PROGRESSIVE DISCLOSURE rule is adopted verbatim: a
// control appears when it starts doing something. Class chips at >= 4
// records, the "nur offen" toggle at >= 1 unjudged. Below those counts the
// control is ABSENT, not disabled — no dead chrome.

import { esc } from '../core/dom.js';
import { archiveFrameUrl } from './_api.js';
import { archiveFilterFor } from './_state.js';
import { classChip, fmtDateTime, labelDe, settingChip, verdictWord } from './_helpers.js';

const MIN_RECORDS_FOR_CLASS_CHIPS = 4;

// The audit sentence the whole feature exists to be able to print.
// Computed over the whole FILTERED set, never over the visible page.
function _headHtml(data) {
  const stat = data.answered
    ? `Von ${data.answered} Antworten ${
        data.moved === 1 ? 'hat 1 einen Wert' : `haben ${data.moved} einen Wert`
      } bewegt.`
    : 'Noch keine Antwort ausgewertet.';
  return `<div class="netz-arc-head"><span class="netz-arc-stat">${esc(stat)}</span></div>`;
}

function _classChips(data, camId) {
  if ((data.total || 0) < MIN_RECORDS_FOR_CLASS_CHIPS) return '';
  const labels = data.labels || [];
  if (labels.length < 2) return '';
  const sel = archiveFilterFor(camId).label;
  return (
    `<div class="netz-pills">` +
    `<button type="button" class="netz-pill${sel ? '' : ' is-active'}" data-arc-label="">` +
    `Alle Klassen</button>` +
    labels
      .map(
        (l) =>
          `<button type="button" class="netz-pill${sel === l ? ' is-active' : ''}" ` +
          `data-arc-label="${esc(l)}">${esc(labelDe(l))}</button>`,
      )
      .join('') +
    `</div>`
  );
}

function _openToggle(data, camId) {
  if (!data.unjudged) return '';
  const on = archiveFilterFor(camId).open;
  return (
    `<button type="button" class="netz-toggle${on ? ' is-on' : ''}" data-arc-open>` +
    `Nur offen <span class="netz-toggle-n">${data.unjudged}</span></button>`
  );
}

function _thumb(row) {
  if (!row.has_frame) {
    return `<span class="netz-arc-thumb netz-arc-thumb--net" aria-hidden="true">◎</span>`;
  }
  return (
    `<img class="netz-arc-thumb" loading="lazy" alt="" ` +
    `src="${esc(archiveFrameUrl(row.event_id))}" onerror="this.style.visibility='hidden'">`
  );
}

function _rowHtml(row) {
  const score = Number.isFinite(Number(row.score))
    ? ` · ${Math.round(Number(row.score) * 100)} %`
    : '';
  return (
    `<button type="button" class="netz-arc-row" data-arc-id="${esc(row.event_id)}">` +
    _thumb(row) +
    `<span class="netz-arc-body">` +
    // A camera-wide change carries no class — its field name takes the
    // chip's place so the row still says WHAT moved at a glance.
    `<span class="netz-arc-l1">${classChip(row.label) || settingChip(row.field_de)}` +
    `<span class="netz-arc-time">${esc(fmtDateTime(row.ts))}${esc(score)}</span></span>` +
    `<span class="netz-arc-l2"><span class="netz-badge" data-state="${esc(row.state)}">` +
    `${esc(row.badge)}</span>${esc(verdictWord(row))}</span>` +
    `<span class="netz-arc-l3">${esc(row.reason_de || '')}</span>` +
    `</span></button>`
  );
}

// The calm empty state, not a spinner. Mirrors storms.html's approach:
// this is also what is on screen between paint and hydration.
function _emptyHtml() {
  return (
    `<div class="netz-empty">` +
    `<div class="netz-empty-title">Noch nichts gefragt.</div>` +
    `<div class="netz-empty-sub">Sobald diese Kamera etwas Unsicheres sieht, fragt ` +
    `Squirreling per Telegram nach — und der Moment landet hier.</div></div>`
  );
}

export function renderArchiveList(host, data, camId, handlers) {
  if (!data || !data.items?.length) {
    const filter = archiveFilterFor(camId);
    const noFilter = !filter.label && !filter.open;
    host.innerHTML = noFilter
      ? _emptyHtml()
      : `${_classChips(data || {}, camId)}` +
        `<div class="netz-empty"><div class="netz-empty-sub">Keine Einträge in dieser ` +
        `Auswahl.</div></div>`;
    _bind(host, camId, handlers);
    return;
  }
  host.innerHTML =
    _headHtml(data) +
    _classChips(data, camId) +
    _openToggle(data, camId) +
    `<div class="netz-arc-rows">${data.items.map(_rowHtml).join('')}</div>`;
  _bind(host, camId, handlers);
}

function _bind(host, camId, handlers) {
  host.querySelectorAll('[data-arc-label]').forEach((b) =>
    b.addEventListener('click', () => {
      archiveFilterFor(camId).label = b.dataset.arcLabel || null;
      handlers.reload();
    }),
  );
  host.querySelector('[data-arc-open]')?.addEventListener('click', () => {
    const filter = archiveFilterFor(camId);
    filter.open = !filter.open;
    handlers.reload();
  });
  host
    .querySelectorAll('[data-arc-id]')
    .forEach((b) => b.addEventListener('click', () => handlers.openDetail(b.dataset.arcId)));
}
