// ─── mediathek/_paging.js ──────────────────────────────────────────────────
// R23 split of orchestration.js — the page-slice cluster: how many tiles fit
// on a page, which slice of state._allMedia is the current page, the page
// painter, the pagination bar and the in-flight poll that re-paints it.
//
// The grid painter lives here rather than in a module of its own because
// the four entry points are mutually recursive — _goToPage → renderMediaGrid
// → renderMediaPagination, and renderMediaGrid's post-render column
// correction re-runs the page-size math and re-slices. Splitting them would
// have bought a new import cycle for no separation of concern.
//
// Not to be confused with grid.js (no underscore), which is the one-shot
// ResizeObserver bootstrapper — it only nudges the column count on window.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { loadMediaStorageStats } from '../chrome/storage-stats.js';
import { loadMedia } from './media-loader.js';
import { openLightbox } from '../lightbox.js';
import { mediaCardHTML } from './_cards.js';
import { isActivelyPending, renderProcessingQueue } from './_processing.js';
import { registerMediaItems, getRegisteredMediaItem } from './_item-registry.js';

// ── Page-size sizer ─────────────────────────────────────────────────────────
// _lastKnownCols + window._cachedPageSize are bridged on window so the
// grid.js resize observer (extracted in stage 13) can read AND write the
// same counter — without the bridge it would set its own copy and the
// re-render below would never see the update.
window._lastKnownCols ??= 0;
window._cachedPageSize ??= 0;
export const _MEDIA_ROWS = 4;
export function calcItemsPerPage() {
  const grid = byId('mediaGrid');
  let containerW = 0;
  if (grid) {
    const gr = grid.getBoundingClientRect();
    if (gr.width > 0) containerW = gr.width;
  }
  if (!containerW) {
    const isMobile = window.innerWidth <= 768;
    const mediaEl = byId('media');
    containerW = Math.max(
      193,
      mediaEl && mediaEl.clientWidth > 192
        ? mediaEl.clientWidth - 24
        : window.innerWidth - (isMobile ? 24 : 320),
    );
  }
  const GAP = 10,
    MIN_CARD = 192;
  const cols =
    window._lastKnownCols || Math.max(1, Math.floor((containerW + GAP) / (MIN_CARD + GAP)));
  return _MEDIA_ROWS * cols;
}

// ── Page slicing ────────────────────────────────────────────────────────────
// One-tick re-render. A drilldown wrapper that just transitioned from
// display:none to display:'' has no layout box until the next paint, so
// calcItemsPerPage() inside loadMedia() can read 0 from
// getBoundingClientRect and slice an empty page. setTimeout(0) yields to
// the browser, the layout settles, then we re-slice + re-render. Identical
// state → idempotent when the first render already worked, fixes the
// empty-grid race when it didn't (the user's "have to toggle a filter"
// symptom). Both drilldown openers need it, hence one helper.
export function _reflowPageAfterLayout() {
  setTimeout(() => {
    const ps = calcItemsPerPage();
    if (state._allMedia?.length) {
      window._cachedPageSize = ps;
      state.mediaTotalPages = Math.max(1, Math.ceil(state._allMedia.length / ps));
      state.mediaPage = Math.min(state.mediaPage || 0, state.mediaTotalPages - 1);
      const off = (state.mediaPage || 0) * ps;
      state.media = state._allMedia.slice(off, off + ps);
    }
    renderMediaGrid();
  }, 0);
}

// Drop one event from the loaded library and re-slice the current page,
// stepping back a page when the deletion emptied the last one. Shared by
// deleteMediaCard + deleteTLCard in _actions.js, which had this block
// character-for-character twice.
export function _dropEventAndReslice(eventId) {
  state._allMedia = (state._allMedia || []).filter((x) => x.event_id !== eventId);
  const ps_d = calcItemsPerPage();
  state.mediaTotalPages = Math.max(1, Math.ceil(state._allMedia.length / ps_d));
  state.mediaPage = Math.min(state.mediaPage || 0, state.mediaTotalPages - 1);
  state.media = state._allMedia.slice(state.mediaPage * ps_d, (state.mediaPage + 1) * ps_d);
  if (state.media.length === 0 && state.mediaPage > 0) {
    state.mediaPage--;
    state.media = state._allMedia.slice(state.mediaPage * ps_d, (state.mediaPage + 1) * ps_d);
  }
}

// ── Pagination ──────────────────────────────────────────────────────────────
export function _goToPage(n) {
  const ps = calcItemsPerPage();
  const p = Math.max(0, Math.min(state.mediaTotalPages - 1, n));
  if (p === state.mediaPage) return;
  state.mediaPage = p;
  // Re-slice from the cached all-items list — no new API call needed
  state.media = (state._allMedia || []).slice(p * ps, (p + 1) * ps);
  renderMediaGrid();
  renderMediaPagination();
}

export function renderMediaPagination() {
  const pg = byId('mediaPagination');
  if (!pg) return;
  const total = state.mediaTotalPages || 1;
  const cur = state.mediaPage || 0;
  if (total <= 1) {
    pg.innerHTML = '';
    return;
  }
  // POLISH-01a · the ‹ / › buttons carry a 44 px touch target but a
  // smaller visible chip (.page-pill-chip) so the row reads thinner.
  pg.innerHTML =
    `<button class="page-pill" ${cur === 0 ? 'disabled' : ''} onclick="_goToPage(${cur - 1})" aria-label="Vorherige Seite"><span class="page-pill-chip">‹</span></button>` +
    `<span class="page-label">Seite ${cur + 1} von ${total}</span>` +
    `<button class="page-pill" ${cur >= total - 1 ? 'disabled' : ''} onclick="_goToPage(${cur + 1})" aria-label="Nächste Seite"><span class="page-pill-chip">›</span></button>`;
}

// ── In-flight poll ──────────────────────────────────────────────────────────
let _processingPoll = null;
export function _ensureProcessingPoll() {
  // Watch the whole loaded library, not just the current page. A clip
  // that starts recording while the user is on page 2 pushes itself to
  // the top of page 1 — polling only `state.media` meant that clip
  // never refreshed and its tile stayed frozen mid-stage forever.
  // Stalled items are excluded: they stay on screen but nothing will
  // move them, so they must not hold the interval open indefinitely.
  const pending = (state._allMedia || state.media || []).some(isActivelyPending);
  if (pending && !_processingPoll) {
    _processingPoll = setInterval(async () => {
      try {
        await loadMedia();
        renderMediaGrid();
      } catch (_) {
        /* keep polling */
      }
    }, 3000);
  } else if (!pending && _processingPoll) {
    clearInterval(_processingPoll);
    _processingPoll = null;
    // A recording just finished — file landed on disk and size_mb grew.
    // Refresh overview chips + size badge to match server truth.
    loadMediaStorageStats();
  }
}

// ── Grid render ─────────────────────────────────────────────────────────────
export function renderMediaGrid() {
  const grid = byId('mediaGrid');
  if (!grid) return;
  // Unified stream: EventStore now contains motion + timelapse events, so no
  // separate tl list needs to be merged here.
  const items = state.media || [];
  // Strip first: it summarises every in-flight clip in the loaded
  // library, including the ones that fell onto another page.
  renderProcessingQueue(state._allMedia || items);
  // Light slide-in on page change
  grid.style.opacity = '0';
  grid.style.transform = 'translateX(10px)';
  grid.innerHTML =
    items.map(mediaCardHTML).join('') ||
    '<div class="item muted" style="padding:16px">Keine Medien vorhanden.</div>';
  if (state.mediaSelectMode) {
    grid.querySelectorAll('.media-card').forEach((card) => {
      if (state.mediaSelected.has(card.dataset.eventId)) card.classList.add('media-card--selected');
    });
  }
  // Lazy-paint QA pills on every visible timelapse card. Pure
  // window-level wiring — no import to keep this hot path free of
  // module-graph dependencies. paintQAPillsForGrid exists on
  // window via the import in main.js below.
  try {
    window.paintQAPillsForGrid?.();
  } catch {
    /* swallow */
  }
  requestAnimationFrame(() => {
    grid.style.transition = 'opacity .18s ease,transform .18s ease';
    grid.style.opacity = '1';
    grid.style.transform = '';
  });
  renderMediaPagination();
  // The merged library grid (library/page.js) paints its own motion
  // cards from a different item pool and registers them into the same
  // shared registry — see mediathek/_item-registry.js for why a plain
  // `items.find(...)` closure stopped being enough once a second grid
  // could be on screen at once.
  registerMediaItems(items);
  window._openMediaItem = (id) => {
    if (state.mediaSelectMode) {
      window._toggleMediaSelected(id);
      return;
    }
    const item = items.find((x) => x.event_id === id) || getRegisteredMediaItem(id);
    if (item) openLightbox(item);
  };
  // Poll for pending recording/processing items until every visible card is ready
  _ensureProcessingPoll();
  _bustBrokenThumbs(grid, items);
  _correctColumnCount(grid);
}

// Cache-bust any card whose item has a snapshot_relpath but whose <img> is
// empty or broken — covers freshly-generated thumbnails that the browser
// may have cached as 404 from an earlier render pass.
function _bustBrokenThumbs(grid, items) {
  grid.querySelectorAll('.media-card').forEach((card) => {
    const eid = card.dataset.eventId;
    if (!eid) return;
    const item = items.find((x) => x.event_id === eid);
    if (!item || !item.snapshot_relpath) return;
    const img = card.querySelector('.mmc-img-wrap img');
    if (!img) return;
    const needsBust =
      !img.getAttribute('src') || img.naturalWidth === 0 || img.style.display === 'none';
    if (needsBust) {
      img.style.display = '';
      img.src = `/media/${item.snapshot_relpath}?t=${Date.now()}`;
    }
  });
}

// Post-render column correction: measure actual card width, recompute page
// size if off.
function _correctColumnCount(grid) {
  requestAnimationFrame(() => {
    const firstCard = grid.querySelector('.media-card');
    if (!firstCard) return;
    const actualW = firstCard.getBoundingClientRect().width;
    const containerW = grid.getBoundingClientRect().width;
    if (actualW <= 0 || containerW <= 0) return;
    const actualCols = Math.max(1, Math.round(containerW / actualW));
    if (actualCols !== window._lastKnownCols) window._lastKnownCols = actualCols;
    const correctPs = _MEDIA_ROWS * actualCols;
    if (correctPs !== window._cachedPageSize && state._allMedia && state._allMedia.length) {
      window._cachedPageSize = correctPs;
      state.mediaTotalPages = Math.max(1, Math.ceil(state._allMedia.length / correctPs));
      state.mediaPage = 0;
      state.media = state._allMedia.slice(0, correctPs);
      renderMediaGrid();
      renderMediaPagination();
    }
  });
}
