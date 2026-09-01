// ─── library/index.js ────────────────────────────────────────────────────
// Stage 4 of the Mediathek + Wetter-Ereignisse merge: the unified card
// renderer for `/api/library` (Stage 3's read model, `app/app/library/`).
// Dispatches each item to whichever existing card builder already owns
// its kind — no new card HTML for motion/sighting/recap/manual/episode,
// which all reuse `mediathek/_cards.js` / `weather/_feed.js` unchanged.
// Only `timelapse` gets a fresh, small builder (`_timelapse-card.js`) —
// see that module for why.
//
// Stage 6 mounts these building blocks into the real page — see
// `page.js` (the merged section's fetch/render/paginate orchestrator),
// `_filter-bar.js` (camera + object-class + weather-category chips) and
// `_bind.js` (click/delete/pin wiring). This file's own exports are
// unchanged by that — still the pure rendering primitives, still usable
// on their own.
//
//   libraryCardHTML(item, ctx?)                 — one item -> card HTML
//   renderLibraryGrid(host, items, ctx?)         — one page -> a mixed
//                                                  grid, in server
//                                                  order, no grouping by
//                                                  kind
//   createLibraryCursorStack()                   — Stage 11's client-held
//                                                  prev/next cursor
//                                                  history behind the
//                                                  page-numbered widget
//                                                  (`/api/library`'s own
//                                                  pagination is still
//                                                  cursor-based — see
//                                                  `_cursor-stack.js`)
//   renderLibraryPagination(host, stack, total,
//     pageSize, onGoTo)                          — the "Seite N von M"
//                                                  widget for that stack
export { libraryCardHTML } from './_dispatch.js';
export { renderLibraryGrid } from './_grid.js';
export { createLibraryCursorStack, renderLibraryPagination } from './_pagination.js';
