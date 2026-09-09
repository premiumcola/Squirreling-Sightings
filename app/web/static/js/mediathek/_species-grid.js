// ─── mediathek/_species-grid.js ────────────────────────────────────────────
// The "Vogelarten" entry point into the Mediathek: a grid of every bird
// species this installation has actually sighted — icon, German name,
// sighting count — reachable from its own card in the overview grid
// (_overview.js::renderMediaOverview). Tapping a tile narrows straight
// into the all-cameras drilldown for that one species.
//
// NAMED "Vogelarten", NOT "Tiere" — _overview.js already ships a "Tiere"
// quick tile (the cross-camera, cross-species animal-LABEL jump into the
// merged /api/library grid; see that tile's own comment in _overview.js).
// This is a different surface — a per-SPECIES breakdown, bird-only
// because its data source is bird-only (GET /api/bird-dossiers, via
// _species-filter.js — mammals have no dossier/sighting_count concept,
// same limitation sichtungen/_achievements.js documents for its own
// mammal tiles). Reusing the "Tiere" name for a second, differently-
// behaving tile would read as a duplicate/contradiction, so this one
// gets its own, more precise name instead.
//
// LEAF MODULE, SAME REASON AS _species-filter.js's OWN ONE: the pure
// exports below (speciesGridTilesHTML, selectSpeciesFromGrid,
// speciesGridEntryTileHTML) must stay importable under the node --test
// stubs the rest of mediathek/_tests/ relies on, so this file never
// reaches into filters.js/_paging.js/_drilldown.js — that chain ends at
// lightbox.js, which pokes the real DOM at module load time (see
// _species-filter.js's own header for the full story). The DOM-touching
// functions further down (renderMediaSpeciesGrid and friends) only
// reach `document`/`window` INSIDE a function body, never at module top
// level, so importing this whole file is still safe under those stubs —
// they are just never the functions a unit test calls.
//
// SELECTION REUSES _species-filter.js's OWN selectSpecies() — not a
// second species-selection mechanism (see selectSpeciesFromGrid below).
// The actual "reveal the drilldown" half is NOT done here: it lives in
// mediathek/_drilldown.js::openMediaSpeciesDrilldown, reached via the
// window bridge orchestration.js installs — exactly the pattern
// _overview.js's own quick tiles already use for their cross-module
// jump (window.setLibraryLabelFilter), for the same reason: that opener
// needs the heavy loadMedia/renderMediaGrid/lightbox chain this file
// must not import.
import { byId, esc } from '../core/dom.js';
import { state } from '../core/state.js';
import { speciesIconMarkup } from '../core/species-icon.js';
import { objIconSvg } from '../core/icons.js';
import { loadBirdSpeciesOptions, selectSpecies } from './_species-filter.js';
import { showMediathekView } from './_view-toggle.js';

// ── pure: the species list ──────────────────────────────────────────────
// Defensive filter even though loadBirdSpeciesOptions() already drops
// sighting_count === 0 entries before they ever reach
// state.mediaSpeciesOptions — belt-and-braces against whatever else
// might populate that field later, same spirit as _species-filter.js's
// own `sighting_count > 0` guard.
function _sightedOptions() {
  return (state.mediaSpeciesOptions || []).filter((o) => (o.count || 0) > 0);
}

function _speciesTileHTML({ name, count }) {
  return (
    `<button type="button" class="species-grid-tile" data-species="${esc(name)}">` +
    `<span class="sgt-icon">${speciesIconMarkup(name)}</span>` +
    `<span class="sgt-name">${esc(name)}</span>` +
    `<span class="sgt-count">${count}</span></button>`
  );
}

/** PURE: one tile per sighted species, most-sighted first — the order
 * state.mediaSpeciesOptions already comes sorted in
 * (_species-filter.js::loadBirdSpeciesOptions). Most-sighted-first fits
 * a "browse what I actually have" grid better than the achievements
 * grid's own order (ACH_DEFS.rank, a NATIONAL frequency table —
 * sichtungen/_ach-defs.js — unrelated to what this installation has
 * actually seen): the operator's most common visitor should be the
 * first tile they tap, not buried by an external ranking. '' when
 * nothing has been sighted yet — the caller shows an empty-state
 * message instead of an empty grid.
 */
export function speciesGridTilesHTML() {
  return _sightedOptions().map(_speciesTileHTML).join('');
}

// ── pure: the SAME selection _species-filter.js's pill click uses ──────
/** A grid tap always narrows to "bird" + this one species — unlike a
 * pill re-click (filters.js::renderSpeciesFilterPills), which TOGGLES
 * the same species off again. A grid tile is a fresh navigation
 * target, not a re-clickable filter chip, so mediaSpecies is reset to
 * null first: selectSpecies() itself is the exact function
 * _species-filter.js's own pill click calls, not a reimplementation. */
export function selectSpeciesFromGrid(name) {
  state.mediaLabels = new Set(['bird']);
  state.mediaSpecies = null;
  selectSpecies(name);
}

// ── the "Vogelarten" entry tile in the overview grid ────────────────────
// Same .moc-card/.moc-quick shape _overview.js's own quick tiles use
// (Tiere/Menschen/Wetterereignisse) — this reads as one more of them,
// not a new visual language. No dedicated CSS needed for the wrapper:
// it inherits .moc-card/.moc-all-thumb exactly like those three do.
export function speciesGridEntryTileHTML() {
  const n = _sightedOptions().length;
  const desc = n > 0 ? `${n} Art${n === 1 ? '' : 'en'} gesichtet` : 'Noch keine Sichtung';
  return `<div class="moc-card moc-quick" id="mocSpeciesGridEntry">
    <div class="moc-all-thumb moc-quick-thumb">${objIconSvg('bird', 48)}</div>
    <div class="moc-body">
      <div class="moc-name">Vogelarten</div>
      <div class="moc-desc">${esc(desc)}</div>
    </div>
  </div>`;
}

// ── DOM: render + wire the grid, and the view-level open/close ─────────
function _wireTileClicks(container) {
  container.querySelectorAll('.species-grid-tile').forEach((tile) => {
    tile.addEventListener('click', () => {
      selectSpeciesFromGrid(tile.dataset.species);
      // Bridged in orchestration.js — see the module header above for
      // why this file cannot import _drilldown.js directly.
      window.openMediaSpeciesDrilldown?.();
    });
  });
}

export function renderMediaSpeciesGrid() {
  const body = byId('mediaSpeciesGridBody');
  if (!body) return;
  const html = speciesGridTilesHTML();
  body.innerHTML = html || `<div class="species-grid-empty">Noch keine Vogelart erkannt.</div>`;
  _wireTileClicks(body);
}

/** The "Vogelarten" overview tile's own click target. Reuses
 * state.mediaSpeciesOptions if _species-filter.js (or an earlier open
 * of this same grid) already fetched it — never a second
 * GET /api/bird-dossiers. */
export function openMediaSpeciesGridView() {
  showMediathekView('mediaSpeciesGrid');
  if (state.mediaSpeciesOptions === null) {
    loadBirdSpeciesOptions().then(renderMediaSpeciesGrid);
  } else {
    renderMediaSpeciesGrid();
  }
}

// The grid's own "← Übersicht" back button (data-action="closeMediaSpeciesGrid",
// see partials/mediathek.html#mediaSpeciesGrid + core/action-registry.js).
export function closeMediaSpeciesGrid() {
  showMediathekView('mediaOverview');
}

/** The entry tile's count is only accurate once
 * state.mediaSpeciesOptions has been fetched. On the FIRST Mediathek
 * paint it is still null — filters.js's own loadBirdSpeciesOptions()
 * call only fires once the "bird" pill is active inside a drilldown
 * (see filters.js), which the overview never reaches — so without
 * this, every operator's very first look at the tile would read
 * "Noch keine Sichtung" even on an installation with dozens of
 * sightings. Same singleton fetch every other caller here shares (see
 * loadBirdSpeciesOptions's own header); patches just this one tile
 * in place once it resolves rather than re-rendering the whole grid. */
function _primeSpeciesGridEntryTile() {
  if (state.mediaSpeciesOptions !== null) return;
  loadBirdSpeciesOptions().then(() => {
    const el = byId('mocSpeciesGridEntry');
    if (!el) return; // overview moved on before the fetch resolved
    el.outerHTML = speciesGridEntryTileHTML();
    bindSpeciesGridEntryTile();
  });
}

/** Wired from renderMediaOverview() after every re-render, mirroring
 * _overview.js's own _bindQuickLabelTiles() re-wiring pattern — the
 * previous listener goes with the DOM node innerHTML replacement
 * discards, so this never double-fires. */
export function bindSpeciesGridEntryTile() {
  byId('mocSpeciesGridEntry')?.addEventListener('click', openMediaSpeciesGridView);
  _primeSpeciesGridEntryTile();
}
