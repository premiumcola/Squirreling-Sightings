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
  state.mediaStats = [];
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 10));

// ── speciesGridTilesHTML — one tile per sighted species ──────────────────

test('renders one tile per dossier entry with sighting_count > 0', () => {
  resetState();
  state.mediaStats = [{ camera_id: 'cam1', species_counts: { ['Elster']: 5, ['Amsel']: 2 } }];
  const html = speciesGridTilesHTML();
  assert.match(html, /data-species="Elster"/);
  assert.match(html, /data-species="Amsel"/);
  assert.match(html, />5</);
  assert.match(html, />2</);
});

test('excludes species with sighting_count === 0', () => {
  resetState();
  state.mediaStats = [{ camera_id: 'cam1', species_counts: { ['Elster']: 5, ['Nieuwvogel']: 0 } }];
  const html = speciesGridTilesHTML();
  assert.match(html, /data-species="Elster"/);
  assert.doesNotMatch(html, /data-species="Nieuwvogel"/);
});

test('renders most-sighted first, in the order mediaSpeciesOptions provides', () => {
  resetState();
  // loadBirdSpeciesOptions() already sorts count-desc before this ever
  // sees the list — this only pins that the tile builder preserves
  // that order rather than re-sorting (or worse, reversing) it.
  state.mediaStats = [{ camera_id: 'cam1', species_counts: { ['Elster']: 5, ['Amsel']: 2 } }];
  const html = speciesGridTilesHTML();
  assert.ok(html.indexOf('Elster') < html.indexOf('Amsel'));
});

test('no tiles when nothing has been sighted yet', () => {
  resetState();
  state.mediaStats = [];
  assert.equal(speciesGridTilesHTML(), '');
});

test('species names are HTML-escaped in the tile markup', () => {
  resetState();
  state.mediaStats = [{ camera_id: 'cam1', species_counts: { ['<script>alert(1)</script>']: 1 } }];
  assert.doesNotMatch(speciesGridTilesHTML(), /<script>/);
});

// ── icon resolution — real SVG for a known species, emoji otherwise ─────

test('a known species (Elster) renders its real SVG icon', () => {
  resetState();
  state.mediaStats = [{ camera_id: 'cam1', species_counts: { ['Elster']: 3 } }];
  const html = speciesGridTilesHTML();
  assert.match(html, /<svg/);
  assert.doesNotMatch(html, /species-icon-emoji/);
});

test('an unmapped species falls back to the emoji icon', () => {
  resetState();
  state.mediaStats = [{ camera_id: 'cam1', species_counts: { ['Voglus Incognitus']: 1 } }];
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
  state.mediaStats = [{ camera_id: 'cam1', species_counts: { ['Elster']: 5, ['Amsel']: 2 } }];
  assert.match(speciesGridEntryTileHTML(), /2 Arten gesichtet/);
});

test('the entry tile uses the singular form for exactly one species', () => {
  resetState();
  state.mediaStats = [{ camera_id: 'cam1', species_counts: { ['Elster']: 5 } }];
  assert.match(speciesGridEntryTileHTML(), /1 Art gesichtet/);
});

test('the entry tile shows an empty-state hint when nothing has been sighted', () => {
  resetState();
  // Stats HAVE arrived, they just hold no species — that is a real
  // empty state, unlike the one below.
  state.mediaStats = [{ camera_id: 'cam1', species_counts: {} }];
  assert.match(speciesGridEntryTileHTML(), /Noch keine Sichtung/);
});

test('before the stats arrive the tile says loading, not "none"', () => {
  // „Noch keine Vogelart erkannt" on a box with 320 bird clips is not an
  // empty state, it is a wrong one.
  resetState();
  state.mediaStats = [];
  assert.match(speciesGridEntryTileHTML(), /geladen/);
  assert.doesNotMatch(speciesGridEntryTileHTML(), /Noch keine Sichtung/);
});

// ── bindSpeciesGridEntryTile — nothing to wait for any more ─────────────
// The tile used to read "Noch keine Sichtung" on every operator's first
// look and patch itself once GET /api/bird-dossiers came back. The list
// is derived from `state.mediaStats` now (the stats the Mediathek loads
// for its class pills anyway), so the first paint is already the right
// one and there is no fetch, no null sentinel and no patch cycle left.

test('the entry tile is correct on its FIRST paint, with no fetch at all', () => {
  resetState();
  state.mediaStats = [{ camera_id: 'cam1', species_counts: { Elster: 5 } }];
  let fetched = 0;
  globalThis.fetch = async () => {
    fetched += 1;
    return { ok: true, json: async () => ({}) };
  };
  const tile = { outerHTML: speciesGridEntryTileHTML(), addEventListener() {} };
  globalThis.document = {
    getElementById: (id) => (id === 'mocSpeciesGridEntry' ? tile : null),
  };

  bindSpeciesGridEntryTile();

  assert.match(tile.outerHTML, /1 Art gesichtet/);
  assert.equal(fetched, 0, 'the species row must not cost a request of its own');
});
