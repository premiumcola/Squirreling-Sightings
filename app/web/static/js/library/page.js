// ─── library/page.js ─────────────────────────────────────────────────────
// Stage 6 of the Mediathek + Wetter-Ereignisse merge: the merged
// section's actual mount point. Fetches `/api/library` — `kinds`
// omitted, "Alles gemischt" is the feed's own default — accumulates
// pages behind "Mehr laden" (the cursor pager from Stage 4 has no page
// count to jump to, see `library/_pagination.js`'s own header), and
// wires the combined filter bar + card interactions on top of the
// Stage 3/4 building blocks.
import { byId } from '../core/dom.js';
import { apiGet } from '../core/api.js';
import { renderLibraryGrid } from './_grid.js';
import { createLibraryPager, renderLoadMoreControl } from './_pagination.js';
import {
  createLibraryFilterState,
  libraryQueryParams,
  renderLibraryFilterBar,
} from './_filter-bar.js';
import { bindLibraryGrid } from './_bind.js';
import { isZoomActive } from '../weather/_zoom.js';

const _PAGE_LIMIT = 30;

const _filter = createLibraryFilterState();
const _pager = createLibraryPager();
let _items = [];
let _loading = false;

function _paint() {
  const grid = byId('libraryGrid');
  if (!grid) return;
  renderLibraryGrid(grid, _items);
  bindLibraryGrid(grid, _items);
  renderLoadMoreControl(byId('libraryLoadMore'), _pager, () => _loadPage(false));
  // Stage 7: the only visible hint that this page is scoped to the
  // chart's drag-zoom rather than "Alles gemischt" — an empty result
  // already reads distinctly (see _grid.js), this covers the non-empty
  // case, where a shorter-than-usual list could otherwise read as a
  // silently broken feed instead of a deliberate narrowing.
  const note = byId('libraryZoomNote');
  if (note) note.hidden = !isZoomActive();
}

async function _loadPage(reset) {
  if (_loading) return;
  _loading = true;
  if (reset) {
    _pager.reset();
    _items = [];
  }
  try {
    const params = libraryQueryParams(_filter);
    params.set('limit', String(_PAGE_LIMIT));
    if (_pager.cursor) params.set('before', _pager.cursor);
    const page = await apiGet(`/api/library?${params.toString()}`);
    _items = _items.concat(page.items || []);
    _pager.applyPage(page);
    _paint();
  } catch (e) {
    console.error('[library] page load failed:', e);
  } finally {
    _loading = false;
  }
}

function _onFilterChange() {
  renderLibraryFilterBar(_filter, _onFilterChange);
  return _loadPage(true);
}

/** Boot entry — called from live-update.js's loadAll(), same pattern
 * as initWeatherStats()/loadWeatherSightings(). */
export function initLibraryPage() {
  if (!byId('libraryGrid')) return;
  renderLibraryFilterBar(_filter, _onFilterChange);
  return _loadPage(true);
}

/** Re-fetch page 1 with the current filter — every mutation elsewhere
 * in the merged section (delete, restore, rescan, manual-event save)
 * calls this by global name to keep the grid honest. Returns the
 * in-flight promise so callers that need the DOM settled can await it. */
export function reloadLibraryPage() {
  if (!byId('libraryGrid')) return Promise.resolve();
  return _loadPage(true);
}

window.initLibraryPage = initLibraryPage;
window.reloadLibraryPage = reloadLibraryPage;
