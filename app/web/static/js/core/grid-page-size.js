// ─── core/grid-page-size.js ─────────────────────────────────────────────
// Shared "how many tiles make one page" math for the Mediathek section's
// two row-and-responsive-column grids: mediathek/_paging.js's per-camera
// drilldown (#mediaGrid) and library/_pagination.js's merged results
// grid (#libraryGrid). Both share `.media-grid`'s CSS and, per the
// operator's explicit "so wie's eben für die Kameras ist" ask for the
// merged grid's own pagination, the same page-size FORMULA too
// (GRID_PAGE_ROWS rows of however many columns fit). A `core/` leaf
// module — only pure math plus a couple of DOM reads, no state of either
// feature — rather than living inside `mediathek/` or `library/`, since
// neither package owns the other and CLAUDE.md forbids a second copy of
// the arithmetic.
//
// ASK THE LAYOUT, DON'T PREDICT IT. This began as pure arithmetic over
// one hard-coded card width, and a page of four cards on a phone is what
// that cost: the CSS narrows the cards twice on the way down to a 393 px
// screen and this file knew about neither breakpoint, so it paged by one
// column while the browser drew two. `measuredColumns` reads the tracks
// the browser actually laid out; the width math is now only the stand-in
// for a grid that has not painted yet, and it at least knows the same
// breakpoints the stylesheets do (`gridMetrics`).
import { byId } from './dom.js';

/** Row count both grids page by. */
export const GRID_PAGE_ROWS = 4;

/** The desktop `.media-grid` recipe — `minmax(192px, 1fr)`, 10 px gap. */
const _DESKTOP = { card: 192, gap: 10 };

/**
 * The card/gap pair `.media-grid` ACTUALLY uses at `viewportW`.
 *
 * This module hard-coded the desktop pair at every width, and the phone
 * is where that hurt: 03-dashboard.css drops to `minmax(160px, 1fr)`
 * below 768 px and 25-mobile.css to `minmax(140px, 1fr)` below 400 px,
 * so on a 393 px screen the CSS laid out TWO columns while this math
 * insisted on one. Four rows of one column is eight cards short of four
 * rows of two — „jetzt grade sind hier nur zwei Zeilen, das ist zu
 * wenig". Kept beside `measuredColumns` below, which is the answer
 * whenever the grid has actually painted; this is what stands in before
 * it has.
 */
export function gridMetrics(viewportW) {
  const w = Number(viewportW) || 0;
  if (w > 0 && w <= 400) return { card: 140, gap: 8 };
  if (w > 0 && w <= 768) return { card: 160, gap: 8 };
  return _DESKTOP;
}

/** How many `metrics.card`-wide, `metrics.gap`-apart columns fit in
 * `containerW` px — the pure half of the sizing math, trivial to pin
 * with plain numbers in a test. */
export function calcColumnsForWidth(containerW, metrics = _DESKTOP) {
  if (!containerW || containerW <= 0) return 1;
  return Math.max(1, Math.floor((containerW + metrics.gap) / (metrics.card + metrics.gap)));
}

/**
 * The column count the browser HAS LAID OUT, straight off the grid.
 *
 * `grid-template-columns` resolves to one length per rendered track
 * ("181.5px 181.5px"), which is the number this module spent its life
 * trying to predict from a width and a breakpoint table. When the
 * element has painted, ask instead of guessing — no copy of the CSS can
 * then drift away from the CSS. `0` when there is nothing to read: no
 * element, no `getComputedStyle` (the node tests), or a grid that is
 * still `display: none` and resolves to `none`.
 */
export function measuredColumns(containerEl) {
  if (!containerEl) return 0;
  const tpl = globalThis.getComputedStyle?.(containerEl)?.gridTemplateColumns || '';
  if (!tpl || tpl === 'none') return 0;
  return tpl.trim().split(/\s+/).filter(Boolean).length;
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
  // What the browser laid out beats anything derived from a width.
  const measured = measuredColumns(containerEl);
  if (measured) return rows * measured;
  let containerW = 0;
  if (containerEl) {
    const box = containerEl.getBoundingClientRect();
    if (box.width > 0) containerW = box.width;
  }
  if (!containerW) containerW = fallbackContainerWidth();
  return rows * calcColumnsForWidth(containerW, gridMetrics(globalThis.window?.innerWidth));
}
