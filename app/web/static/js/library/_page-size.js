// ─── library/_page-size.js ──────────────────────────────────────────────
// The merged grid's own page size — "so wie's eben für die Kameras
// ist": the SAME `GRID_PAGE_ROWS` rows × responsive-columns formula
// `mediathek/_paging.js::calcItemsPerPage` uses for the per-camera
// drilldown, via the shared `core/grid-page-size.js` helper (see that
// module's header for why it lives there and not in either feature
// package). No `window._lastKnownCols`-style cache here — the
// drilldown's own cache exists to survive a ResizeObserver correction
// pass (`mediathek/grid.js`) that #libraryGrid doesn't have; a fresh
// measurement on every call is simpler and cheap enough for a widget
// that only recomputes on page navigation and filter changes, not on
// every frame.
import { byId } from '../core/dom.js';
import { GRID_PAGE_ROWS, calcGridPageSize } from '../core/grid-page-size.js';

export function calcLibraryPageSize() {
  return calcGridPageSize(byId('libraryGrid'), { rows: GRID_PAGE_ROWS });
}
