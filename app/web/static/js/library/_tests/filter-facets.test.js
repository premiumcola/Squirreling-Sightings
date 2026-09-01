// ─── library/_tests/filter-facets.test.js ───────────────────────────────
// Pure-function + fetch-mock coverage for library/_filter-facets.js —
// the query-param mapping onto `/api/library/facets`, and the
// fetch-with-keep-previous cache `_filter-bar.js` uses so an in-flight
// or failed refresh never blanks the chip row (see that file's own
// header). `_filter-bar.js` itself (DOM rendering, wired chips) is not
// imported here for the same reason library/_tests/filter-state.test.js
// doesn't import _filter-bar.js either — see that file's own header.
import './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  facetsQueryParams,
  emptyFacets,
  fetchLibraryFacets,
  createFacetsCache,
} from '../_filter-facets.js';
import { createLibraryFilterState } from '../_filter-state.js';
import { clearZoomRange } from '../../weather/_zoom.js';

// ── facetsQueryParams ─────────────────────────────────────────────────

test('an empty filter and no kinds produces no query params', () => {
  clearZoomRange();
  const params = facetsQueryParams(createLibraryFilterState(), null);
  assert.equal([...params.keys()].length, 0);
});

test('kinds is appended as a csv, same shape as camera_ids/labels/categories', () => {
  const params = facetsQueryParams(createLibraryFilterState(), ['sighting', 'recap']);
  assert.equal(params.get('kinds'), 'sighting,recap');
});

test('an empty kinds array is treated as "no kinds", not an empty param', () => {
  const params = facetsQueryParams(createLibraryFilterState(), []);
  assert.equal(params.has('kinds'), false);
});

test('chip filters and kinds compose in one query string', () => {
  const filter = createLibraryFilterState();
  filter.cameraIds.add('cam1');
  filter.labels.add('cat');
  const params = facetsQueryParams(filter, ['motion']);
  assert.equal(params.get('camera_ids'), 'cam1');
  assert.equal(params.get('labels'), 'cat');
  assert.equal(params.get('kinds'), 'motion');
});

// ── emptyFacets ───────────────────────────────────────────────────────

test('emptyFacets is the all-zero shape every dimension expects', () => {
  assert.deepEqual(emptyFacets(), { cameras: {}, labels: {}, categories: {}, total: 0 });
});

// ── fetchLibraryFacets ───────────────────────────────────────────────────

test('fetchLibraryFacets calls the facets route with the built query string', async () => {
  const realFetch = globalThis.fetch;
  let seenUrl = null;
  globalThis.fetch = (url) => {
    seenUrl = url;
    return Promise.resolve({
      ok: true,
      headers: { get: () => 'application/json' },
      json: () => Promise.resolve({ cameras: {}, labels: {}, categories: {}, total: 0 }),
    });
  };
  try {
    const filter = createLibraryFilterState();
    filter.labels.add('fox');
    await fetchLibraryFacets(filter, null);
    assert.equal(seenUrl, '/api/library/facets?labels=fox');
  } finally {
    globalThis.fetch = realFetch;
  }
});

// ── createFacetsCache: keep-previous on failure/being superseded ────────

test('a fresh cache starts at emptyFacets()', () => {
  const cache = createFacetsCache();
  assert.deepEqual(cache.current, emptyFacets());
});

test('a successful refresh replaces current', async () => {
  const cache = createFacetsCache();
  const result = { cameras: { cam1: 2 }, labels: {}, categories: {}, total: 2 };
  await cache.refresh(() => Promise.resolve(result));
  assert.deepEqual(cache.current, result);
});

test('a failed refresh keeps the previous facets rather than blanking', async () => {
  const cache = createFacetsCache();
  const ok = { cameras: { cam1: 1 }, labels: {}, categories: {}, total: 1 };
  await cache.refresh(() => Promise.resolve(ok));
  await cache.refresh(() => Promise.reject(new Error('network down')));
  assert.deepEqual(cache.current, ok);
});

test('a slow, now-superseded refresh does not clobber a faster later result', async () => {
  const cache = createFacetsCache();
  let resolveSlow;
  const slow = new Promise((res) => {
    resolveSlow = res;
  });
  const inFlight = cache.refresh(() => slow);
  const fast = { cameras: {}, labels: { bird: 3 }, categories: {}, total: 3 };
  await cache.refresh(() => Promise.resolve(fast));
  resolveSlow({ cameras: {}, labels: {}, categories: {}, total: 999 });
  await inFlight;
  assert.deepEqual(cache.current, fast);
});
