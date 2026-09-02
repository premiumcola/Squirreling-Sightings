// ─── library/page.js ─────────────────────────────────────────────────────
// Stage 6 of the Mediathek + Wetter-Ereignisse merge: the merged
// section's actual mount point. Fetches `/api/library` — `kinds`
// omitted, "Alles gemischt" is the feed's own default — pages through it
// page-numbered, "genau wie bei den Kameras" (Stage 11, see
// `library/_pagination.js`'s own header), and wires the combined filter
// bar + card interactions on top of the Stage 3/4 building blocks.
import { byId } from '../core/dom.js';
import { apiGet } from '../core/api.js';
import { state } from '../core/state.js';
import { renderLibraryGrid } from './_grid.js';
import {
  createLibraryCursorStack,
  libraryPageItems,
  renderLibraryPagination,
} from './_pagination.js';
import { showToast } from '../core/toast.js';
import { calcLibraryPageSize } from './_page-size.js';
import {
  createLibraryFilterState,
  libraryQueryParams,
  renderLibraryFilterBar,
  getLibraryFacetsTotal,
} from './_filter-bar.js';
import { bindLibraryGrid } from './_bind.js';
import { isZoomActive } from '../weather/_zoom.js';
import { showMediathekView } from '../mediathek/_view-toggle.js';

const _filter = createLibraryFilterState();
const _cursorStack = createLibraryCursorStack();
let _items = [];
let _loading = false;
// `kinds` on purpose lives OUTSIDE `_filter`/`libraryQueryParams` — that
// function's own contract ("no kinds ever set here") is what keeps
// "Alles gemischt" the feed's default for every caller that never
// touches this. Only `setLibraryKindFilter` (below) ever sets it; `null`
// means "every kind", the same default the backend already applies when
// the param is simply absent (routes/library.py::api_library_list).
let _kinds = null;

// Split out of _paint() so a facets fetch that resolves AFTER the grid
// has already painted (renderLibraryFilterBar's own fetch — see
// _onFilterChange below — races independently against _loadPage's
// /api/library fetch, and routinely loses since /api/library/facets
// does the more expensive full-exhaustion widen, _facets.py's own
// docstring) can still correct the "Seite N von M" label once the real
// total is known, instead of leaving it stuck on the previous filter's
// number. getLibraryFacetsTotal() itself is race-safe (_filter-facets.
// js's createFacetsCache only ever commits the latest call), so calling
// this again from a late-resolving fetch always repaints a CURRENT
// value, never a stale one — see _filter-bar.js's own header.
function _repaintPagination() {
  renderLibraryPagination(
    byId('libraryPagination'),
    _cursorStack,
    getLibraryFacetsTotal(),
    calcLibraryPageSize(),
    _goToLibraryPage,
  );
}

function _paint() {
  const grid = byId('libraryGrid');
  if (!grid) return;
  renderLibraryGrid(grid, _items);
  bindLibraryGrid(grid, _items);
  _repaintPagination();
  // Stage 7: the only visible hint that this page is scoped to the
  // chart's drag-zoom rather than "Alles gemischt" — an empty result
  // already reads distinctly (see _grid.js), this covers the non-empty
  // case, where a shorter-than-usual list could otherwise read as a
  // silently broken feed instead of a deliberate narrowing.
  const note = byId('libraryZoomNote');
  if (note) note.hidden = !isZoomActive();
}

/** One `/api/library` fetch, replacing `_items` outright — never
 * concatenating, unlike the old "Mehr laden" accumulate model. `cursor`
 * defaults to the cursor stack's own `current` (re-fetching the same
 * page, e.g. after a filter change once `reset` has just cleared it back
 * to page 1); the page-widget's ‹/› pass an explicit one instead, since
 * by the time this runs the stack has already advanced/gone back past
 * it (see `_goToLibraryPage`). */
async function _loadPage(reset, cursor) {
  if (_loading) return;
  _loading = true;
  if (reset) _cursorStack.reset();
  const before = cursor !== undefined ? cursor : _cursorStack.current;
  try {
    const params = libraryQueryParams(_filter);
    if (_kinds) params.set('kinds', _kinds.join(','));
    params.set('limit', String(calcLibraryPageSize()));
    if (before) params.set('before', before);
    const page = await apiGet(`/api/library?${params.toString()}`);
    _items = libraryPageItems(page);
    _cursorStack.applyPage(page);
    _paint();
  } catch (e) {
    // A failed page load used to be console-only: the grid kept its
    // stale items, the cursor stack kept a stale `nextCursor`, and ‹/›
    // stayed enabled — a control that looks alive and does nothing. Say
    // so on screen.
    console.error('[library] page load failed:', e);
    showToast('Mediathek konnte nicht geladen werden.', 'error');
  } finally {
    _loading = false;
  }
}

/** ‹/› handler for `renderLibraryPagination` — `_cursorStack.back()`/
 * `.advance()` already do the push/pop and hand back the cursor to
 * re-fetch with (`undefined` when there is nowhere to go, in which case
 * this is a no-op rather than a redundant re-fetch of the same page). */
function _goToLibraryPage(direction) {
  const cursor = direction === 'back' ? _cursorStack.back() : _cursorStack.advance();
  if (cursor === undefined) return;
  return _loadPage(false, cursor);
}

// True while a quick tile (Tiere/Menschen/Wetterereignisse) or any
// #libraryFilterBar chip is active — the one condition that decides
// whether #libraryBlock (the toggle's third state, mediathek/
// _view-toggle.js) or the #mediaOverview tiles are showing.
function _hasActiveLibraryFilter() {
  return !!(_filter.cameraIds.size || _filter.labels.size || _filter.categories.size || _kinds);
}

// Flips the shared overview/drilldown/results toggle to match the
// current filter state. A camera tile still opens the per-camera
// drilldown as its own thing (mediathek/_drilldown.js) — but
// #libraryFilterBar stays reachable while that drilldown is open, so a
// chip click there has to be able to override it: reuse the exact same
// "leave the drilldown" bridge its own "← Alle Kameras" button calls
// (window.closeMediaDrilldown, set by mediathek/orchestration.js) rather
// than re-deriving that cleanup here, then let showMediathekView promote
// the results grid over the overview it just landed on.
function _syncMediathekView() {
  if (_hasActiveLibraryFilter()) {
    if (state.mediaDrillOpen) window.closeMediaDrilldown?.();
    showMediathekView('libraryBlock');
  } else {
    showMediathekView('mediaOverview');
  }
}

function _onFilterChange() {
  // Not awaited — repainting the count badges is not on the critical
  // path for the grid's own reload (renderLibraryFilterBar's own
  // header) — but its facets fetch is also the ONLY source for the
  // pagination widget's "von M" total (getLibraryFacetsTotal), so once
  // it resolves (often after _loadPage's own /api/library fetch has
  // already painted a stale total below), repaint just the pagination
  // widget to pick up the fresh number.
  renderLibraryFilterBar(_filter, _kinds, _onFilterChange).then(_repaintPagination);
  _syncMediathekView();
  return _loadPage(true);
}

/** Boot entry — called from live-update.js's loadAll(), same pattern
 * as initWeatherStats()/loadWeatherSightings(). */
export function initLibraryPage() {
  if (!byId('libraryGrid')) return;
  renderLibraryFilterBar(_filter, _kinds, _onFilterChange).then(_repaintPagination);
  _syncMediathekView();
  return _loadPage(true);
}

/** The results grid's "← Übersicht" affordance — clears every filter
 * dimension (chips AND whatever quick tile set `_kinds`/`labels`) and
 * hands control back to `_syncMediathekView`, which then shows the tile
 * overview again since nothing is active any more. */
export function resetLibraryView() {
  _filter.cameraIds.clear();
  _filter.labels.clear();
  _filter.categories.clear();
  _kinds = null;
  return _onFilterChange();
}

/** Re-fetch page 1 with the current filter — every mutation elsewhere
 * in the merged section (delete, restore, rescan, manual-event save)
 * calls this by global name to keep the grid honest. Returns the
 * in-flight promise so callers that need the DOM settled can await it. */
export function reloadLibraryPage() {
  if (!byId('libraryGrid')) return Promise.resolve();
  return _loadPage(true);
}

/** Jump straight into the merged feed filtered to exactly `labels` — the
 * camera-overview's "Tiere" / "Menschen" quick tiles (mediathek/
 * _overview.js) call this by global name rather than importing this
 * module directly, the same window-bridge pattern reloadLibraryPage's
 * own callers already use. Replaces whatever filter was active (a
 * predictable, single-purpose jump, not a merge with leftover camera/
 * category chips from a previous visit) and scrolls the now-filtered
 * grid into view, since it renders below the camera overview these
 * tiles live in. */
export function setLibraryLabelFilter(labels) {
  _filter.cameraIds.clear();
  _filter.categories.clear();
  _filter.labels = new Set(labels || []);
  _kinds = null;
  const done = _onFilterChange();
  byId('libraryBlock')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return done;
}

/** Jump straight into the merged feed filtered to exactly `kinds` — the
 * camera-overview's "Wetterereignisse" quick tile (mediathek/
 * _overview.js) calls this by global name, the sibling of
 * setLibraryLabelFilter above for the one quick tile that answers a
 * KIND question ("every weather record") rather than an object-label
 * one. This is the first-ever frontend caller of `/api/library`'s
 * `kinds` param — every other surface (including this page's own
 * default boot) deliberately never sets it, so "Alles gemischt" stays
 * the default for everyone who never taps this tile. Same
 * replace-not-merge contract as setLibraryLabelFilter: clears every
 * other filter dimension rather than layering onto whatever was
 * active. */
export function setLibraryKindFilter(kinds) {
  _filter.cameraIds.clear();
  _filter.categories.clear();
  _filter.labels.clear();
  _kinds = Array.isArray(kinds) && kinds.length ? [...kinds] : null;
  const done = _onFilterChange();
  byId('libraryBlock')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return done;
}

window.initLibraryPage = initLibraryPage;
window.reloadLibraryPage = reloadLibraryPage;
window.setLibraryLabelFilter = setLibraryLabelFilter;
window.setLibraryKindFilter = setLibraryKindFilter;
window.resetLibraryView = resetLibraryView;
