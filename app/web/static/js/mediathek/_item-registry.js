// ─── mediathek/_item-registry.js ───────────────────────────────────────────
// Shared lookup for `window._openMediaItem(event_id)` — the inline
// onclick every motion/timelapse card (`mediaCardHTML`, `_cards.js`)
// carries. Before the library merge only one grid ever painted at a
// time (`_paging.js::renderMediaGrid`, the per-camera drilldown), so a
// closure over `state.media` was enough. The merged grid
// (`library/page.js`) now paints motion cards from a different item
// pool at the same time the drilldown may also be open — two writers
// of the same global, each only knowing its own slice. This registry
// is the one place both merge into, so whichever rendered last still
// resolves the other's cards.
const _items = new Map();

/** Merge `items` (full event objects, keyed by `event_id`) into the registry. */
export function registerMediaItems(items) {
  for (const item of items || []) {
    if (item && item.event_id) _items.set(item.event_id, item);
  }
}

export function getRegisteredMediaItem(eventId) {
  return _items.get(eventId) || null;
}
