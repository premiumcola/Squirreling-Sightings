// ─── storms/_list.js ───────────────────────────────────────────────────────
// Liste — Jahres-Kennzahlen, Sortierung, Klassen-Filter, Episodenzeilen,
// Auswahl-Modus.
//
// Progressive disclosure is the rule here: every control appears exactly
// when it starts doing something. Rank chips and the sort toggle need
// ≥ 3 episodes (a "①" among two items is noise), the class filter needs
// ≥ 4 (filtering three items is theatre), the year selector needs ≥ 2
// years. Below those counts the controls are ABSENT, not disabled — no
// dead chrome.

import { esc } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { _wsStatsState } from '../weather/stats.js';
import {
  stormsState,
  STORM_CLASS_ORDER,
  STORM_MAX_COMPARE,
  slotAssign,
  slotRelease,
  selectedCount,
  selectedIds,
  slotsClear,
} from './_state.js';
import {
  classMeta,
  effectiveClass,
  episodeTitle,
  episodeYear,
  fmtDayMonth,
  fmtDuration,
  fmtMetric,
  fmtNumberDe,
  fmtTime,
  leadPeak,
  thresholdFor,
} from './_helpers.js';

const FILM_ICON =
  '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14"/></svg>';

export function yearsPresent() {
  const set = new Set();
  for (const ep of stormsState.episodes) {
    const y = episodeYear(ep);
    if (y) set.add(y);
  }
  return [...set].sort((a, b) => b - a);
}

export function activeYear() {
  const years = yearsPresent();
  if (stormsState.year && years.includes(stormsState.year)) return stormsState.year;
  return years[0] || new Date().getFullYear();
}

export function episodesOfYear() {
  const y = activeYear();
  return stormsState.episodes.filter((ep) => episodeYear(ep) === y);
}

// Top-3 by intensity WITHIN the selected year → id → 1|2|3. Rank is a
// property of the row, not a separate list: in chronological order the
// operator still sees which rows are the year's monsters, and switching
// to "Stärkste" just brings them to the top.
function _rankMap(list) {
  if (list.length < 3) return {};
  const top = [...list]
    .sort((a, b) => (Number(b.intensity) || 0) - (Number(a.intensity) || 0))
    .slice(0, 3);
  const map = {};
  top.forEach((ep, i) => {
    map[ep.id] = i + 1;
  });
  return map;
}

// Aggregates only — deliberately names no individual episode, otherwise
// it duplicates the top row of the list underneath it.
function _statsLine(list) {
  const year = activeYear();
  const rain = list.reduce((sum, ep) => sum + (Number(ep.totals?.precipitation_mm) || 0), 0);
  const gust = list.reduce((mx, ep) => Math.max(mx, Number(ep.peaks?.wind_gusts_10m) || 0), 0);
  const parts = [`${year}`, `${list.length} Gewitter`];
  if (rain > 0) parts.push(`${fmtNumberDe(rain, 0)} mm Regen`);
  if (gust > 0) parts.push(`stärkste Böe ${fmtNumberDe(gust, 0)} km/h`);
  return parts.join(' · ');
}

function _sorted(list) {
  if (stormsState.sort === 'strongest') {
    return [...list].sort((a, b) => (Number(b.intensity) || 0) - (Number(a.intensity) || 0));
  }
  return [...list].sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
}

function _filtered(list) {
  const sel = stormsState.filter;
  if (!(sel instanceof Set) || sel.size === 0) return list;
  return list.filter((ep) => sel.has(effectiveClass(ep)));
}

// ── head ──────────────────────────────────────────────────────────────

function _headHtml(list) {
  const years = yearsPresent();
  let ctl = '';
  if (years.length > 1) {
    ctl += `<div class="ws-stats-pills st-years" role="tablist" aria-label="Jahr">${years
      .map(
        (y) =>
          `<button type="button" class="ws-stats-pill st-pill${y === activeYear() ? ' is-active' : ''}" data-year="${y}">${y}</button>`,
      )
      .join('')}</div>`;
  }
  if (list.length >= 3) {
    ctl += `<div class="ws-stats-pills st-sort" role="tablist" aria-label="Sortierung">
      <button type="button" class="ws-stats-pill st-pill${stormsState.sort === 'recent' ? ' is-active' : ''}" data-sort="recent">Neueste</button>
      <button type="button" class="ws-stats-pill st-pill${stormsState.sort === 'strongest' ? ' is-active' : ''}" data-sort="strongest">Stärkste</button>
    </div>`;
  }
  if (list.length >= 2 || stormsState.selecting) {
    const label = stormsState.selecting ? 'Auswahl beenden' : 'Vergleichen';
    ctl += `<button type="button" class="btn btn-action st-compare-enter" data-act="toggle-select">${label}</button>`;
  } else if (list.length === 1) {
    ctl += `<button type="button" class="btn btn-action st-compare-enter" disabled>Vergleich ab 2 Gewittern</button>`;
  }
  return `<div class="st-head">
      <span class="ws-title"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><use href="#icon-bolt"/></svg>Gewitter-Archiv</span>
      <span class="ws-subtitle st-yearline">${esc(_statsLine(list))}</span>
      <div class="st-head-ctl">${ctl}</div>
    </div>`;
}

// Class filter — the existing weather-filter component, filtering on
// effective class. Only classes with count > 0 get a pill; sorted by
// count desc, ties by fixed class order.
function _filterHtml(list) {
  if (list.length < 4) return '';
  const counts = {};
  for (const ep of list) {
    const c = effectiveClass(ep);
    if (c) counts[c] = (counts[c] || 0) + 1;
  }
  const present = STORM_CLASS_ORDER.filter((c) => counts[c] > 0).sort((a, b) => {
    const d = counts[b] - counts[a];
    return d || STORM_CLASS_ORDER.indexOf(a) - STORM_CLASS_ORDER.indexOf(b);
  });
  if (!present.length) return '';
  const sel = stormsState.filter;
  let html = present
    .map((c) => {
      const m = classMeta(c);
      const active = sel.has(c);
      return `<button type="button" class="media-pill cat-filter-btn${active ? ' active' : ''}" data-class="${esc(c)}" style="--cb:${m.color}" aria-label="${esc(m.de)}, ${counts[c]} Gewitter"><span class="cfb-icon" style="pointer-events:none;color:${m.color}">${m.icon}</span><span style="pointer-events:none">${esc(m.de)}</span><span class="mp-count" style="pointer-events:none">${counts[c]}</span></button>`;
    })
    .join('');
  if (sel.size === 0) {
    html += `<span class="media-pill media-pill--status" aria-disabled="true">alle Filter aus</span>`;
  }
  return `<div class="ws-filter-bar st-filter" id="stormsFilterBar">${html}</div>`;
}

// ── row ───────────────────────────────────────────────────────────────

function _rankChip(rank, year) {
  if (!rank) return '';
  return `<span class="st-rank st-rank--${rank}" aria-label="Platz ${rank} von ${year}">${rank}</span>`;
}

function _rowHtml(ep, rank) {
  const cls = effectiveClass(ep);
  const meta = classMeta(cls);
  const pct = Math.max(0, Math.min(1, Number(ep.intensity) || 0)) * 100;
  const lead = leadPeak(ep);
  // One channel, one meaning. The bar is INTENSITY only, in the section
  // accent: four of the five class colours are near-identical
  // desaturated blue-greys (they are the app's weather palette, where
  // they always sit beside their own icon and label), so a 4 px bar
  // tinted with them carried no information at all — and one of them IS
  // the section accent. The class moves to the glyph, which has the room
  // to be told apart by SHAPE and keeps its own colour there.
  const bar = `<span class="st-bar" aria-hidden="true"><i style="width:${pct.toFixed(0)}%"></i></span>`;
  const icon = meta.icon
    ? `<span class="st-row-ic" style="color:${meta.color}" role="img" aria-label="${esc(meta.de)}" title="${esc(meta.de)}">${meta.icon}</span>`
    : '';
  const leadTxt = lead
    ? `<span class="st-lead">${esc(fmtMetric(lead.key, lead.value))}</span>`
    : '';
  // Footage chip only when the backend supplies the count — never
  // "▣ 0", never a per-row spinner.
  const fc = ep.footage_count;
  const foot =
    Number.isFinite(Number(fc)) && Number(fc) > 0
      ? `<span class="st-foot-chip" aria-label="${fc} Aufnahmen">${FILM_ICON}${fc}</span>`
      : '';
  const pick = stormsState.selecting ? _pickHtml(ep) : '';
  return `<div class="st-row" data-id="${esc(ep.id)}">
      ${pick}
      <a class="st-row-body" href="#/gewitter/${encodeURIComponent(ep.id)}">
        <span class="st-row-title">${_rankChip(rank, activeYear())}${icon}<span class="st-row-name">${esc(episodeTitle(ep))}</span></span>
        <span class="st-row-meta">${esc(fmtDayMonth(ep.started_at))} · ${esc(fmtTime(ep.started_at))} · ${esc(fmtDuration(ep.duration_min))}</span>
        <span class="st-row-foot">${bar}${leadTxt}${foot}</span>
      </a>
    </div>`;
}

// 44×44 pick button — a separate <button>, never nested inside the row
// link. While four are held, unselected rows go disabled.
function _pickHtml(ep) {
  const on = stormsState.slots.includes(ep.id);
  const full = selectedCount() >= STORM_MAX_COMPARE;
  const dis = !on && full ? ' disabled' : '';
  return `<button type="button" class="st-pick${on ? ' is-on' : ''}" data-pick="${esc(ep.id)}"${dis} aria-pressed="${on}" aria-label="${on ? 'Aus dem Vergleich entfernen' : 'Zum Vergleich hinzufügen'}"><span class="st-pick-box">${on ? '✓' : ''}</span></button>`;
}

// ── empty states ──────────────────────────────────────────────────────

// Day one. The threshold line is the whole trick: it proves the system
// is armed and watching. An empty state that shows what it is waiting
// for reads as ready; one that says only "keine Daten" reads as broken.
function _emptyHtml() {
  const thr = _wsStatsState.data?.thresholds || {};
  // `thresholdFor`, not `Number.isFinite`: the payload carries `null`
  // for a field with no configured event, and `Number(null)` is a
  // finite 0. Printing "Schnee 0,00 cm/h" would disprove the exact
  // thing this line exists to prove.
  const bits = [
    ['lightning_potential', 'Blitz'],
    ['precipitation', 'Regen'],
    ['snowfall', 'Schnee'],
  ]
    .map(([k, lbl]) => {
      const t = thresholdFor(thr, k);
      return Number.isFinite(t) ? `${lbl} ${fmtMetric(k, t)}` : '';
    })
    .filter(Boolean);
  const line = bits.length
    ? `<div class="st-empty-thr">Aktuelle Schwellen: ${esc(bits.join(' · '))}</div>`
    : '';
  return `<div class="ws-empty st-empty">
      <div class="st-empty-title">Noch kein Gewitter aufgezeichnet.</div>
      <div class="st-empty-sub">Das Archiv füllt sich automatisch, sobald Blitz-Potential, Niederschlag oder Böen die Schwelle überschreiten.</div>
      ${line}
    </div>`;
}

function _selectBarHtml() {
  if (!stormsState.selecting) return '';
  const n = selectedCount();
  const ready = n >= 2;
  const label = ready ? 'Vergleichen' : 'Vergleich ab 2 Gewittern';
  return `<div class="st-selbar" role="group" aria-label="Auswahl">
      <span class="st-selbar-count">${n} ausgewählt</span>
      <button type="button" class="btn st-selbar-cancel" data-act="cancel-select">Abbrechen</button>
      <button type="button" class="btn btn-action" data-act="do-compare"${ready ? '' : ' disabled'}>${label}</button>
    </div>`;
}

// ── public render ─────────────────────────────────────────────────────

export function renderList(host, onNavigate) {
  const all = episodesOfYear();
  // Auswahl-Modus puts a FIXED action bar over the bottom of the list on
  // phones; the class is what lets the stylesheet reserve room for it,
  // so the last rows can still be scrolled clear of it.
  host.classList.toggle('is-selecting', !!stormsState.selecting);
  if (!all.length) {
    host.innerHTML = _emptyHtml();
    return;
  }
  const ranks = _rankMap(all);
  const rows = _sorted(_filtered(all));
  const body = rows.length
    ? rows.map((ep) => _rowHtml(ep, ranks[ep.id])).join('')
    : '<div class="ws-empty">Keine Gewitter in dieser Auswahl.</div>';
  const hint =
    all.length === 1
      ? '<div class="st-more-hint">Weitere Gewitter erscheinen hier automatisch.</div>'
      : '';
  host.innerHTML =
    _headHtml(all) +
    _filterHtml(all) +
    `<div class="st-rows">${body}</div>` +
    hint +
    _selectBarHtml();
  _bind(host, onNavigate);
}

function _bind(host, onNavigate) {
  host.querySelectorAll('[data-year]').forEach((b) =>
    b.addEventListener('click', () => {
      stormsState.year = parseInt(b.dataset.year, 10);
      slotsClear();
      renderList(host, onNavigate);
    }),
  );
  host.querySelectorAll('[data-sort]').forEach((b) =>
    b.addEventListener('click', () => {
      stormsState.sort = b.dataset.sort;
      renderList(host, onNavigate);
    }),
  );
  host.querySelectorAll('[data-class]').forEach((b) =>
    b.addEventListener('click', () => {
      const c = b.dataset.class;
      if (stormsState.filter.has(c)) stormsState.filter.delete(c);
      else stormsState.filter.add(c);
      renderList(host, onNavigate);
    }),
  );
  host
    .querySelectorAll('[data-pick]')
    .forEach((b) => b.addEventListener('click', () => _onPick(b.dataset.pick, host, onNavigate)));
  host
    .querySelectorAll('[data-act]')
    .forEach((b) => b.addEventListener('click', () => _onAction(b.dataset.act, host, onNavigate)));
}

function _onPick(id, host, onNavigate) {
  if (stormsState.slots.includes(id)) {
    slotRelease(id);
  } else if (!slotAssign(id)) {
    showToast('Maximal 4 Gewitter vergleichen', 'warn');
    return;
  }
  renderList(host, onNavigate);
}

function _onAction(act, host, onNavigate) {
  if (act === 'toggle-select') {
    stormsState.selecting = !stormsState.selecting;
    if (!stormsState.selecting) slotsClear();
    renderList(host, onNavigate);
    return;
  }
  if (act === 'cancel-select') {
    stormsState.selecting = false;
    slotsClear();
    renderList(host, onNavigate);
    return;
  }
  if (act === 'do-compare') {
    const ids = selectedIds();
    if (ids.length >= 2) onNavigate(`#/gewitter/vergleich/${ids.join(',')}`);
  }
}
