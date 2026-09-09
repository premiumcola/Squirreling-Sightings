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
  loadBirdSpeciesOptions,
  selectSpecies,
  clearSpeciesIfBirdInactive,
  effectiveMediaLabels,
  speciesPillsHtml,
} from '../_species-filter.js';

function resetState() {
  state.mediaLabels = new Set();
  state.mediaSpecies = null;
  state.mediaSpeciesOptions = null;
}

// ── speciesPillsHtml — the row only appears when "bird" is active ───────

test('no species row when "bird" is not an active class filter', () => {
  resetState();
  state.mediaSpeciesOptions = [{ name: 'Elster', count: 3 }];
  assert.equal(speciesPillsHtml(), '');
});

test('no species row while options have not loaded yet, even with bird active', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  assert.equal(state.mediaSpeciesOptions, null);
  assert.equal(speciesPillsHtml(), '');
});

test('no species row when bird is active but nothing has ever been sighted', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaSpeciesOptions = [];
  assert.equal(speciesPillsHtml(), '');
});

test('bird active + species sighted renders one pill per species', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaSpeciesOptions = [
    { name: 'Elster', count: 5 },
    { name: 'Amsel', count: 2 },
  ];
  const html = speciesPillsHtml();
  assert.match(html, /data-species="Elster"/);
  assert.match(html, /data-species="Amsel"/);
  assert.match(html, />5</);
  assert.match(html, />2</);
});

test('the selected species pill carries the active class, others do not', () => {
  resetState();
  state.mediaLabels = new Set(['bird']);
  state.mediaSpeciesOptions = [
    { name: 'Elster', count: 5 },
    { name: 'Amsel', count: 2 },
  ];
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
  state.mediaSpeciesOptions = [{ name: '<script>alert(1)</script>', count: 1 }];
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

// ── loadBirdSpeciesOptions — the data source ─────────────────────────────
// GET /api/bird-dossiers already backs the Sichtungen dossier panel;
// reused here filtered to sighting_count > 0 so a species the daily
// prebuild sweep pre-created as a locked, never-sighted placeholder
// (bird_dossiers.py::sweep_prebuild) never shows up as a pill.

test('loadBirdSpeciesOptions keeps only sighted species, sorted by count desc', async () => {
  resetState();
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      dossiers: [
        { common_name_de: 'Rotkehlchen', latin: 'erithacus rubecula', sighting_count: 0 },
        { common_name_de: 'Amsel', latin: 'turdus merula', sighting_count: 2 },
        { common_name_de: 'Elster', latin: 'pica pica', sighting_count: 5 },
        { latin: 'no de name', sighting_count: 9 },
      ],
    }),
  });
  const options = await loadBirdSpeciesOptions();
  assert.deepEqual(options, [
    { name: 'Elster', count: 5 },
    { name: 'Amsel', count: 2 },
  ]);
  assert.deepEqual(state.mediaSpeciesOptions, options);
});
