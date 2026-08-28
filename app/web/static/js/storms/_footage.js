// ─── storms/_footage.js ────────────────────────────────────────────────────
// Aufnahmen — the footage column beside the detail chart.
//
// Groups are data-driven off each item's `kind`, so a future trigger
// kind (e.g. fog_dissolve) slots in with no renderer change. A group
// with zero items is not rendered at all.
//
// The degradation ladder matters more than the happy path here: with
// event_timelapse disabled on every camera the storm-purpose group is
// empty for every episode today, and that must not read as breakage.

import { esc } from '../core/dom.js';
import { openMediaView } from '../mediaview/index.js';

// Fixed render order + German headings. "Weitere Aufnahmen im Zeitraum"
// is deliberately honest: incidental footage that happens to overlap,
// not storm footage — labelling it as such stops the operator reading a
// rain-triggered motion clip as a storm recording.
const GROUPS = [
  { key: 'event_timelapse', title: 'Gewitter-Zeitraffer', cls: 'st-fg--hero' },
  { key: 'weather_clips', title: 'Wetter-Clips', cls: 'st-fg--duo' },
  { key: 'sun_timelapse', title: 'Sonnen-Zeitraffer', cls: 'st-fg--duo' },
  { key: '_other', title: 'Weitere Aufnahmen im Zeitraum', cls: 'st-fg--duo' },
];

const OTHER_CAP = 12;

const PLAY_ICON =
  '<svg viewBox="0 0 24 24" width="30" height="30" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';

// Merge the two incidental kinds into one group, sorted by overlap desc.
function _buckets(payload) {
  const g = payload?.groups || {};
  const out = {};
  for (const { key } of GROUPS) {
    if (key === '_other') continue;
    out[key] = Array.isArray(g[key]) ? g[key] : [];
  }
  const other = [...(g.timelapse || []), ...(g.motion || [])];
  other.sort((a, b) => (Number(b.overlap_s) || 0) - (Number(a.overlap_s) || 0));
  out._other = other;
  return out;
}

function _tileHtml(item, idx, groupKey) {
  const missing = item.missing_media || !item.video_url;
  const span = item.span || {};
  const thumb = missing
    ? '<div class="ws-card-thumb ws-card-thumb--orphan" aria-hidden="true"></div>'
    : `<img class="ws-card-thumb" loading="lazy" src="${esc(item.thumb_url || '')}" alt="" onerror="this.style.opacity=0.2"/>`;
  const time = esc(item.time_label || '');
  const cam = esc(item.cam_name || item.cam_id || '');
  return `<div class="ws-card st-tile${missing ? ' ws-card--orphan' : ''}" data-group="${esc(groupKey)}" data-idx="${idx}"
        data-span-start="${esc(span.start || '')}" data-span-end="${esc(span.end || '')}"
        ${missing ? 'title="Datei nicht mehr vorhanden"' : ''}>
      <div class="ws-card-thumb-wrap">
        ${thumb}
        ${missing ? '' : `<span class="ws-card-play">${PLAY_ICON}</span>`}
        <div class="ws-card-stack ws-card-stack--l">
          <div class="st-tile-badge">${time}</div>
          ${cam ? `<div class="st-tile-sub">${cam}</div>` : ''}
        </div>
      </div>
    </div>`;
}

// The single most valuable string this endpoint can return today: it
// turns an empty box into the one action that fixes it.
function _hintHtml(degraded, demoted) {
  const d = Array.isArray(degraded) ? degraded : [];
  if (d.includes('weather_service_unavailable')) {
    return '<div class="st-fhint st-fhint--muted">Wetterdienst nicht erreichbar — Aufnahmen konnten nicht geladen werden.</div>';
  }
  if (!d.includes('event_timelapse_disabled')) return '';
  const cls = demoted ? ' st-fhint--muted' : '';
  return `<div class="st-fhint${cls}">
      <div class="st-fhint-txt">Gewitter-Zeitraffer ist deaktiviert — für kommende Gewitter in den Kamera-Einstellungen aktivierbar.</div>
      <button type="button" class="btn btn-action" data-act="open-cam-weather">Kamera-Einstellungen öffnen</button>
    </div>`;
}

/**
 * Render the Aufnahmen column. Returns true when it drew any tiles —
 * the detail view collapses to a single full-width column when it did
 * not, because an empty column beside a chart is the thing that makes a
 * page look broken.
 */
export function renderFootage(host, payload) {
  const buckets = _buckets(payload);
  const total = Object.values(buckets).reduce((n, arr) => n + arr.length, 0);
  if (!total) {
    host.innerHTML =
      '<div class="st-fstrip">Keine Aufnahmen in diesem Zeitraum.</div>' +
      _hintHtml(payload?.degraded, false);
    _bind(host, buckets);
    return false;
  }
  let html = '';
  for (const g of GROUPS) {
    const items = buckets[g.key];
    if (!items.length) continue;
    const shown = g.key === '_other' ? items.slice(0, OTHER_CAP) : items;
    const more =
      items.length > shown.length
        ? `<button type="button" class="st-fmore" data-act="expand-other">Alle ${items.length} anzeigen</button>`
        : '';
    html += `<div class="st-fgroup ${g.cls}" data-group-key="${esc(g.key)}">
        <div class="st-fgroup-title">${g.title}</div>
        <div class="st-fgrid">${shown.map((it, i) => _tileHtml(it, i, g.key)).join('')}</div>
        ${more}
      </div>`;
  }
  // Populated groups render normally; the activation hint sits BELOW
  // them, demoted to muted 12 px.
  host.innerHTML = html + _hintHtml(payload?.degraded, true);
  _bind(host, buckets);
  return true;
}

// Weather kinds open in the MediaView shell via the same reshape
// weather/sightings.js already performs; motion hands off to the
// existing lightbox. No new player. Ever.
function _open(item) {
  if (!item || item.missing_media || !item.video_url) return;
  if (item.kind === 'motion') {
    if (typeof window.openLightbox === 'function') window.openLightbox(item);
    return;
  }
  openMediaView({
    mode: 'weather',
    item: {
      camera_name: item.cam_name || item.cam_id || '',
      time_label: [item.kind_label || '', item.time_label || ''].filter(Boolean).join(' · '),
      api_snapshot: item.api_snapshot,
      sun_snapshot: item.sun_snapshot,
      event_type: item.event_type,
    },
    source: { type: 'video', url: item.video_url, loop: true },
    actions: {},
  });
}

// Binding is idempotent: the expander re-enters this function to adopt
// the newly-rendered tiles, and a tile that is already wired must not
// collect a second click listener (that would open the player twice).
function _bind(host, buckets) {
  host.querySelectorAll('.st-tile').forEach((tile) => {
    if (tile.dataset.bound) return;
    tile.dataset.bound = '1';
    tile.addEventListener('click', () => {
      const arr = buckets[tile.dataset.group] || [];
      _open(arr[parseInt(tile.dataset.idx, 10)]);
    });
  });
  host.querySelector('[data-act="expand-other"]')?.addEventListener('click', () => {
    const arr = buckets._other || [];
    const grid = host.querySelector('[data-group-key="_other"] .st-fgrid');
    if (grid) grid.innerHTML = arr.map((it, i) => _tileHtml(it, i, '_other')).join('');
    host.querySelector('[data-act="expand-other"]')?.remove();
    _bind(host, buckets);
  });
  host.querySelector('[data-act="open-cam-weather"]')?.addEventListener('click', () => {
    document.querySelector('#cameras')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

/**
 * Chart → tiles. While the chart guide sits at `tMs`, every tile whose
 * span contains it gets a highlight ring (an inner box-shadow, not a
 * border — no thin lines in this design system). Pure timestamp
 * arithmetic: the endpoint already returns a per-item span and the
 * chart already knows its own time domain, so this needs no new state.
 */
export function highlightFootageAt(host, tMs) {
  host.querySelectorAll('.st-tile').forEach((tile) => {
    const a = Date.parse(tile.dataset.spanStart || '');
    const b = Date.parse(tile.dataset.spanEnd || '');
    const on =
      Number.isFinite(tMs) && Number.isFinite(a) && Number.isFinite(b) && tMs >= a && tMs <= b;
    tile.classList.toggle('is-cross', on);
  });
}
