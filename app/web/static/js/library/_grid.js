// ─── library/_grid.js ─────────────────────────────────────────────────
// Stage 4 of the Mediathek + Wetter-Ereignisse merge: paints one
// `/api/library` page's `items` array as a single mixed grid — the
// "Alles gemischt" default the user asked for. Renders in the order it
// is given and nothing else: `/api/library` already arrives newest-first
// (see `library._feed`'s module docstring), so there is no client-side
// sort here — unlike weather/sightings.js's old grid painter, which had
// to merge four un-sorted arrays itself because it predated this route
// (retired in Stage 6, once this grid took over rendering every kind).
// This grid never groups by kind either — a motion clip, a storm
// episode and a sighting sit side by side in whatever order the server
// sorted them.
import { libraryCardHTML } from './_dispatch.js';
import { isZoomActive } from '../weather/_zoom.js';

const _EMPTY_HTML = '<div class="item muted" style="padding:16px">Keine Einträge vorhanden.</div>';
// Stage 7: an empty PAGE reads very differently depending on why it's
// empty — "nothing configured yet" (the message above) versus "nothing
// in the range you just dragged" (below). Silently sharing one message
// would make a real zoom-window result look like a broken/empty
// archive. Read directly off weather/_zoom.js (a leaf module, no cycle
// risk) rather than threading a flag through `ctx` from every caller.
const _EMPTY_ZOOM_HTML =
  '<div class="item muted" style="padding:16px">Keine Einträge im gewählten Zeitraum.</div>';

/**
 * Paint `items` (one `/api/library` page, or any already-ordered list of
 * library items) into `host`. `ctx` is forwarded to every card, plus a
 * per-item `idx` (the item's position within THIS page) and `pageItems`
 * (the full array) — see `index.js::libraryCardHTML` for why a card
 * needs either at all.
 */
export function renderLibraryGrid(host, items, ctx = {}) {
  if (!host) return;
  const pageItems = Array.isArray(items) ? items : [];
  host.innerHTML = pageItems.length
    ? pageItems.map((item, idx) => libraryCardHTML(item, { ...ctx, idx, pageItems })).join('')
    : isZoomActive()
      ? _EMPTY_ZOOM_HTML
      : _EMPTY_HTML;
}
