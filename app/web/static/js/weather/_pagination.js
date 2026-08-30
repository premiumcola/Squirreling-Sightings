// ─── weather/_pagination.js ─────────────────────────────────────────────
// Page-size + pagination-control for the unified Wetter-Ereignisse grid.
// Split out of sightings.js when that file crossed the JS line ceiling —
// this is a self-contained "how many cards fit, and how does the user
// move between pages" concern, independent of what kind of record any
// given card is.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';

// Viewport-aware page size: tight on phones (4 = 2×2 mosaic that
// matches the .ws-grid 2-col mobile layout), comfortable on tablets,
// 3×3 on desktop so the pagination control stays in view on a
// 1080 p screen without scrolling. Recomputed on every render so a
// window resize adjusts the page count without a reload.
export function weatherPageSize() {
  const w = window.innerWidth || 1200;
  if (w <= 768) return 4;
  if (w <= 1180) return 8;
  return 9;
}

// Pagination strip underneath the grid. Copied 1:1 from the Mediathek
// renderMediaPagination() recipe (mediathek/orchestration.js): a prev
// chip, a "Seite X von Y" label, and a next chip — no numbered pill row
// (it got ugly with many pages). The container
// (#weatherSightingsPagination) already carries `media-pagination` so
// the `.page-pill` / `.page-pill-chip` / `.page-label` styling is shared
// with the Library. Wiring is unchanged: prev/next move
// state.weather.page, re-render the grid, and scroll it back into view;
// the strip stays hidden for single-page lists. `onPageChange` is the
// grid's own re-render (sightings.js::_renderWeatherGrid) — injected so
// this module never has to import the grid renderer back.
export function renderWeatherPagination(totalItems, pageSize, onPageChange) {
  const pag = byId('weatherSightingsPagination');
  if (!pag) return;
  if (!totalItems || totalItems <= pageSize) {
    pag.hidden = true;
    pag.innerHTML = '';
    return;
  }
  pag.hidden = false;
  const pageCount = Math.max(1, Math.ceil(totalItems / pageSize));
  const cur = Number.isInteger(state.weather.page) ? state.weather.page : 0;
  pag.innerHTML =
    `<button type="button" class="page-pill" data-act="prev" ${cur === 0 ? 'disabled' : ''} aria-label="Vorherige Seite"><span class="page-pill-chip">‹</span></button>` +
    `<span class="page-label">Seite ${cur + 1} von ${pageCount}</span>` +
    `<button type="button" class="page-pill" data-act="next" ${cur >= pageCount - 1 ? 'disabled' : ''} aria-label="Nächste Seite"><span class="page-pill-chip">›</span></button>`;
  pag.querySelectorAll('button').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      let next = state.weather.page || 0;
      if (btn.dataset.act === 'prev') next = Math.max(0, next - 1);
      else if (btn.dataset.act === 'next') next = Math.min(pageCount - 1, next + 1);
      if (next === state.weather.page) return;
      state.weather.page = next;
      onPageChange();
      // Scroll the grid back into view so the user sees the new page,
      // not whatever scroll position the strip was at.
      byId('weatherSightingsGrid')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}
