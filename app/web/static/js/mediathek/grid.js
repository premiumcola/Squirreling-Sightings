// ─── mediathek/grid.js ─────────────────────────────────────────────────────
// Stage 13 of the legacy.js → ES modules refactor — the ResizeObserver
// that re-paginates the Mediathek drilldown when the column count
// changes (window resize, sidebar collapse, orientation change). Cell
// width drives column count, column count + fixed row count drive page
// size — see calcItemsPerPage() in legacy.js for the math.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { onLongPress } from '../core/gestures.js';
import { _enterMediaSelectMode, _toggleMediaSelected } from './bulk-delete.js';

(function _initMediaGridResizeObserver() {
  const grid = byId('mediaGrid');
  if (!grid || typeof ResizeObserver === 'undefined') return;
  let lastW = 0;
  const ro = new ResizeObserver((entries) => {
    const w = entries[0]?.contentRect?.width || 0;
    if (!w || Math.abs(w - lastW) < 192) return;
    lastW = w;
    if (byId('mediaDrilldown')?.style.display === 'none') return;
    const firstCard = grid.querySelector('.media-card');
    if (!firstCard) return;
    const cardW = firstCard.getBoundingClientRect().width;
    if (cardW <= 0) return;
    const newCols = Math.max(1, Math.floor(w / cardW));
    // _lastKnownCols + _cachedPageSize + calcItemsPerPage() still live
    // in legacy.js for now; we read/write them through window so the
    // column count is shared between modules.
    if (newCols === window._lastKnownCols) return;
    window._lastKnownCols = newCols;
    if (!state._allMedia?.length) return;
    const ps = typeof window.calcItemsPerPage === 'function' ? window.calcItemsPerPage() : 24;
    window._cachedPageSize = ps;
    state.mediaTotalPages = Math.max(1, Math.ceil(state._allMedia.length / ps));
    state.mediaPage = 0;
    state.media = state._allMedia.slice(0, ps);
    if (typeof window.renderMediaGrid === 'function') window.renderMediaGrid();
    if (typeof window.renderMediaPagination === 'function') window.renderMediaPagination();
  });
  ro.observe(grid);
})();

// Long-press on a media card enters bulk-select mode and selects the
// pressed card. Already-in-bulk-mode long-presses fall through to the
// existing click-to-toggle path so behaviour stays predictable. The
// gesture lives at the grid level via event delegation so newly
// rendered cards inherit it without per-card binding.
(function _wireMediaCardLongPress() {
  const grid = byId('mediaGrid');
  if (!grid) return;
  onLongPress(grid, (evt) => {
    if (state.mediaSelectMode) return;
    const card = evt.target?.closest?.('.media-card');
    const eventId = card?.dataset?.eventId;
    if (!card || !eventId) return;
    _enterMediaSelectMode();
    _toggleMediaSelected(eventId);
  });
})();
