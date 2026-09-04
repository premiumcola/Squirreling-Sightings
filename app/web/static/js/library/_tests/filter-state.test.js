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

// ── the Wetterdaten chart does NOT filter this grid ─────────────────────
//
// It used to: a span dragged in the weather graph put since/until into
// this query. The two live in different sections of the page, so the
// operator zoomed the graph, scrolled up, and found "Keine Eintraege im
// gewaehlten Zeitraum" with nothing on screen explaining it — "der
// Zeitraum von dem Wettergrafen darf nicht die Mediathek bestimmen,
// also loes da die Verbindung".
//
// These three pinned the coupling. They now pin its absence, because a
// convenience that silently empties the library is worse than no
// convenience.

test('ein aktiver Chart-Zoom filtert die Mediathek NICHT', () => {
  const filter = createLibraryFilterState();
  setZoomRange('2026-08-20T12:00:00', '2026-08-20T18:00:00');
  try {
    const params = libraryQueryParams(filter);
    assert.equal(params.has('since'), false, 'der Graph darf das Raster nicht einengen');
    assert.equal(params.has('until'), false);
  } finally {
    clearZoomRange();
  }
});

test('ohne Zoom ist seit jeher nichts gesetzt — daran aendert sich nichts', () => {
  setZoomRange('2026-08-20T12:00:00', '2026-08-20T18:00:00');
  clearZoomRange();
  const params = libraryQueryParams(createLibraryFilterState());
  assert.equal(params.has('since'), false);
  assert.equal(params.has('until'), false);
});

test('die eigenen Filter des Rasters bleiben davon unberuehrt', () => {
  // Der Schnitt darf nur den Zoom entfernen. Kamera, Label und Kategorie
  // sind die Filter, die NEBEN dem Raster stehen, und die bleiben.
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
    assert.equal(params.has('since'), false);
  } finally {
    clearZoomRange();
  }
});
