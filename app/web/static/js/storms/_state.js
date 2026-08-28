// ─── storms/_state.js ──────────────────────────────────────────────────────
// Module state + the two vocabularies the Gewitter-Browser owns:
// the five user classes and the four compare-slot colours.
//
// Every colour here already exists elsewhere in the app — imported, not
// re-declared, so a palette change lands in one place.

import { WEATHER_TYPES } from '../core/weather-types.js';
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

// Compare slot colours, in this exact order. All four are already in the
// app's _LIVE_PALETTE vocabulary (core/track-color.js), so no new hue
// enters the design system. Checked against WEATHER_STATS_PALETTE and
// the class colours: no collision — and by the one-colour-one-meaning
// rule they never co-occur anyway.
export const STORM_SLOT_COLORS = ['#38bdf8', '#f6b73c', '#e879f9', '#2dd4bf'];
export const STORM_MAX_COMPARE = 4;

// The five storm-relevant history fields. cloud_cover and sun_altitude
// are excluded on purpose: diagnostics, never a storm signal.
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
  episodes: [], // full list, newest first — never paginated (see §9.3)
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
