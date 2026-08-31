// ─── mediathek/_drilldown.js ───────────────────────────────────────────────
// R23 split of orchestration.js — Level 2 of the Mediathek: the three ways
// into the filtered grid (one camera / all cameras / one category) and the
// way back out. Each opener owns the same sequence — reset filter state,
// swap the two wrappers, load, prune dead pills, render — so they live
// together and share _reflowPageAfterLayout() from _paging.js.
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

const _LOADING_HTML =
  '<div style="padding:32px;text-align:center;color:var(--muted)">Lade Medien…</div>';

// Swap overview → drilldown and bring the select-mode toggle + heading in
// line with the state the caller just wrote.
function _showDrilldown() {
  byId('mediaOverview').style.display = 'none';
  byId('mediaDrilldown').style.display = '';
  _updateMediaSelectToggle();
  updateMediaSectionTitle();
}

// Always render — even if loadMedia throws, the "Keine Medien
// vorhanden." fallback is a far better UX than a frozen "Lade
// Medien…" placeholder. _pruneEmptyMediaFilters then drops any
// pre-seeded label that ended up with zero matches so the pill bar
// doesn't show stale highlights.
async function _loadAndRender(what) {
  try {
    await loadMedia();
  } catch (err) {
    console.warn(`[mediathek] loadMedia (${what}) failed:`, err);
  }
  _pruneEmptyMediaFilters();
  renderMediaFilterPills('drilldown');
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
  state.mediaPage = 0;
  if (state.mediaSelectMode) _exitMediaSelectMode();
  if (state.mediaLabels.size === 0) _seedTopMediaLabel();
  renderMediaFilterPills('drilldown');
  _showDrilldown();
  await _loadAndRender('category');
}

export async function openAllMediaDrilldown(preFilterLabel) {
  state.mediaDrillOpen = true;
  state.mediaCamera = null;
  state.mediaLabels = preFilterLabel ? new Set([preFilterLabel]) : new Set();
  state.mediaPage = 0;
  if (state.mediaSelectMode) _exitMediaSelectMode();
  _clearLoadedLibrary();
  if (state.mediaLabels.size === 0) _seedTopMediaLabel();
  renderMediaFilterPills('drilldown');
  byId('mediaOverview').style.display = 'none';
  byId('mediaDrilldown').style.display = '';
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
  state.mediaPage = 0;
  if (state.mediaSelectMode) _exitMediaSelectMode();
  _clearLoadedLibrary();
  const pag = byId('mediaPagination');
  if (pag) pag.innerHTML = '';
  _seedTopMediaLabel();
  renderMediaFilterPills('drilldown');
  byId('mediaOverview').style.display = 'none';
  byId('mediaDrilldown').style.display = '';
  _setActiveMocCard(camId);
  _updateMediaSelectToggle();
  updateMediaSectionTitle();
  await _loadAndRender('cam');
  _reflowPageAfterLayout();
}

export function closeMediaDrilldown() {
  state.mediaDrillOpen = false;
  state.mediaCamera = null;
  state.media = [];
  if (state.mediaSelectMode) _exitMediaSelectMode();
  byId('mediaDrilldown').style.display = 'none';
  byId('mediaOverview').style.display = '';
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
