// ─── storms/_state.js ──────────────────────────────────────────────────────
// Module state + the two vocabularies the Gewitter-Browser owns:
// the five user classes and the four compare-slot colours.
//
// Every colour here already exists elsewhere in the app — imported, not
// re-declared, so a palette change lands in one place.

import { WEATHER_TYPES } from '../core/weather-types.js';
import { LIVE_PALETTE } from '../core/track-color.js';
import { WEATHER_STATS_PALETTE } from '../weather/stats.js';

// New glyphs — the sprite and WEATHER_TYPES between them cover Gewitter
// and Starkregen; Sturm / Hagel / harmlos need their own.
const ICON_WIND =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8h10a3 3 0 1 0-3-3"/><path d="M3 13h14a3 3 0 1 1-3 3"/><path d="M3 18h7"/></svg>';
const ICON_HAIL =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 13a5 5 0 0 0 0-10 7 7 0 0 0-13.5 2.5"/><circle cx="7" cy="18" r="1.4"/><circle cx="12" cy="20" r="1.4"/><circle cx="16" cy="17" r="1.4"/></svg>';
const ICON_OK =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="4,12.5 9.5,18 20,6"/></svg>';

// The five classes an operator can assign, in fixed display order.
// `storm` borrows the wind-gust palette entry — the metric that DEFINES
// a Sturm; `hail` borrows the snow colour as the frozen-precipitation
// sibling; `harmless` the neutral fog grey.
export const STORM_CLASSES = {
  thunder: { de: 'Gewitter', color: WEATHER_TYPES.thunder.color, icon: WEATHER_TYPES.thunder.icon },
  heavy_rain: {
    de: 'Starkregen',
    color: WEATHER_TYPES.heavy_rain.color,
    icon: WEATHER_TYPES.heavy_rain.icon,
  },
  storm: { de: 'Sturm', color: WEATHER_STATS_PALETTE.wind_gusts_10m, icon: ICON_WIND },
  hail: { de: 'Hagel', color: WEATHER_TYPES.snow.color, icon: ICON_HAIL },
  harmless: { de: 'harmlos', color: WEATHER_TYPES.fog.color, icon: ICON_OK },
};

export const STORM_CLASS_ORDER = Object.keys(STORM_CLASSES);

// ── Storm CHARACTER — composition + sequence of the curve itself ───────
// Distinct from STORM_CLASSES above: a class answers "which alarm
// fired" (backend: _segment.dominant_event); a character answers "what
// did the whole curve look like" (backend: weather_episodes/_character.py,
// whose module docstring carries the full rule table this map mirrors).
// Both are stamped on every episode record and both render — neither
// replaces the other.
//
// The two sequence icons encode ORDER, not just composition: the axis
// that peaks FIRST sits on the left of the arrow. Everything else reuses
// an existing glyph — the shape it draws already means the same thing
// elsewhere in this app, so a second, differently-drawn "Regen" icon
// here would only cost recognisability.
const ICON_RAIN_TO_BOLT =
  '<svg viewBox="0 0 32 24" width="20" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6.5 4c-2.1 3-3.3 5.1-3.3 7.1a3.3 3.3 0 0 0 6.6 0C9.8 9.1 8.6 7 6.5 4z"/><path d="M13 12h5"/><path d="M16 9l3 3-3 3"/><path d="M25 3l-3.5 7h3L23 18"/></svg>';
const ICON_BOLT_TO_RAIN =
  '<svg viewBox="0 0 32 24" width="20" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3l-3.5 7h3L7 18"/><path d="M14 12h5"/><path d="M17 9l3 3-3 3"/><path d="M25.5 4c-2.1 3-3.3 5.1-3.3 7.1a3.3 3.3 0 0 0 6.6 0c0-2-1.2-4.1-3.3-7.1z"/></svg>';
const ICON_MIXED =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" stroke="none" aria-hidden="true"><circle cx="12" cy="5" r="2.2"/><circle cx="19" cy="12" r="2.2"/><circle cx="12" cy="19" r="2.2"/><circle cx="5" cy="12" r="2.2"/></svg>';

// Keys are a bit-for-bit mirror of the backend's CHARACTERS tuple
// (weather_episodes/_consts.py) — a slug missing here falls back to
// the "unbekannt" default in storms/_helpers.js::characterMeta.
export const STORM_CHARACTERS = {
  rain_led_thunder: { de: 'Vorlauf-Regen', icon: ICON_RAIN_TO_BOLT },
  lightning_led_rain: { de: 'Blitzfront', icon: ICON_BOLT_TO_RAIN },
  lightning_only: { de: 'Blitzsturm', icon: WEATHER_TYPES.thunder.icon },
  rain_only: { de: 'Landregen', icon: WEATHER_TYPES.heavy_rain.icon },
  wind_only: { de: 'Sturmböen', icon: ICON_WIND },
  snow_only: { de: 'Schneefall', icon: WEATHER_TYPES.snow.icon },
  fog_only: { de: 'Nebelereignis', icon: WEATHER_TYPES.fog.icon },
  mixed: { de: 'Mischform', icon: ICON_MIXED },
};

export const STORM_MAX_COMPARE = 4;

// Compare slot colours — the first four of the app's "N distinguishable
// series" palette (core/track-color.js · LIVE_PALETTE), taken by
// reference rather than copied so a palette change lands in one place.
// By the one-colour-one-meaning rule they never co-occur with the live
// track colours anyway: colour means "which episode" inside this view
// and nothing else.
export const STORM_SLOT_COLORS = LIVE_PALETTE.slice(0, STORM_MAX_COMPARE);

// The five storm-relevant history fields — the mirror of PEAK_FIELDS in
// app/app/weather_episodes/_consts.py. A field listed here but absent
// there renders a pill that can never light up. cloud_cover and
// sun_altitude are excluded on purpose: diagnostics, never a storm
// signal.
// Which DIRECTION counts as worse for each of them is deliberately NOT
// stated here — weather/metric-direction.js owns that single fact and
// every consumer (chart dot, table bold, severity ratio) asks it.
export const STORM_METRICS = [
  'lightning_potential',
  'precipitation',
  'wind_gusts_10m',
  'snowfall',
  'visibility',
];

// Short pill labels. The full names (WEATHER_FIELD_LABEL_DE) go into
// title / aria-label, where space is not the constraint.
export const STORM_METRIC_SHORT = {
  lightning_potential: 'Blitz',
  precipitation: 'Regen',
  wind_gusts_10m: 'Böen',
  snowfall: 'Schnee',
  visibility: 'Sicht',
};

export const stormsState = {
  view: 'list', // 'list' | 'detail' | 'compare'
  // Full list, newest first. Never paginated: the year's Top-3 ranking
  // is computed client-side and a partial page makes it wrong.
  episodes: [],
  loaded: false,
  unavailable: false, // endpoint missing / unreachable → empty archive, not an error page
  year: null, // selected year, null = newest present
  sort: 'recent', // 'recent' | 'strongest'
  filter: new Set(), // effective classes; empty = alle Filter aus
  selecting: false, // Auswahl-Modus
  // Compare slots. Assignment is BY SLOT, not by pick order: freeing
  // slot 2 leaves slot 2 empty and the next pick takes the lowest free
  // one, so an episode keeps its colour for the whole session even as
  // others come and go. A curve never changes colour under the
  // operator's hands.
  slots: [null, null, null, null],
  detail: null, // full episode record (with samples) for the detail view
  detailId: null,
  metric: null, // compare metric key, null = auto-pick
  samples: {}, // id → full record cache, so compare fetches each id once
  footage: {}, // id → footage payload
};

export function slotOf(id) {
  const i = stormsState.slots.indexOf(id);
  return i < 0 ? 0 : i + 1;
}

export function selectedIds() {
  return stormsState.slots.filter(Boolean);
}

export function selectedCount() {
  return selectedIds().length;
}

/** Put an episode into the lowest free slot. Returns false when full. */
export function slotAssign(id) {
  if (stormsState.slots.includes(id)) return true;
  const free = stormsState.slots.indexOf(null);
  if (free < 0) return false;
  stormsState.slots[free] = id;
  return true;
}

/** Free an episode's slot, leaving the slot itself empty. */
export function slotRelease(id) {
  const i = stormsState.slots.indexOf(id);
  if (i >= 0) stormsState.slots[i] = null;
}

export function slotsClear() {
  stormsState.slots = [null, null, null, null];
}

export function slotColor(slot) {
  return STORM_SLOT_COLORS[(slot - 1) % STORM_SLOT_COLORS.length];
}
