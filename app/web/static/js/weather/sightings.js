// ─── weather/sightings.js ──────────────────────────────────────────────────
// Data layer for Wetter-Ereignisse: fetches sightings/recaps/episodes/
// manual-events into state.weather.*, opens the lightbox, deletes a
// sighting, and handles the #weather/<id> hash-anchor deep link.
//
// Stage 6 of the Mediathek + Wetter-Ereignisse merge dropped this
// file's own grid painter (`_renderWeatherGrid`, its filter pills and
// its click/delete wiring) — the merged grid (`library/page.js`,
// `/api/library`) is now the one place sightings/recaps/episodes/
// manual events render as cards. What stays here is everything that
// grid still needs from this module: the fetches that keep
// state.weather.* current, and the lightbox/delete plumbing
// router.js's Telegram deep links and library/_bind.js both call by
// name.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { apiGet, apiDelete } from '../core/api.js';
import { showToast } from '../core/toast.js';
import { WEATHER_TYPES } from '../core/weather-types.js';
import { fetchEpisodes } from '../storms/_api.js';
import { openWeatherLightbox, openWeatherRecapLightbox } from './_lightbox.js';
import { loadWeatherManualEvents } from './_manual-events.js';

// Matches MAX_SIGHTINGS_PAGE_SIZE in routes/weather.py. state.weather.items
// still backs the lightbox's prev/next navigation and the Telegram
// deep-link lookup, both of which need the whole list, not a page of it.
const _FETCH_PAGE_SIZE = 500;

async function loadWeatherSightings(filter) {
  // Filter is a Set of event_type strings; state.weather.filter still
  // reaches the lightbox delete's reload call below. Empty Set = "no
  // filter" (kept for that one caller's benefit — the merged grid's own
  // category filter is a separate, server-side `/api/library?categories=`
  // concern, see library/_filter-bar.js).
  try {
    const data = await apiGet(`/api/weather/sightings?page_size=${_FETCH_PAGE_SIZE}`);
    state.weather.items = data.items || [];
    state.weather.counts = data.counts || {};
    state.weather.total = data.total || 0;
    if (filter instanceof Set) {
      state.weather.filter = filter;
    } else if (typeof filter === 'string' && filter) {
      state.weather.filter = new Set([filter]);
    } else if (!(state.weather.filter instanceof Set)) {
      const present = Object.keys(WEATHER_TYPES).filter((t) => (state.weather.counts[t] || 0) > 0);
      state.weather.filter = new Set(present);
    }
  } catch (_err) {
    // silently degrade — state keeps its previous values
  }
  // Recaps, Gewitter-episodes and manual events are event records like
  // any other and render inline in the merged grid — loading them here
  // keeps every source synced without a separate boot hook.
  await loadWeatherRecaps();
  await loadStormEpisodes();
  await loadWeatherManualEvents();
}

// Delete a sighting straight from its card (Mediathek-style hover trash —
// no confirm modal; the heavier confirm lives in the lightbox). Fades the
// card, hits the same DELETE endpoint the lightbox uses, then re-fetches so
// the merged grid and the lightbox's own list both reflect the removal.
export function deleteSighting(id, cardEl) {
  if (!id) return;
  if (cardEl) {
    cardEl.style.transition = 'opacity .2s, transform .2s';
    cardEl.style.opacity = '0';
    cardEl.style.transform = 'scale(0.96)';
  }
  apiDelete(`/api/weather/sightings/${encodeURIComponent(id)}`)
    .then(() => {
      loadWeatherSightings(state.weather.filter);
      window.reloadLibraryPage?.();
    })
    .catch((err) => {
      showToast('Löschen fehlgeschlagen: ' + (err?.message || err), 'error');
      if (cardEl) {
        cardEl.style.opacity = '';
        cardEl.style.transform = '';
      }
    });
}

async function loadWeatherRecaps() {
  try {
    const d = await apiGet('/api/weather/recaps');
    state.weather.recaps = d.items || [];
  } catch (_err) {
    /* silent */
  }
}

// fetchEpisodes() never throws (see storms/_api.js) — a missing or
// unreachable endpoint resolves to an empty list, same as day one.
async function loadStormEpisodes() {
  const { items } = await fetchEpisodes();
  state.weather.episodes = items;
}

// ── Hash anchor handler — open lightbox for #weather/<id> on page load ──────

function _handleWeatherHashAnchor() {
  const h = window.location.hash || '';
  // Wetter-Ereignisse merged into #media (Stage 6) — #weather is no
  // longer a section id, but old Telegram links / bookmarks may still
  // carry it, so both forms keep resolving to the merged section.
  const target = byId('media');
  if (h === '#weather' || h === '#media') {
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (typeof window._setActiveNav === 'function') window._setActiveNav('media');
    return;
  }
  if (!h.startsWith('#weather/')) return;
  const id = decodeURIComponent(h.slice('#weather/'.length));
  const items = state.weather.items || [];
  const idx = items.findIndex((s) => s.id === id);
  if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (typeof window._setActiveNav === 'function') window._setActiveNav('media');
  if (idx >= 0 && typeof openWeatherLightbox === 'function') {
    setTimeout(() => openWeatherLightbox(idx), 350);
  }
}

window.addEventListener('hashchange', _handleWeatherHashAnchor);
// Fire once after the initial loadAll() completes.
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(_handleWeatherHashAnchor, 1200);
});

// Public surface — bridges in legacy.js consume these by name.

export { loadWeatherSightings, openWeatherLightbox, loadWeatherRecaps, openWeatherRecapLightbox };

// ── window.* bridges ────────────────────────────────────────────────────────
// loadAll() + router.js (Telegram deep-link routing) reach for these
// by global name.
window.loadWeatherSightings = loadWeatherSightings;
window.loadWeatherRecaps = loadWeatherRecaps;
window.openWeatherLightbox = openWeatherLightbox;
window.openWeatherRecap = openWeatherRecapLightbox;
