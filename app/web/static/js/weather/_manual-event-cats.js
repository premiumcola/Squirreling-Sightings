// ─── weather/_manual-event-cats.js ──────────────────────────────────────
// The one place that knows a manual weather event's category shape.
//
// A real event is genuinely more than one thing — the operator's own
// example is a thunderstorm that also brings heavy rain — so a record
// carries a `categories` list. Records saved before multi-select carry a
// single `category` string instead, and must keep rendering without a
// migration; records saved since carry BOTH (the list, plus `category`
// as its first entry) so a reader that only knows the old field still
// works. Every consumer normalises through here rather than branching on
// the record's age — the JS twin of weather_service/_manual_events.py's
// `manual_event_categories`.
//
// Leaf module: imports only the WEATHER_TYPES table, imported by the
// card builder (./_feed.js), the detail modal (./_manual-events.js) and
// the save form (./_manual-event-save.js). No cycles.
import { WEATHER_TYPES } from '../core/weather-types.js';

// Mirrors MANUAL_EVENT_CATEGORIES_MAX in
// app/app/weather_service/_manual_events.py — three is what the grid
// card can stack without turning into noise at 375 px.
export const MANUAL_CATEGORIES_MAX = 3;

// Normalise either record shape to a category-key array, order kept,
// duplicates dropped. Empty only when the record carries neither field.
export function manualEventCategories(m) {
  const out = [];
  const raw = m && Array.isArray(m.categories) ? m.categories : [];
  for (const c of raw) {
    if (typeof c === 'string' && c && !out.includes(c)) out.push(c);
  }
  if (!out.length && m && typeof m.category === 'string' && m.category) out.push(m.category);
  return out;
}

// Badge label/colour/icon for one category key. The fallback keeps a
// record whose category is no longer in WEATHER_TYPES renderable
// (grey, no icon, key as label) instead of throwing — same contract the
// sighting card's own fallback has always had.
export function manualCategoryMeta(key) {
  return WEATHER_TYPES[key] || { de: key || 'Ereignis', color: '#94a3b8', icon: '' };
}
