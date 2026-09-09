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
  speciesPillsHtml,
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
