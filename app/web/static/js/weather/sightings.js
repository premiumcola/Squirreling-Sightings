// ─── weather/sightings.js ──────────────────────────────────────────────────
// Stage 24 of the legacy.js → ES modules refactor — Wetter-Sichtungen
// grid + hash-anchor handler. Pure code move from legacy.js; the two
// _orig* monkey-patches that lived at the bottom of legacy.js have been
// folded directly into the function bodies (loadWeatherSightings ->
// loadWeatherRecaps; renderWeatherSightings -> _renderWeatherGrid) so
// callers see one definition, no double-override risk. Card templates
// live in ./_feed.js, pagination in ./_pagination.js, the MediaView
// lightbox openers in ./_lightbox.js, manual-event data+view in
// ./_manual-events.js — this file crossed the JS line ceiling and split
// into those four siblings, keeping only "load the sources, build the
// grid, wire the chip filter" here.
import { byId, esc } from '../core/dom.js';
import { state } from '../core/state.js';
import { apiGet, apiDelete } from '../core/api.js';
import { showToast } from '../core/toast.js';
import { WEATHER_TYPES } from '../core/weather-types.js';
import { fetchEpisodes } from '../storms/_api.js';
import {
  sightingCardHTML,
  recapCardHTML,
  episodeCardHTML,
  manualEventCardHTML,
  openStormEpisode,
  unifiedFeedItems,
} from './_feed.js';
import { openWeatherLightbox, openWeatherRecapLightbox } from './_lightbox.js';
import { weatherPageSize, renderWeatherPagination } from './_pagination.js';
import { loadWeatherManualEvents, openManualEventView } from './_manual-events.js';
import { withinZoom } from './_zoom.js';
import { bindPinToggle } from './pin-toggle.js';

// Matches MAX_SIGHTINGS_PAGE_SIZE in routes/weather.py. The gallery
// filters client-side over multi-select chips, so it needs the whole
// list; the cap keeps "whole" bounded on a large library.
const _FETCH_PAGE_SIZE = 500;

async function loadWeatherSightings(filter) {
  // Filter migrates from single-string to Set semantics: state.weather.filter
  // is a Set of event_type strings. Empty Set = "no filter, show everything"
  // (matches the Mediathek pill UX). The fetch asks for the full list
  // — filtering happens client-side in _renderWeatherGrid so toggling pills
  // doesn't trigger a network round-trip. The legacy single-string call site
  // is still tolerated: a string argument seeds a single-member Set.
  try {
    // Ask for the whole list explicitly. Without page_size the server
    // returns 50 while still counting every event, which is what made a
    // chip read "Starkregen 3" over an empty grid.
    const data = await apiGet(`/api/weather/sightings?page_size=${_FETCH_PAGE_SIZE}`);
    state.weather.items = data.items || [];
    state.weather.counts = data.counts || {};
    state.weather.total = data.total || 0;
    if (filter instanceof Set) {
      state.weather.filter = filter;
    } else if (typeof filter === 'string' && filter) {
      state.weather.filter = new Set([filter]);
    } else if (!(state.weather.filter instanceof Set)) {
      // First load → seed with every event type that has items, mirroring
      // the Mediathek "all on by default" rule.
      const present = Object.keys(WEATHER_TYPES).filter((t) => (state.weather.counts[t] || 0) > 0);
      state.weather.filter = new Set(present);
    }
    renderWeatherSightings();
  } catch (_err) {
    // silently degrade — section stays empty
  }
  // Recaps, Gewitter-episodes and manual events are event records like
  // any other and render inline in the same grid (see _renderWeatherGrid)
  // — loading them here keeps every source synced without a separate
  // boot hook.
  await loadWeatherRecaps();
  await loadStormEpisodes();
  await loadWeatherManualEvents();
  _renderWeatherGrid();
}

function renderWeatherSightings() {
  const block = byId('weatherSightingsBlock');
  if (!block) return;
  const sub = byId('weatherSightingsSubtitle');
  if (sub) {
    const yr = new Date().getFullYear();
    sub.textContent = `${state.weather.total} Ereignisse · ${yr}`;
  }
  _renderWeatherFilterPills();
  _renderWeatherGrid();
}

function _renderWeatherFilterPills() {
  const bar = byId('weatherFilterBar');
  if (!bar) return;
  // Render a filter pill ONLY for weather types that actually have events;
  // zero-count types are skipped entirely so the bar collapses to a single
  // row. Sort the survivors by count desc, ties by spec order.
  const types = Object.keys(WEATHER_TYPES);
  const counts = state.weather.counts || {};
  const sorted = types
    .filter((t) => (counts[t] || 0) > 0)
    .sort((a, b) => {
      const d = (counts[b] || 0) - (counts[a] || 0);
      return d || types.indexOf(a) - types.indexOf(b);
    });
  const sel = state.weather.filter instanceof Set ? state.weather.filter : new Set();
  let html = sorted
    .map((t) => {
      const meta = WEATHER_TYPES[t];
      const cnt = counts[t] || 0;
      const active = sel.has(t);
      const cls = `media-pill cat-filter-btn${active ? ' active' : ''}`;
      const cntChip = `<span class="mp-count" style="pointer-events:none">${cnt}</span>`;
      // Visible text: short `de` label. Tooltip + accessible name: full
      // `de_full` (falls back to `de` when not set) so screen readers and
      // hover tooltips keep the long form even when the chip itself is
      // truncated for space.
      const fullLbl = meta.de_full || meta.de;
      return `<button type="button" class="${cls}" data-type="weather" data-val="${esc(t)}" title="${esc(fullLbl)}" aria-label="${esc(fullLbl)}, ${cnt} Ereignisse" style="--cb:${meta.color}"><span class="cfb-icon" style="pointer-events:none;color:${meta.color}">${meta.icon}</span><span style="pointer-events:none">${esc(meta.de)}</span>${cntChip}</button>`;
    })
    .join('');
  if (sel.size === 0) {
    html += `<span class="media-pill media-pill--status" aria-disabled="true">alle Filter aus</span>`;
  }
  bar.innerHTML = html;
  bar.querySelectorAll('.media-pill').forEach((p) => {
    if (p.classList.contains('media-pill--status')) return;
    p.addEventListener('click', () => {
      const val = p.dataset.val;
      if (!(state.weather.filter instanceof Set)) state.weather.filter = new Set();
      if (state.weather.filter.has(val)) state.weather.filter.delete(val);
      else state.weather.filter.add(val);
      // Filter change can shrink the result set below the current
      // page — reset to page 0 so the user sees the freshest items
      // instead of an empty trailing page.
      state.weather.page = 0;
      // No fetch needed — filtering is client-side now.
      renderWeatherSightings();
    });
  });
}

// Delete a sighting straight from its card (Mediathek-style hover trash —
// no confirm modal; the heavier confirm lives in the lightbox). Fades the
// card, hits the same DELETE endpoint the lightbox uses, then re-fetches so
// the grid, filter pills and counts all reflect the removal.
function _deleteSightingCard(id, cardEl) {
  if (!id) return;
  if (cardEl) {
    cardEl.style.transition = 'opacity .2s, transform .2s';
    cardEl.style.opacity = '0';
    cardEl.style.transform = 'scale(0.96)';
  }
  apiDelete(`/api/weather/sightings/${encodeURIComponent(id)}`)
    .then(() => loadWeatherSightings(state.weather.filter))
    .catch((err) => {
      showToast('Löschen fehlgeschlagen: ' + (err?.message || err), 'error');
      if (cardEl) {
        cardEl.style.opacity = '';
        cardEl.style.transform = '';
      }
    });
}

function _renderWeatherGrid() {
  const grid = byId('weatherSightingsGrid');
  if (!grid) return;
  const empty = byId('weatherSightingsEmpty');
  const allItems = state.weather.items || [];
  // Client-side filter: include items whose event_type is in the active
  // filter Set. Empty Set = "no filter active → show all" (matches the
  // Mediathek mental model).
  const sel = state.weather.filter instanceof Set ? state.weather.filter : new Set();
  const items = sel.size === 0 ? allItems : allItems.filter((s) => sel.has(s.event_type));
  // The lightbox indexes prev/next into this same filtered list via the
  // absolute idx the sighting cards carry, regardless of where the
  // unified feed's sort places them on screen.
  state.weather.itemsFiltered = items;
  const merged = unifiedFeedItems(
    items,
    state.weather.recaps,
    state.weather.episodes,
    state.weather.manualEvents,
  );
  // A custom drag-zoom on the Wetterdaten chart narrows the SAME feed by
  // timestamp, on top of (not instead of) the chip filter above — both
  // apply simultaneously, and reset independently of one another.
  const feed = merged.filter((entry) => withinZoom(entry.ts));
  if (!feed.length) {
    grid.innerHTML = '';
    if (empty) empty.hidden = false;
    renderWeatherPagination(0, 0, _renderWeatherGrid);
    return;
  }
  if (empty) empty.hidden = true;
  const pageSize = weatherPageSize();
  const pageCount = Math.max(1, Math.ceil(feed.length / pageSize));
  let page = Number.isInteger(state.weather.page) ? state.weather.page : 0;
  if (page >= pageCount) page = pageCount - 1;
  if (page < 0) page = 0;
  state.weather.page = page;
  const sliceStart = page * pageSize;
  const visible = feed.slice(sliceStart, sliceStart + pageSize);
  // Pre-compute the active-camera id set so each sighting card can
  // decide whether to actually request its thumb. Sightings recorded
  // before a manuf/model edit carry the OLD canonical cam_id in their
  // sighting.id (the on-disk path was already renamed by storage_
  // migration), so the thumb URL 404s. Skipping the <img> tag for
  // those entries avoids the network request and keeps the console
  // clean — the card still renders with a placeholder so the user can
  // see the orphan exists and decide whether to delete it.
  const _activeCamIds = new Set((state.cameras || []).map((c) => c.id));
  grid.innerHTML = visible.map((entry) => _weatherFeedCardHTML(entry, _activeCamIds)).join('');
  _bindWeatherGridCards(grid);
  bindPinToggle(grid);
  renderWeatherPagination(feed.length, pageSize, _renderWeatherGrid);
}

// One switch, one place — picking the right card template per feed
// entry kind. Split out of _renderWeatherGrid to keep that function
// under the JS ceiling.
function _weatherFeedCardHTML(entry, activeCamIds) {
  if (entry.kind === 'sighting') {
    return sightingCardHTML(entry.data, entry.idx, activeCamIds.has(entry.data.cam_id));
  }
  if (entry.kind === 'recap') return recapCardHTML(entry.data, entry.idx);
  if (entry.kind === 'manual') return manualEventCardHTML(entry.data);
  return episodeCardHTML(entry.data);
}

// Click + delete + score-tip wiring for whatever mix of sighting/recap/
// episode/manual cards the current page rendered. Split out of
// _renderWeatherGrid to keep that function under the JS ceiling.
function _bindWeatherGridCards(grid) {
  grid.querySelectorAll('.ws-card').forEach((card) => {
    card.addEventListener('click', () => openWeatherLightbox(parseInt(card.dataset.idx, 10)));
  });
  grid.querySelectorAll('.ws-recap-card[data-recap-idx]').forEach((card) => {
    card.addEventListener('click', () =>
      openWeatherRecapLightbox(parseInt(card.dataset.recapIdx, 10)),
    );
  });
  grid.querySelectorAll('.ws-recap-card[data-ep-id]').forEach((card) => {
    card.addEventListener('click', () => openStormEpisode(card.dataset.epId));
  });
  grid.querySelectorAll('.ws-recap-card[data-manual-id]').forEach((card) => {
    card.addEventListener('click', () => openManualEventView(card.dataset.manualId));
  });
  // Hover-reveal delete (top-right) mirrors the Mediathek media-card:
  // stopPropagation so the trash tap removes the event instead of opening
  // the lightbox, then a re-fetch refreshes grid + filter counts.
  grid.querySelectorAll('.mmc-delete').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const card = btn.closest('.ws-card');
      if (card) _deleteSightingCard(card.dataset.id, card);
    });
  });
  // Score chips fire a toast with the metric explanation on tap —
  // title= alone is desktop-only. stopPropagation keeps the chip tap
  // from also opening the card lightbox.
  grid.querySelectorAll('.ws-score-chip').forEach((b) => {
    const tip = b.getAttribute('data-score-tip');
    if (!tip) return;
    const fire = (e) => {
      e.stopPropagation();
      showToast(tip, 'info');
    };
    b.addEventListener('click', fire);
    b.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        fire(e);
      }
    });
  });
}

// Window resize switches the page-size band (4 → 8 → 12). Re-render
// the grid so the user sees the right column count immediately and
// the page index gets clamped to the new page count.
let _wsResizeTimer = null;
window.addEventListener(
  'resize',
  () => {
    if (_wsResizeTimer) clearTimeout(_wsResizeTimer);
    _wsResizeTimer = setTimeout(() => {
      _renderWeatherGrid();
    }, 150);
  },
  { passive: true },
);

// ── Settings: Wetter-Ereignisse ──────────────────────────────────────────────

async function loadWeatherRecaps() {
  try {
    const d = await apiGet('/api/weather/recaps');
    state.weather.recaps = d.items || [];
  } catch (_err) {
    /* silent */
  }
  _renderWeatherGrid();
}

// fetchEpisodes() never throws (see storms/_api.js) — a missing or
// unreachable endpoint resolves to an empty list, same as day one.
async function loadStormEpisodes() {
  const { items } = await fetchEpisodes();
  state.weather.episodes = items;
  _renderWeatherGrid();
}

// ── Hash anchor handler — open lightbox for #weather/<id> on page load ──────

function _handleWeatherHashAnchor() {
  const h = window.location.hash || '';
  // Scroll to the new top-level #weather section (was a sub-block of
  // #achievements before the Sichtungen↔Wetter split). Falls back to the
  // inner block id for back-compat with any cached deep links.
  const target = byId('weather') || byId('weatherSightingsBlock');
  if (h === '#weather') {
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (typeof window._setActiveNav === 'function') window._setActiveNav('weather');
    return;
  }
  if (!h.startsWith('#weather/')) return;
  const id = decodeURIComponent(h.slice('#weather/'.length));
  const items = state.weather.items || [];
  const idx = items.findIndex((s) => s.id === id);
  if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (typeof window._setActiveNav === 'function') window._setActiveNav('weather');
  if (idx >= 0 && typeof openWeatherLightbox === 'function') {
    setTimeout(() => openWeatherLightbox(idx), 350);
  }
}

// Phase-3 monkey-patches at the bottom of legacy.js folded into the
// renderWeatherSightings / loadWeatherSightings function bodies above.
window.addEventListener('hashchange', _handleWeatherHashAnchor);
// Fire once after the initial loadAll() completes.
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(_handleWeatherHashAnchor, 1200);
});

// Public surface — bridges in legacy.js consume these by name.

export {
  loadWeatherSightings,
  renderWeatherSightings,
  openWeatherLightbox,
  loadWeatherRecaps,
  openWeatherRecapLightbox,
};

// ── window.* bridges ────────────────────────────────────────────────────────
// loadAll() + router.js (Telegram deep-link routing) reach for these
// by global name. The hash-anchor handler at module-import time
// already binds; these bridges are about cross-module callers.
window.loadWeatherSightings = loadWeatherSightings;
window.loadWeatherRecaps = loadWeatherRecaps;
window.openWeatherLightbox = openWeatherLightbox;
window.openWeatherRecap = openWeatherRecapLightbox;
// The Wetterdaten-chart's drag-zoom (weather/stats.js) narrows this same
// grid by timestamp on every drag/reset — a plain re-render off already-
// loaded state, not a re-fetch, so it reaches for this bridge instead of
// the heavier window.loadWeatherSightings above (which would also be
// correct, just a needless network round-trip per drag).
window.renderWeatherSightings = renderWeatherSightings;
