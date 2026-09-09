// ─── mediathek/_tests/species-grid.test.js ───────────────────────────────
// The "Vogelarten" species grid (mediathek/_species-grid.js) — see that
// module's own header for why it stays a leaf module, same reasoning as
// species-filter.test.js's own sibling file: filters.js/_paging.js/
// _drilldown.js transitively pull in lightbox.js, which pokes the real
// DOM at module load time and can't be stubbed the way this directory's
// tests stub document/fetch.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { state } from '../../core/state.js';
import { selectSpecies } from '../_species-filter.js';
import {
  speciesGridTilesHTML,
  selectSpeciesFromGrid,
  speciesGridEntryTileHTML,
  bindSpeciesGridEntryTile,
} from '../_species-grid.js';

function resetState() {
  state.mediaLabels = new Set();
  state.mediaSpecies = null;
  state.mediaSpeciesOptions = null;
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 10));

// ── speciesGridTilesHTML — one tile per sighted species ──────────────────

test('renders one tile per dossier entry with sighting_count > 0', () => {
  resetState();
  state.mediaSpeciesOptions = [
    { name: 'Elster', count: 5 },
    { name: 'Amsel', count: 2 },
  ];
  const html = speciesGridTilesHTML();
  assert.match(html, /data-species="Elster"/);
  assert.match(html, /data-species="Amsel"/);
  assert.match(html, />5</);
  assert.match(html, />2</);
});

test('excludes species with sighting_count === 0', () => {
  resetState();
  state.mediaSpeciesOptions = [
    { name: 'Elster', count: 5 },
    { name: 'Nieuwvogel', count: 0 },
  ];
  const html = speciesGridTilesHTML();
  assert.match(html, /data-species="Elster"/);
  assert.doesNotMatch(html, /data-species="Nieuwvogel"/);
});

test('renders most-sighted first, in the order mediaSpeciesOptions provides', () => {
  resetState();
  // loadBirdSpeciesOptions() already sorts count-desc before this ever
  // sees the list — this only pins that the tile builder preserves
  // that order rather than re-sorting (or worse, reversing) it.
  state.mediaSpeciesOptions = [
    { name: 'Elster', count: 5 },
    { name: 'Amsel', count: 2 },
  ];
  const html = speciesGridTilesHTML();
  assert.ok(html.indexOf('Elster') < html.indexOf('Amsel'));
});

test('no tiles when nothing has been sighted yet', () => {
  resetState();
  state.mediaSpeciesOptions = [];
  assert.equal(speciesGridTilesHTML(), '');
});

test('species names are HTML-escaped in the tile markup', () => {
  resetState();
  state.mediaSpeciesOptions = [{ name: '<script>alert(1)</script>', count: 1 }];
  assert.doesNotMatch(speciesGridTilesHTML(), /<script>/);
});

// ── icon resolution — real SVG for a known species, emoji otherwise ─────

test('a known species (Elster) renders its real SVG icon', () => {
  resetState();
  state.mediaSpeciesOptions = [{ name: 'Elster', count: 3 }];
  const html = speciesGridTilesHTML();
  assert.match(html, /<svg/);
  assert.doesNotMatch(html, /species-icon-emoji/);
});

test('an unmapped species falls back to the emoji icon', () => {
  resetState();
  state.mediaSpeciesOptions = [{ name: 'Voglus Incognitus', count: 1 }];
  const html = speciesGridTilesHTML();
  assert.match(html, /species-icon-emoji/);
});

// ── selectSpeciesFromGrid — the SAME mechanism as the species pill row ──

test('selectSpeciesFromGrid narrows via the same state fields selectSpecies() drives', () => {
  resetState();
  selectSpeciesFromGrid('Elster');
  assert.equal(state.mediaSpecies, 'Elster');
  assert.ok(state.mediaLabels.has('bird'));
});

test('selectSpeciesFromGrid always selects — a repeat tap never deselects, unlike a pill re-click', () => {
  resetState();
  selectSpeciesFromGrid('Elster');
  selectSpeciesFromGrid('Elster');
  assert.equal(state.mediaSpecies, 'Elster');
});

test('selectSpeciesFromGrid drives selectSpecies() itself, not a duplicated selection path', () => {
  // Prove both entrypoints land on the exact same state: run the real
  // pill-click mechanism (selectSpecies, imported straight from
  // _species-filter.js) and the grid's own mechanism from the same
  // starting state, and assert they agree bit-for-bit.
  resetState();
  state.mediaLabels = new Set(['bird']);
  selectSpecies('Amsel');
  const viaPill = { species: state.mediaSpecies, labels: [...state.mediaLabels] };

  resetState();
  selectSpeciesFromGrid('Amsel');
  const viaGrid = { species: state.mediaSpecies, labels: [...state.mediaLabels] };

  assert.deepEqual(viaGrid, viaPill);
});

test('selecting a different species from the grid replaces the previous one, not adds to it', () => {
  resetState();
  selectSpeciesFromGrid('Elster');
  selectSpeciesFromGrid('Amsel');
  assert.equal(state.mediaSpecies, 'Amsel');
  assert.equal(state.mediaLabels.size, 1);
  assert.ok(state.mediaLabels.has('bird'));
});

// ── speciesGridEntryTileHTML — the overview card ─────────────────────────

test('the entry tile counts only sighted species', () => {
  resetState();
  state.mediaSpeciesOptions = [
    { name: 'Elster', count: 5 },
    { name: 'Amsel', count: 2 },
  ];
  assert.match(speciesGridEntryTileHTML(), /2 Arten gesichtet/);
});

test('the entry tile uses the singular form for exactly one species', () => {
  resetState();
  state.mediaSpeciesOptions = [{ name: 'Elster', count: 5 }];
  assert.match(speciesGridEntryTileHTML(), /1 Art gesichtet/);
});

test('the entry tile shows an empty-state hint when nothing has been sighted', () => {
  resetState();
  state.mediaSpeciesOptions = [];
  assert.match(speciesGridEntryTileHTML(), /Noch keine Sichtung/);
});

// ── bindSpeciesGridEntryTile — self-corrects a cold-load `null` ─────────
// state.mediaSpeciesOptions is still null on the Mediathek's very first
// paint (filters.js's own loadBirdSpeciesOptions() call only fires once
// "bird" is active inside a drilldown, which the overview never reaches
// — see _species-grid.js::_primeSpeciesGridEntryTile's own comment).
// Without priming, the entry tile would misreport "Noch keine Sichtung"
// on every operator's first look, even with sightings on file.

test('bindSpeciesGridEntryTile patches the tile once options load, from a cold null state', async () => {
  resetState();
  const tile = { outerHTML: speciesGridEntryTileHTML(), addEventListener() {} };
  globalThis.document = {
    getElementById: (id) => (id === 'mocSpeciesGridEntry' ? tile : null),
  };
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      dossiers: [{ common_name_de: 'Elster', latin: 'pica pica', sighting_count: 5 }],
    }),
  });
  assert.match(tile.outerHTML, /Noch keine Sichtung/);

  bindSpeciesGridEntryTile();
  await flush();

  assert.match(tile.outerHTML, /1 Art gesichtet/);
});
