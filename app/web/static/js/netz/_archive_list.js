// ─── netz/_archive_list.js ─────────────────────────────────────────────────
// Verlauf — the list, its filters, and the header stat.
//
// Structure copied from storms/_list.js (list → detail → one section,
// one state in the DOM at a time, so the back button navigates for free
// and there is no modal-in-modal on iOS). storms/ itself is NOT extended:
// its state, its class vocabulary and its compare slots are all
// weather-specific.
//
// storms/_list.js's PROGRESSIVE DISCLOSURE rule is adopted verbatim: a
// control appears when it starts doing something. Camera chips at >= 2
// cameras, class chips at >= 4 records, the "nur offen" toggle at >= 1
// unjudged. Below those counts the control is ABSENT, not disabled — no
// dead chrome.

import { esc } from '../core/dom.js';
import { archiveFrameUrl } from './_api.js';
import { netzState } from './_state.js';
import { classChip, fmtDateTime, labelDe, verdictWord } from './_helpers.js';

const MIN_CAMS_FOR_CHIPS = 2;
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

function _camChips(data) {
  const cams = data.cameras || [];
  if (cams.length < MIN_CAMS_FOR_CHIPS) return '';
  const sel = netzState.archiveFilter.cam;
  const all =
    `<button type="button" class="netz-pill${sel ? '' : ' is-active'}" ` +
    `data-arc-cam="">Alle</button>`;
  return `<div class="netz-pills">${all}${cams
    .map(
      (c) =>
        `<button type="button" class="netz-pill${sel === c.id ? ' is-active' : ''}" ` +
        `data-arc-cam="${esc(c.id)}">${esc(c.name)}</button>`,
    )
    .join('')}</div>`;
}

function _classChips(data) {
  if ((data.total || 0) < MIN_RECORDS_FOR_CLASS_CHIPS) return '';
  const labels = data.labels || [];
  if (labels.length < 2) return '';
  const sel = netzState.archiveFilter.label;
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

function _openToggle(data) {
  if (!data.unjudged) return '';
  const on = netzState.archiveFilter.open;
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
    `<span class="netz-arc-l1">${classChip(row.label)}` +
    `<span class="netz-arc-cam">${esc(row.cam_name || '')}</span>` +
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
    `<div class="netz-empty-sub">Sobald eine Kamera etwas Unsicheres sieht, fragt ` +
    `Squirreling per Telegram nach — und der Moment landet hier.</div></div>`
  );
}

export function renderArchiveList(host, data, handlers) {
  if (!data || !data.items?.length) {
    const noFilter =
      !netzState.archiveFilter.cam &&
      !netzState.archiveFilter.label &&
      !netzState.archiveFilter.open;
    host.innerHTML = noFilter
      ? _emptyHtml()
      : `${_camChips(data || {})}${_classChips(data || {})}` +
        `<div class="netz-empty"><div class="netz-empty-sub">Keine Einträge in dieser ` +
        `Auswahl.</div></div>`;
    _bind(host, handlers);
    return;
  }
  host.innerHTML =
    _headHtml(data) +
    _camChips(data) +
    _classChips(data) +
    _openToggle(data) +
    `<div class="netz-arc-rows">${data.items.map(_rowHtml).join('')}</div>`;
  _bind(host, handlers);
}

function _bind(host, handlers) {
  host.querySelectorAll('[data-arc-cam]').forEach((b) =>
    b.addEventListener('click', () => {
      netzState.archiveFilter.cam = b.dataset.arcCam || null;
      handlers.reload();
    }),
  );
  host.querySelectorAll('[data-arc-label]').forEach((b) =>
    b.addEventListener('click', () => {
      netzState.archiveFilter.label = b.dataset.arcLabel || null;
      handlers.reload();
    }),
  );
  host.querySelector('[data-arc-open]')?.addEventListener('click', () => {
    netzState.archiveFilter.open = !netzState.archiveFilter.open;
    handlers.reload();
  });
  host
    .querySelectorAll('[data-arc-id]')
    .forEach((b) => b.addEventListener('click', () => handlers.openDetail(b.dataset.arcId)));
}
