// ─── core/grid-page-size.js ─────────────────────────────────────────────
// Shared "how many tiles make one page" math for the Mediathek section's
// two row-and-responsive-column grids: mediathek/_paging.js's per-camera
// drilldown (#mediaGrid) and library/_pagination.js's merged results
// grid (#libraryGrid). Both share `.media-grid`'s CSS (MIN_CARD=192px
// cards, 10px gap) and, per the operator's explicit "so wie's eben für
// die Kameras ist" ask for the merged grid's own pagination, the same
// page-size FORMULA too (GRID_PAGE_ROWS rows of however many columns
// fit). A `core/` leaf module — only pure math plus the one shared
// DOM-fallback-width read, no state of either feature — rather than
// living inside `mediathek/` or `library/`, since neither package owns
// the other and CLAUDE.md forbids a second copy of the arithmetic.
import { byId } from './dom.js';

/** Row count both grids page by. */
export const GRID_PAGE_ROWS = 4;

const _MIN_CARD = 192;
const _GAP = 10;

/** How many `_MIN_CARD`-wide, `_GAP`-apart columns fit in `containerW`
 * px — the pure half of the sizing math, trivial to pin with plain
 * numbers in a test. */
export function calcColumnsForWidth(containerW) {
  if (!containerW || containerW <= 0) return 1;
  return Math.max(1, Math.floor((containerW + _GAP) / (_MIN_CARD + _GAP)));
}

/** Container width to assume when `containerEl` has no layout box yet
 * (e.g. a freshly-unhidden drilldown / a grid that hasn't painted a
 * first page — see mediathek/_paging.js's own `_reflowPageAfterLayout`
 * for why that race exists): the `#media` section's own width, minus
 * its padding, falling back to the viewport width on mobile. */
export function fallbackContainerWidth() {
  const isMobile = window.innerWidth <= 768;
  const mediaEl = byId('media');
  return Math.max(
    193,
    mediaEl && mediaEl.clientWidth > 192
      ? mediaEl.clientWidth - 24
      : window.innerWidth - (isMobile ? 24 : 320),
  );
}

/**
 * `rows` × however many columns fit `containerEl`'s current measured
 * width, falling back to `fallbackContainerWidth()` when it has none.
 * `lastKnownCols`, when given, wins over a fresh measurement —
 * mediathek/_paging.js's own `window._lastKnownCols` cache, corrected
 * post-render against the actual rendered card width by that module's
 * `_correctColumnCount`; `library/_pagination.js` has no such cache of
 * its own and simply omits it.
 */
export function calcGridPageSize(containerEl, { rows = GRID_PAGE_ROWS, lastKnownCols = 0 } = {}) {
  if (lastKnownCols) return rows * lastKnownCols;
  let containerW = 0;
  if (containerEl) {
    const box = containerEl.getBoundingClientRect();
    if (box.width > 0) containerW = box.width;
  }
  if (!containerW) containerW = fallbackContainerWidth();
  return rows * calcColumnsForWidth(containerW);
}
