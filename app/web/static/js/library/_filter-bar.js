// ─── library/_filter-bar.js ─────────────────────────────────────────────
// Stage 6 of the Mediathek + Wetter-Ereignisse merge: the one filter bar
// for the merged grid — camera chips, an object-class chip row (motion
// items only) and a weather-category chip row (sighting/manual/episode
// items only). Each toggle maps straight onto one `/api/library` query
// param; see `_filter-state.js::libraryQueryParams` for the exact
// mapping (split out there — pure, no DOM, no mediathek/filters.js
// import — so it stays importable without pulling in the whole
// Mediathek module graph this file's `MEDIA_FILTER_LABELS` import does).
//
// Stage 10: every chip now carries a live count from `GET
// /api/library/facets` (`_filter-facets.js`'s `fetchLibraryFacets`), and
// a chip whose count is 0 — and isn't the caller's own active selection
// — is omitted from the DOM entirely rather than greyed out, per the
// operator's explicit ask ("sollten dann gar nicht angezeigt werden").
// The actual chip HTML + the "is this chip visible at all" rule live in
// `_filter-chips.js` (pure, leaf-testable); the fetch-with-keep-previous
// state machine lives in `_filter-facets.js` (also pure/testable) — this
// file is purely the DOM orchestration gluing the two together, same
// split `_filter-state.js` already drew and the same reason
// (`_filter-bar.js` itself pulls in `mediathek/filters.js`'s whole
// graph via `MEDIA_FILTER_LABELS` below, which makes IT untestable
// under this repo's plain-node harness — see library/_tests/
// filter-facets.test.js + filter-chips.test.js's own headers for where
// the actually-tested logic lives instead).
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { MEDIA_FILTER_LABELS } from '../mediathek/filters.js';
import { cameraChipsHTML, labelChipsHTML, categoryChipsHTML } from './_filter-chips.js';
import { fetchLibraryFacets, createFacetsCache } from './_filter-facets.js';

export { createLibraryFilterState, libraryQueryParams } from './_filter-state.js';

// 'timelapse' is a `kind`, not an object label `/api/library`'s
// `label`/`labels` params can filter on (they only ever reach
// `motion_candidates`, see `library._feed._windowed_candidates`) — drop
// it from the reused Mediathek vocabulary rather than sending a filter
// value the backend would silently never match.
const _OBJECT_LABELS = MEDIA_FILTER_LABELS.filter((l) => l !== 'timelapse');

// One cache per page load — the merged grid only ever has one filter
// bar on screen, so module-level state (rather than a param threaded
// through every caller) matches `library/page.js`'s own `_filter`/
// `_pager` module-state convention.
const _facetsCache = createFacetsCache();

// Quick tiles (mediathek/_overview.js's "Tiere"/"Menschen") pre-seed
// `filter.labels` to a superset and rely on tap-to-deselect — the same
// "seed-all" pattern `mediathek/filters.js::_seedTopMediaLabel`
// documents for the legacy drilldown. Unlike that legacy pill bar's own
// `_pruneEmptyMediaFilters`, a seeded-but-currently-zero label here is
// deliberately NOT auto-deselected: `chipVisible` already keeps an
// active chip on screen regardless of its count, so the seeded set
// stays exactly what the tile promised ("every animal is selected,
// untap what you don't want") instead of chips quietly disappearing
// out from under the operator mid-glance.
function _wireChips(bar, filter, onChange) {
  bar.querySelectorAll('.media-pill').forEach((p) => {
    p.addEventListener('click', () => {
      const group = p.dataset.group;
      const val = p.dataset.val;
      const set =
        group === 'camera'
          ? filter.cameraIds
          : group === 'label'
            ? filter.labels
            : filter.categories;
      if (set.has(val)) set.delete(val);
      else set.add(val);
      onChange();
    });
  });
}

function _paint(bar, filter, facets) {
  // .media-filter-bar (reused, not reinvented) already carries the
  // flex-wrap row layout AND 25-mobile.css's horizontal-scroll-snap
  // treatment for exactly this "one row of .media-pill chips" shape —
  // see 26-library-merge.css's #libraryFilterBar comment. A row whose
  // builder returned '' (nothing visible in it) simply contributes
  // nothing here — no empty wrapper left behind.
  bar.innerHTML =
    cameraChipsHTML(state.cameras, filter, facets.cameras) +
    labelChipsHTML(_OBJECT_LABELS, filter, facets.labels) +
    categoryChipsHTML(filter, facets.categories);
}

/**
 * Paint the bar into #libraryFilterBar and wire every chip's toggle.
 * Async: fetches fresh `/api/library/facets` counts for the current
 * `filter` + `kinds` on every call (mount, and every chip toggle / quick
 * tile jump via `onChange` re-invoking this) before painting — while
 * that fetch is in flight, or if it fails, the PREVIOUS successful
 * facets response stays on screen (`_facetsCache`) rather than the bar
 * blanking or a spinner stealing focus, the same non-blocking pattern
 * `weather/stats.js::loadWeatherStats` uses for its own chart data.
 * Never awaited by callers on purpose — repainting the count badges is
 * not on the critical path for the grid's own data reload.
 */
export async function renderLibraryFilterBar(filter, kinds, onChange) {
  const bar = byId('libraryFilterBar');
  if (!bar) return;
  const facets = await _facetsCache.refresh(() => fetchLibraryFacets(filter, kinds));
  _paint(bar, filter, facets);
  _wireChips(bar, filter, onChange);
}
