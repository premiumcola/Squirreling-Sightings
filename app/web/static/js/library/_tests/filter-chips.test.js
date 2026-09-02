// ─── library/_tests/filter-chips.test.js ────────────────────────────────
// Pure-function coverage for library/_filter-chips.js — the three
// facets-scoped chip rows the relevance-pruned filter bar renders. Every
// import this module makes loads cleanly under plain node (see that
// file's own header for why `MEDIA_FILTER_LABELS` is a parameter here
// instead), so this is a straight function-in/string-out test, no DOM.
import './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  chipVisible,
  cameraChipsHTML,
  labelChipsHTML,
  categoryChipsHTML,
} from '../_filter-chips.js';
import { createLibraryFilterState } from '../_filter-state.js';

const _CAMERAS = [
  { id: 'cam1', name: 'Garten' },
  { id: 'cam2', name: 'Einfahrt' },
];
const _LABELS = ['person', 'cat', 'bird'];

// ── chipVisible ──────────────────────────────────────────────────────

test('a zero count, inactive chip is not visible', () => {
  assert.equal(chipVisible(0, false), false);
});

test('a positive count makes a chip visible even when inactive', () => {
  assert.equal(chipVisible(3, false), true);
});

test('an active chip stays visible even at zero count', () => {
  assert.equal(chipVisible(0, true), true);
});

// ── camera row ────────────────────────────────────────────────────────

test('a camera with zero matches and not selected is omitted entirely', () => {
  const filter = createLibraryFilterState();
  const html = cameraChipsHTML(_CAMERAS, filter, { cam1: 4 });
  assert.match(html, /data-val="cam1"/);
  assert.doesNotMatch(html, /data-val="cam2"/);
});

test('a camera chip is badged with its facet count', () => {
  const filter = createLibraryFilterState();
  const html = cameraChipsHTML(_CAMERAS, filter, { cam1: 7 });
  assert.match(html, /cam1"[^]*?class="mp-count"[^>]*>7</);
});

test('a zero-count chip carries no count badge at all', () => {
  const filter = createLibraryFilterState();
  filter.cameraIds.add('cam1');
  const html = cameraChipsHTML(_CAMERAS, filter, {});
  assert.doesNotMatch(html, /mp-count/);
});

test('the whole camera row is omitted when every camera has zero matches and none is active', () => {
  const filter = createLibraryFilterState();
  const html = cameraChipsHTML(_CAMERAS, filter, {});
  assert.equal(html, '');
});

test('a selected camera with zero matches stays visible, marked active', () => {
  const filter = createLibraryFilterState();
  filter.cameraIds.add('cam2');
  const html = cameraChipsHTML(_CAMERAS, filter, { cam1: 5 });
  assert.match(html, /data-val="cam1"/);
  assert.match(
    html,
    /class="media-pill cat-filter-btn active" data-group="camera" data-val="cam2"/,
  );
});

// ── label row ─────────────────────────────────────────────────────────

test('label chips are pruned to whatever the caller-supplied vocabulary carries a count for', () => {
  const filter = createLibraryFilterState();
  const html = labelChipsHTML(_LABELS, filter, { cat: 2 });
  assert.match(html, /data-val="cat"/);
  assert.doesNotMatch(html, /data-val="person"/);
  assert.doesNotMatch(html, /data-val="bird"/);
});

test('an empty facets.labels dict hides the entire label row', () => {
  const filter = createLibraryFilterState();
  assert.equal(labelChipsHTML(_LABELS, filter, {}), '');
});

// ── category row ──────────────────────────────────────────────────────

test('category chips are pruned the same way, keyed off WEATHER_TYPES', () => {
  const filter = createLibraryFilterState();
  const html = categoryChipsHTML(filter, { thunder: 3 });
  assert.match(html, /data-val="thunder"/);
  assert.doesNotMatch(html, /data-val="snow"/);
});

test('an empty facets.categories dict hides the entire category row', () => {
  const filter = createLibraryFilterState();
  assert.equal(categoryChipsHTML(filter, {}), '');
});

test('a selected category with zero matches stays visible', () => {
  const filter = createLibraryFilterState();
  filter.categories.add('fog');
  const html = categoryChipsHTML(filter, {});
  assert.match(html, /data-val="fog"/);
});

// ── a facets response that lost a dimension ───────────────────────────
// `_filter-bar.js::_paint` hands each row `facets.cameras` /
// `facets.labels` / `facets.categories` straight off the fetched
// response. `emptyFacets()`'s own docstring promises those keys always
// exist "rather than a render crashing on a missing key" — but that
// promise only holds for the FRESH cache. `createFacetsCache().refresh`
// commits whatever the server actually sent, so a response that is
// missing a dimension (or `null` outright — core/api.js::apiGet returns
// null for any non-JSON content-type, e.g. a proxy/Flask HTML error
// page) reaches these builders with `counts === undefined`. The
// `cameras`/`objectLabels` list argument is already `|| []`-guarded;
// `counts` was not, so `counts[c.id]` threw and took the whole filter
// bar's paint with it.

test('a camera row survives a facets response that carries no cameras dict', () => {
  const filter = createLibraryFilterState();
  filter.cameraIds.add('cam1');
  assert.doesNotThrow(() => cameraChipsHTML(_CAMERAS, filter, undefined));
  assert.match(cameraChipsHTML(_CAMERAS, filter, undefined), /data-val="cam1"/);
});

test('a label row survives a facets response that carries no labels dict', () => {
  const filter = createLibraryFilterState();
  assert.doesNotThrow(() => labelChipsHTML(_LABELS, filter, undefined));
  assert.equal(labelChipsHTML(_LABELS, filter, undefined), '');
});

test('a category row survives a facets response that carries no categories dict', () => {
  const filter = createLibraryFilterState();
  assert.doesNotThrow(() => categoryChipsHTML(filter, undefined));
  assert.equal(categoryChipsHTML(filter, undefined), '');
});
