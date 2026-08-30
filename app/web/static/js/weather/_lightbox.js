// ─── weather/_lightbox.js ───────────────────────────────────────────────
// Opening a weather sighting or recap in the unified MediaView shell.
// Split out of sightings.js when that file crossed the JS line ceiling —
// "how does a record open a player" is its own concern, independent of
// how the grid that lists them is built or filtered.
//
// The post-delete reload reaches for `window.loadWeatherSightings` (the
// bridge sightings.js publishes at its own bottom "for cross-module
// callers") rather than an ES import of sightings.js — sightings.js
// imports `openWeatherLightbox`/`openWeatherRecapLightbox` FROM this
// module for its grid click-wiring, so an import the other way would be
// circular.
import { state } from '../core/state.js';
import { showToast, showConfirm } from '../core/toast.js';
import { apiDelete } from '../core/api.js';
import { WEATHER_TYPES } from '../core/weather-types.js';
import { sightingLabel } from './_feed.js';
import { openMediaView } from '../mediaview/index.js';
import { closeWeatherMode } from '../mediaview/weather-mode.js';

let _wsLbIdx = -1;

// Reshape a weather sighting into the MediaView shell item: the title
// bar reads camera_name + time_label; the Wetter tab reads
// api_snapshot + sun_snapshot. event_type seeds a short type word in
// the time label so the header still reads "Sonnenuntergang · 30.05.".
function _sightingItem(s) {
  const meta = WEATHER_TYPES[s.event_type] || { de: s.event_type || '' };
  const t = new Date(s.started_at);
  const when = Number.isNaN(t.getTime())
    ? ''
    : t.toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' });
  const label = sightingLabel(s, meta);
  return {
    camera_name: s.cam_name || s.cam_id || '',
    time_label: [label, when].filter(Boolean).join(' · '),
    api_snapshot: s.api_snapshot,
    sun_snapshot: s.sun_snapshot,
    event_type: s.event_type,
  };
}

// Confirm + delete a sighting from inside the player, then close the
// modal and refresh the grid so counts / filter pills stay consistent.
function _confirmDeleteSighting(s) {
  showConfirm('Wetter-Ereignis wirklich löschen?').then((ok) => {
    if (!ok) return;
    apiDelete(`/api/weather/sightings/${encodeURIComponent(s.id)}`)
      .then(() => {
        closeWeatherMode();
        window.loadWeatherSightings(state.weather.filter);
      })
      .catch((err) => showToast('Löschen fehlgeschlagen: ' + (err?.message || err), 'error'));
  });
}

// Open a weather sighting in the unified MediaView shell (blue tabs,
// Wetter panel, Fein-Analyse fold, prev/next across the filtered list,
// download + delete). idx is the absolute index into
// state.weather.itemsFiltered so prev/next walk the whole filtered set,
// not just the current page.
export function openWeatherLightbox(idx) {
  const items = state.weather.itemsFiltered || state.weather.items || [];
  if (idx < 0 || idx >= items.length) return;
  _wsLbIdx = idx;
  const s = items[idx];
  openMediaView({
    mode: 'weather',
    item: _sightingItem(s),
    source: {
      type: 'video',
      url: `/api/weather/sightings/${encodeURIComponent(s.id)}/clip`,
      loop: true,
    },
    actions: {
      onPrev: idx > 0 ? () => openWeatherLightbox(idx - 1) : null,
      onNext: idx < items.length - 1 ? () => openWeatherLightbox(idx + 1) : null,
      onDownload: () =>
        window.open(`/api/weather/sightings/${encodeURIComponent(s.id)}/clip`, '_blank'),
      onDelete: () => _confirmDeleteSighting(s),
    },
  });
}

// Open a weather recap (a multi-clip compilation) in the MediaView
// shell. Recaps carry no per-event snapshot — no Wetter tab, no
// Fein-Analyse fold, just the clip + title. No prev/next: recaps don't
// form an ordered series. Tolerant signature — the Telegram router
// calls openWeatherRecap(item, idx); a bare idx also works.
export function openWeatherRecapLightbox(itemOrIdx, idx) {
  const items = state.weather.recaps || [];
  let m;
  if (itemOrIdx && typeof itemOrIdx === 'object') {
    m = itemOrIdx;
  } else {
    const i = typeof itemOrIdx === 'number' ? itemOrIdx : idx;
    if (i == null || i < 0 || i >= items.length) return;
    m = items[i];
  }
  if (!m) return;
  openMediaView({
    mode: 'weather',
    item: {
      camera_name: m.period_label || m.id || 'Recap',
      time_label: [m.built_at || '', m.n_clips != null ? `${m.n_clips} Sichtungen` : '']
        .filter(Boolean)
        .join(' · '),
    },
    source: {
      type: 'video',
      url: `/api/weather/recaps/${encodeURIComponent(m.id)}/clip`,
      loop: true,
    },
    showWeatherTab: false,
    showFineFold: false,
    actions: {},
  });
}
