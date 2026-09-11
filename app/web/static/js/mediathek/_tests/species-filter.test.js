// ─── mediathek/_tests/species-filter.test.js ────────────────────────────
// The Mediathek species sub-filter (narrow the grid to e.g. only Elster
// clips without leaving Mediathek for Sichtungen) — see
// mediathek/_species-filter.js's own module docstring for why this
// logic lives in a leaf module separate from filters.js: filters.js
// transitively imports lightbox.js, which pokes the real DOM at module
// load time and can't be stubbed the way the rest of this directory's
// tests stub document/fetch.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { state } from '../../core/state.js';
import {
  birdSpeciesOptions,
  selectSpecies,
  clearSpeciesIfBirdInactive,
  effectiveMediaLabels,
  speciesClipCount,
  speciesPillsHtml,
  hasSpeciesToNest,
  speciesNestOpen,
  speciesNestHtml,
} from '../_species-filter.js';

function resetState() {
  state.mediaLabels = new Set();
  state.mediaSpecies = null;
  state.mediaCamera = null;
  state.mediaStats = [];
}

/** One camera's stats row, in the shape media_index/_visible.py::
 *  camera_stats returns. */
function cam(id, species_counts) {
  return { camera_id: id, id, name: id, label_counts: { bird: 1 }, species_counts };
}

// ── speciesPillsHtml — the row only appears when "bird" is active ───────

test('no species row when "bird" is not an active class filter', () => {
  resetState();
  state.mediaStats = [cam('cam1', { Elster: 3 })];
  assert.equal(speciesPillsHtml(), '');
});

test('no species row while options have not loaded yet, even with bird active', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  assert.deepEqual(state.mediaStats, []);
  assert.equal(speciesPillsHtml(), '');
});

test('no species row when bird is active but nothing has ever been sighted', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [];
  assert.equal(speciesPillsHtml(), '');
});

test('bird active + species sighted renders one pill per species', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [cam('cam1', { Elster: 5, Amsel: 2 })];
  const html = speciesPillsHtml();
  assert.match(html, /data-species="Elster"/);
  assert.match(html, /data-species="Amsel"/);
  assert.match(html, />5</);
  assert.match(html, />2</);
});

test('the selected species pill carries the active class, others do not', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [cam('cam1', { Elster: 5, Amsel: 2 })];
  state.mediaSpecies = 'Elster';
  const html = speciesPillsHtml();
  const elsterBtn = html.match(/<button[^>]*data-species="Elster"[^>]*>/)[0];
  const amselBtn = html.match(/<button[^>]*data-species="Amsel"[^>]*>/)[0];
  assert.match(elsterBtn, /\bactive\b/);
  assert.doesNotMatch(amselBtn, /\bactive\b/);
});

test('species names are HTML-escaped in the pill markup', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [cam('cam1', { '<script>alert(1)</script>': 1 })];
  assert.doesNotMatch(speciesPillsHtml(), /<script>/);
});

// ── selecting a species narrows the built query/state ───────────────────

test('selecting a species sets state.mediaSpecies', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  selectSpecies('Elster');
  assert.equal(state.mediaSpecies, 'Elster');
});

test('selecting the already-selected species deselects it (toggle)', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  selectSpecies('Elster');
  selectSpecies('Elster');
  assert.equal(state.mediaSpecies, null);
});

test('effectiveMediaLabels replaces "bird" with the selected species, not alongside it', () => {
  // Ordinary "bird" would OR-match every bird event in the backend
  // filter (storage.py::_filter_events) — keeping both would undo the
  // narrowing entirely, so the species value must REPLACE it.
  resetState();
  state.mediaLabels = new Set(['bird']);
  selectSpecies('Elster');
  assert.deepEqual(effectiveMediaLabels(), ['Elster']);
});

test('effectiveMediaLabels drops other active class pills — a species is an exclusive narrow', () => {
  // storage.py::_filter_events is OR-of-filter-set with no AND, so
  // keeping 'cat' alongside 'Elster' would widen the result (every cat
  // event, plus every Elster one) instead of narrowing it. This was the
  // "Vogelartenfilter funktionieren nicht" bug: a species pick under the
  // default seed-every-class-pill state OR-matched unrelated classes in
  // ahead of the species narrowing.
  resetState();
  state.mediaLabels = new Set(['cat', 'bird']);
  selectSpecies('Elster');
  assert.deepEqual(effectiveMediaLabels(), ['Elster']);
});

test('no species selected: effectiveMediaLabels is the plain class-label list', () => {
  resetState();
  state.mediaLabels = new Set(['cat', 'bird']);
  assert.deepEqual(effectiveMediaLabels(), ['cat', 'bird']);
});

// ── clearing "bird" also clears any selected species ─────────────────────

test('clearSpeciesIfBirdInactive clears mediaSpecies once "bird" is deselected', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  selectSpecies('Elster');
  state.mediaLabels.delete('bird'); // the pill click handler's own toggle
  clearSpeciesIfBirdInactive();
  assert.equal(state.mediaSpecies, null);
});

test('clearSpeciesIfBirdInactive is a no-op while "bird" is still active', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  selectSpecies('Elster');
  clearSpeciesIfBirdInactive();
  assert.equal(state.mediaSpecies, 'Elster');
});

test('a cleared species filter narrows nothing — effectiveMediaLabels back to plain labels', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  selectSpecies('Elster');
  state.mediaLabels.delete('bird');
  clearSpeciesIfBirdInactive();
  assert.deepEqual(effectiveMediaLabels(), []);
});

// ── birdSpeciesOptions — the data source ────────────────────────────────
// It used to fetch GET /api/bird-dossiers and print `sighting_count`.
// That is the dossier's LIFETIME tally beside a control that filters the
// ARCHIVE — the two drift apart in both directions (retention prunes
// clips the dossier still counts; a sighting the dossier missed is still
// a clip the filter finds), which is „Ich wähle Filter Kohlmeise mit (1)
// und erhalte 31 Seiten andere Vögel". Now it counts the same events the
// grid renders, from stats the Mediathek already has.

test('counts are summed across cameras, most-clips first', () => {
  resetState();
  state.mediaStats = [cam('cam1', { Elster: 5, Amsel: 2 }), cam('cam2', { Elster: 3 })];
  assert.deepEqual(birdSpeciesOptions(), [
    { name: 'Elster', count: 8 },
    { name: 'Amsel', count: 2 },
  ]);
});

test('a selected camera scopes the counts, like the class pills above', () => {
  resetState();
  state.mediaStats = [cam('cam1', { Elster: 5 }), cam('cam2', { Amsel: 2 })];
  state.mediaCamera = 'cam2';
  assert.deepEqual(birdSpeciesOptions(), [{ name: 'Amsel', count: 2 }]);
});

test('a species with no clips never becomes a pill', () => {
  resetState();
  state.mediaStats = [cam('cam1', { Elster: 0, Amsel: 1 })];
  assert.deepEqual(birdSpeciesOptions(), [{ name: 'Amsel', count: 1 }]);
});

test('stats without a species_counts map are simply empty, not a throw', () => {
  resetState();
  state.mediaStats = [{ camera_id: 'cam1', label_counts: { bird: 4 } }];
  assert.deepEqual(birdSpeciesOptions(), []);
});

test('equal counts fall back to a stable German-alphabetical order', () => {
  resetState();
  state.mediaStats = [cam('cam1', { Zaunkönig: 2, Amsel: 2 })];
  assert.deepEqual(
    birdSpeciesOptions().map((o) => o.name),
    ['Amsel', 'Zaunkönig'],
  );
});

// ── speciesClipCount — the number filters.js prints on the class row ────
//
// While a species narrows the grid, „Vogel" may only claim what that
// species can actually return: with „Elster 150" picked, a „Vogel 330"
// beside it is a number no reachable filter produces
// („aktualisiere die angezeigte zahl in den filtern basierend auf der
// aktuellen filterung!!"). It reads the pill's OWN count, so the two can
// never disagree.

test('speciesClipCount is the very number that species pill prints', () => {
  resetState();
  state.mediaStats = [cam('cam1', { Elster: 150, Kohlmeise: 64 })];
  assert.equal(speciesClipCount('Elster'), 150);
  assert.equal(speciesClipCount('Kohlmeise'), 64);
});

test('a species with no clips — or none at all — counts zero, never NaN', () => {
  resetState();
  state.mediaStats = [cam('cam1', { Elster: 3 })];
  assert.equal(speciesClipCount('Zaunkönig'), 0);
  assert.equal(speciesClipCount(null), 0);
});

test('speciesClipCount respects the camera scope the pills use', () => {
  resetState();
  state.mediaStats = [cam('cam1', { Elster: 150 }), cam('cam2', { Elster: 7 })];
  assert.equal(speciesClipCount('Elster'), 157, 'all cameras when none is selected');
  state.mediaCamera = 'cam2';
  assert.equal(speciesClipCount('Elster'), 7);
});

// ── the bubble: „die spezies … als unterelemente zu Vogel" ──────────────
//
// The species were a SECOND ROW under the class row, which gave a
// narrowing of one pill the same rank as the whole taxonomy. They are the
// „Vogel" pill's children now. Open is not a state of its own: the bubble
// stands open exactly while „Vogel" is the active class filter, so one
// tap keeps one meaning.

const HEAD = '<button data-val="bird">ICON</button>';

test('the bubble is open while "bird" is active and something was sighted', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [cam('cam1', { Elster: 5 })];
  assert.equal(speciesNestOpen(), true);
});

test('deselecting "bird" collapses it back to an ordinary pill', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [cam('cam1', { Elster: 5 })];
  state.mediaLabels.delete('bird');
  assert.equal(speciesNestOpen(), false);
  assert.equal(speciesNestHtml(HEAD), '');
});

test('an installation with no sighted species never opens an empty bubble', () => {
  // A control that promises children it does not have. „Vogel" stays a
  // plain pill until the first species is actually on camera.
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [{ camera_id: 'cam1', label_counts: { bird: 12 } }];
  assert.equal(hasSpeciesToNest(), false);
  assert.equal(speciesNestOpen(), false);
  assert.equal(speciesNestHtml(HEAD), '');
});

test('the camera scope decides it too — a cam with no species gets no bubble', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [cam('cam1', { Elster: 5 }), { camera_id: 'cam2', label_counts: {} }];
  assert.equal(speciesNestOpen(), true);
  state.mediaCamera = 'cam2';
  assert.equal(speciesNestOpen(), false);
});

test('the open bubble carries the caller’s own head button, then the chips', () => {
  // The head is passed IN rather than rebuilt here: filters.js owns the
  // class-pill vocabulary, so „Vogel" is the same button whether it
  // stands in the row or heads the bubble.
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [cam('cam1', { Elster: 5, Amsel: 2 })];
  const html = speciesNestHtml(HEAD);
  assert.match(html, /class="media-nest media-nest--species"/);
  assert.ok(html.includes(HEAD), 'the head goes in untouched');
  assert.ok(html.indexOf(HEAD) < html.indexOf('data-species="Elster"'), 'head first, chips after');
  assert.match(html, /data-species="Amsel"/);
});

test('the chips sit in their own strip inside the bubble, not loose in it', () => {
  // .media-filter-bar is what gives them the sideways scroll-snap strip
  // on a phone (25-mobile.css); a species list is open-ended where the
  // class taxonomy is eight words long.
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaStats = [cam('cam1', { Elster: 5 })];
  assert.match(speciesNestHtml(HEAD), /<div class="media-filter-bar media-nest-kids">/);
});
