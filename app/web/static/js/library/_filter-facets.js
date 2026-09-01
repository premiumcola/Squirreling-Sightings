// ─── library/_filter-facets.js ──────────────────────────────────────────
// Relevance-pruned + live-counted filter bar: the pure half — query
// params, the `/api/library/facets` fetch itself, and the "keep the
// previous render up while a fetch is in flight or just failed" cache —
// split out of _filter-bar.js the same way _filter-state.js already is
// (see that file's own header for the identical reasoning): a leaf
// module, no `mediathek/filters.js` import, so it stays importable
// under this repo's plain-node test harness (library/_tests/_setup.js)
// without pulling in the whole Mediathek graph _filter-bar.js itself
// still needs for its label vocabulary.
import { apiGet } from '../core/api.js';
import { libraryQueryParams } from './_filter-state.js';

/** `/api/library/facets`'s query params for the current filter + kinds
 * — `libraryQueryParams(filter)` plus `kinds`, the one param that lives
 * outside `filter` (see library/page.js's own header for why: `kinds`
 * is set by exactly one quick tile, never a chip). */
export function facetsQueryParams(filter, kinds) {
  const params = libraryQueryParams(filter);
  if (kinds && kinds.length) params.set('kinds', kinds.join(','));
  return params;
}

/** The all-zero shape a fresh page (or a permanently-failing fetch)
 * reads as — every chip row's own visibility check then sees "nothing
 * has a count" and hides the whole row, rather than a render crashing
 * on a missing key. */
export function emptyFacets() {
  return { cameras: {}, labels: {}, categories: {}, total: 0 };
}

/** One `/api/library/facets` call for the current filter + kinds. */
export function fetchLibraryFacets(filter, kinds) {
  return apiGet(`/api/library/facets?${facetsQueryParams(filter, kinds).toString()}`);
}

/**
 * Fetch-with-keep-previous cache for the facets response — the same
 * catch-and-keep-previous non-blocking pattern `weather/stats.js::
 * loadWeatherStats` already uses for its own chart data, generalised
 * into a small state machine so it is unit-testable without a fetch
 * mock or a DOM: `refresh` takes a promise-returning thunk rather than
 * calling `fetchLibraryFacets` itself.
 *
 * A slow, now-superseded call resolving AFTER a faster, later one must
 * not clobber the newer result — `refresh` tags every in-flight call
 * with a sequence number and only ever commits the LATEST call's
 * outcome, discarding an out-of-order resolution silently.
 */
export function createFacetsCache() {
  let current = emptyFacets();
  let seq = 0;
  return {
    get current() {
      return current;
    },
    async refresh(fetchPromiseFactory) {
      const mySeq = ++seq;
      try {
        const result = await fetchPromiseFactory();
        if (mySeq === seq) current = result;
      } catch {
        // Transient error — leave `current` (the previous successful
        // render's data) exactly as it was rather than blanking the bar.
      }
      return current;
    },
  };
}
