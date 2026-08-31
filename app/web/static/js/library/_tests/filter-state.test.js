// ─── library/_tests/filter-bar.test.js ──────────────────────────────────
// Stage 6 of the Mediathek + Wetter-Ereignisse merge: pure-function
// coverage for library/_filter-state.js — the merged grid's filter
// state + its mapping onto /api/library's query params. Imports
// _filter-state.js directly, not _filter-bar.js: the latter also pulls
// in mediathek/filters.js for its label vocabulary, and through that
// the whole Mediathek module graph (bbox-overlay, lightbox.js, …),
// which needs a real DOM this repo's plain-node test harness doesn't
// provide (see _setup.js's own header) — exactly why _filter-state.js
// is its own file. renderLibraryFilterBar itself (DOM rendering) is
// untestable here for the same reason; same scope boundary
// library/_tests/pagination.test.js already draws around its own DOM
// half.
import './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createLibraryFilterState, libraryQueryParams } from '../_filter-state.js';
import { setZoomRange, clearZoomRange } from '../../weather/_zoom.js';

test('a fresh filter state has every group empty', () => {
  const filter = createLibraryFilterState();
  assert.equal(filter.cameraIds.size, 0);
  assert.equal(filter.labels.size, 0);
  assert.equal(filter.categories.size, 0);
});

test('an empty filter produces no query params at all — "Alles gemischt", no `kinds`', () => {
  clearZoomRange();
  const filter = createLibraryFilterState();
  const params = libraryQueryParams(filter);
  assert.equal([...params.keys()].length, 0);
  assert.equal(params.has('kinds'), false);
});

test('camera chips map onto camera_ids as a csv', () => {
  const filter = createLibraryFilterState();
  filter.cameraIds.add('cam1');
  filter.cameraIds.add('cam2');
  const params = libraryQueryParams(filter);
  assert.equal(params.get('camera_ids'), 'cam1,cam2');
  assert.equal(params.has('labels'), false);
  assert.equal(params.has('categories'), false);
});

test('object-class chips map onto labels as a csv', () => {
  const filter = createLibraryFilterState();
  filter.labels.add('person');
  filter.labels.add('fox');
  const params = libraryQueryParams(filter);
  assert.equal(params.get('labels'), 'person,fox');
});

test('weather-category chips map onto categories as a csv', () => {
  const filter = createLibraryFilterState();
  filter.categories.add('thunder');
  filter.categories.add('heavy_rain');
  const params = libraryQueryParams(filter);
  assert.equal(params.get('categories'), 'thunder,heavy_rain');
});

test('all three groups combine into one query string, never a `kinds` param', () => {
  clearZoomRange();
  const filter = createLibraryFilterState();
  filter.cameraIds.add('cam1');
  filter.labels.add('bird');
  filter.categories.add('fog');
  const params = libraryQueryParams(filter);
  assert.equal(params.get('camera_ids'), 'cam1');
  assert.equal(params.get('labels'), 'bird');
  assert.equal(params.get('categories'), 'fog');
  assert.equal(params.has('kinds'), false);
});

// ── Stage 7: the Wetterdaten-chart's drag-zoom composes in here too ──────

test('an active zoom range adds since/until, with no chip filters set', () => {
  const filter = createLibraryFilterState();
  setZoomRange('2026-08-20T12:00:00', '2026-08-20T18:00:00');
  try {
    const params = libraryQueryParams(filter);
    assert.equal(params.get('since'), '2026-08-20T12:00:00');
    assert.equal(params.get('until'), '2026-08-20T18:00:00');
  } finally {
    clearZoomRange();
  }
});

test('a cleared zoom range omits since/until entirely — not empty strings', () => {
  setZoomRange('2026-08-20T12:00:00', '2026-08-20T18:00:00');
  clearZoomRange();
  const filter = createLibraryFilterState();
  const params = libraryQueryParams(filter);
  assert.equal(params.has('since'), false);
  assert.equal(params.has('until'), false);
});

test('chip filters and an active zoom range compose — neither overrides the other', () => {
  const filter = createLibraryFilterState();
  filter.cameraIds.add('cam1');
  filter.labels.add('fox');
  filter.categories.add('thunder');
  setZoomRange('2026-08-20T12:00:00', '2026-08-20T18:00:00');
  try {
    const params = libraryQueryParams(filter);
    assert.equal(params.get('camera_ids'), 'cam1');
    assert.equal(params.get('labels'), 'fox');
    assert.equal(params.get('categories'), 'thunder');
    assert.equal(params.get('since'), '2026-08-20T12:00:00');
    assert.equal(params.get('until'), '2026-08-20T18:00:00');
  } finally {
    clearZoomRange();
  }
});
