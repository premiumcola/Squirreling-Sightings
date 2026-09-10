// ─── mediathek/_drilldown.js ───────────────────────────────────────────────
// R23 split of orchestration.js — Level 2 of the Mediathek: the four ways
// into the filtered grid (one camera / all cameras / one category / one
// bird species) and the way back out. Each opener owns the same sequence —
// reset filter state, swap the two wrappers, load, prune dead pills, render
// — so they live together and share _reflowPageAfterLayout() from
// _paging.js.
//
// The section heading belongs here too: it is a pure function of
// state.mediaDrillOpen + state.mediaCamera, which only these four
// functions ever write.
import { byId, esc } from '../core/dom.js';
import { state } from '../core/state.js';
import { getCameraIcon } from '../core/icons.js';
import { _exitMediaSelectMode, _updateMediaSelectToggle } from './bulk-delete.js';
import { loadMedia } from './media-loader.js';
import { renderMediaFilterPills, _seedTopMediaLabel, _pruneEmptyMediaFilters } from './filters.js';
import { renderProcessingQueue } from './_processing.js';
import { _setActiveMocCard } from './_overview.js';
import { renderMediaGrid, _reflowPageAfterLayout } from './_paging.js';
import { showMediathekView } from './_view-toggle.js';
import { noteFilterUse } from '../weather/_time-binding.js';

const _LOADING_HTML =
  '<div style="padding:32px;text-align:center;color:var(--muted)">Lade Medien…</div>';

// Swap overview → drilldown and bring the select-mode toggle + heading in
// line with the state the caller just wrote. Also hides #libraryBlock
// (the merged library results, the toggle's third state) if it happened
// to be showing — see mediathek/_view-toggle.js.
function _showDrilldown() {
  showMediathekView('mediaDrilldown');
  _updateMediaSelectToggle();
  updateMediaSectionTitle();
}

// Always render — even if loadMedia throws, the "Keine Medien
// vorhanden." fallback is a far better UX than a frozen "Lade
// Medien…" placeholder. _pruneEmptyMediaFilters then drops any
// pre-seeded label that ended up with zero matches so the pill bar
// doesn't show stale highlights.
async function _loadAndRender(what) {
  // All four openers land here, and all four are the operator choosing a
  // camera / category / species — i.e. a filter that is NOT the time
  // chooser at the foot of the section, which therefore releases its own
  // narrowing (weather/_time-binding.js). One call here instead of four
  // in the openers above, for the same reason the openers share this
  // function at all.
  noteFilterUse(what);
  try {
    await loadMedia();
  } catch (err) {
    console.warn(`[mediathek] loadMedia (${what}) failed:`, err);
  }
  _pruneEmptyMediaFilters();
  renderMediaFilterPills();
  renderMediaGrid();
}

// Drop the previous drilldown's queue strip with its items — it
// belongs to a camera the user just left — and clear the stale grid so
// the previous camera's thumbnails don't flash before the new fetch
// resolves.
function _clearLoadedLibrary() {
  state.media = [];
  state._allMedia = [];
  renderProcessingQueue([]);
  const grid = byId('mediaGrid');
  if (grid) grid.innerHTML = _LOADING_HTML;
}

// ── Drilldown openers ───────────────────────────────────────────────────────
export async function openCategoryDrilldown(label) {
  state.mediaDrillOpen = true;
  state.mediaCamera = null;
  state.mediaLabels = new Set(label ? [label] : []);
  state.mediaSpecies = null;
  state.mediaPage = 0;
  if (state.mediaSelectMode) _exitMediaSelectMode();
  if (state.mediaLabels.size === 0) _seedTopMediaLabel();
  renderMediaFilterPills();
  _showDrilldown();
  await _loadAndRender('category');
}

export async function openAllMediaDrilldown(preFilterLabel) {
  state.mediaDrillOpen = true;
  state.mediaCamera = null;
  state.mediaLabels = preFilterLabel ? new Set([preFilterLabel]) : new Set();
  state.mediaSpecies = null;
  state.mediaPage = 0;
  if (state.mediaSelectMode) _exitMediaSelectMode();
  _clearLoadedLibrary();
  if (state.mediaLabels.size === 0) _seedTopMediaLabel();
  renderMediaFilterPills();
  showMediathekView('mediaDrilldown');
  _setActiveMocCard('__all__');
  _updateMediaSelectToggle();
  updateMediaSectionTitle();
  await _loadAndRender('all');
  _reflowPageAfterLayout();
}

export async function openMediaDrilldown(camId) {
  state.mediaDrillOpen = true;
  state.mediaCamera = camId;
  state.mediaLabels = new Set();
  state.mediaSpecies = null;
  state.mediaPage = 0;
  if (state.mediaSelectMode) _exitMediaSelectMode();
  _clearLoadedLibrary();
  const pag = byId('mediaPagination');
  if (pag) pag.innerHTML = '';
  _seedTopMediaLabel();
  renderMediaFilterPills();
  showMediathekView('mediaDrilldown');
  _setActiveMocCard(camId);
  _updateMediaSelectToggle();
  updateMediaSectionTitle();
  await _loadAndRender('cam');
  _reflowPageAfterLayout();
}

// Fourth way into the drilldown — the "Vogelarten" species grid tile tap
// (mediathek/_species-grid.js) has already put mediaLabels/mediaSpecies
// into the state it wants, via the SAME selectSpecies()
// _species-filter.js's own pill click uses (see
// _species-grid.js::selectSpeciesFromGrid), before calling this — so
// unlike the three openers above, this one must NOT touch
// mediaLabels/mediaSpecies itself. It only does the "reveal the
// all-cameras drilldown + load" half every entrypoint here already
// shares. Reached via window.openMediaSpeciesDrilldown (orchestration.js)
// rather than a direct import: _species-grid.js stays a leaf module
// (see its own header) and cannot pull in this file's loadMedia/
// renderMediaGrid/lightbox chain.
export async function openMediaSpeciesDrilldown() {
  state.mediaDrillOpen = true;
  state.mediaCamera = null;
  state.mediaPage = 0;
  if (state.mediaSelectMode) _exitMediaSelectMode();
  _clearLoadedLibrary();
  renderMediaFilterPills();
  showMediathekView('mediaDrilldown');
  _setActiveMocCard(null);
  _updateMediaSelectToggle();
  updateMediaSectionTitle();
  await _loadAndRender('species');
  _reflowPageAfterLayout();
}

export function closeMediaDrilldown() {
  state.mediaDrillOpen = false;
  state.mediaCamera = null;
  state.mediaSpecies = null;
  state.media = [];
  if (state.mediaSelectMode) _exitMediaSelectMode();
  showMediathekView('mediaOverview');
  _setActiveMocCard(null);
  _updateMediaSelectToggle();
  updateMediaSectionTitle();
}

// ── Section title ───────────────────────────────────────────────────────────
// Library/film glyph for overview + Alle-Medien title; per-camera drilldown
// uses the camera's thematic icon via getCameraIcon (matches the cv-card).
export const _MEDIA_TITLE_SVG = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="6" width="18" height="14" rx="2"/><path d="M7 6V4h10v2"/><circle cx="12" cy="13" r="3"/></svg>`;
export function updateMediaSectionTitle() {
  const h = byId('mediaSectionTitle');
  if (!h) return;
  // Drive the title from a state flag instead of probing
  // #mediaDrilldown.style.display. The DOM probe was returning stale
  // values right after the openers flipped the inline style, leaving
  // the heading stuck on bare "Mediathek" even when a cam was selected.
  // The flag is owned by openMediaDrilldown / openAllMediaDrilldown /
  // openCategoryDrilldown / closeMediaDrilldown — see core/state.js.
  const drillOpen = !!state.mediaDrillOpen;
  if (drillOpen && state.mediaCamera) {
    const cam = (state.cameras || []).find((c) => c.id === state.mediaCamera);
    const camName = cam?.name || state.mediaCamera;
    const camIcon = getCameraIcon(camName);
    h.innerHTML = `<span class="mst-cam-icon" aria-hidden="true">${camIcon}</span><span class="mst-text">Mediathek · ${esc(camName)}</span>`;
  } else if (drillOpen) {
    h.innerHTML = `${_MEDIA_TITLE_SVG}<span class="mst-text">Mediathek · Alle Medien</span>`;
  } else {
    h.innerHTML = `${_MEDIA_TITLE_SVG}<span class="mst-text">Mediathek</span>`;
  }
}
