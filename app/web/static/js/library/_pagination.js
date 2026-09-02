// ─── library/_pagination.js ──────────────────────────────────────────────
// Stage 11 of the Mediathek + Wetter-Ereignisse merge: how the unified
// grid pages through `/api/library` — page-numbered "Seite N von M",
// visually identical to `mediathek/_paging.js`'s own widget
// (`.page-pill`/`.page-label`/`.page-pill-chip`, reused unchanged), per
// the operator's explicit "genau wie bei den Kameras" ask.
//
// `/api/library` is still cursor-paginated SERVER-SIDE (the archive is
// years deep — see `library._feed`'s own module docstring for why a
// page can't be produced by reading everything and sorting) — that
// hasn't changed and shouldn't. What changed is the CLIENT no longer
// treats "no total count" as a reason to avoid page numbers entirely:
// `GET /api/library/facets` (Stage 10, `_filter-bar.js`) already computes
// the full matching-set size for the filter bar's own chip counts, and
// this widget reuses that SAME `total` (no second request) to derive
// "von M" as `Math.ceil(total / pageSize)`. That derived page count is
// an APPROXIMATION, not a guarantee — it can drift by one page if the
// underlying store gains or loses matching items between the facets
// fetch and a later page load, the same limitation every real
// paginated UI with a live-but-not-transactionally-consistent count
// has (a search engine's "about N results" is the same kind of
// estimate). Prev/next themselves stay exact regardless: they are
// driven by the cursor stack (`_cursor-stack.js`), not by the
// approximate count — a stale `total` can only make the page LABEL
// read "3 von 5" when it's actually the last page, never make ‹/›
// jump to a page that does not exist.
export { createLibraryCursorStack, libraryPageItems } from './_cursor-stack.js';

/**
 * Paint the "Seite N von M" widget + wire ‹/› — hidden entirely (empty
 * `host.innerHTML`) once there is only one page AND neither direction
 * has anywhere to go, matching `mediathek/_paging.js::renderMediaPagination`'s
 * own single-page-hides-the-strip behaviour. `total`/`pageSize` derive
 * "von M"; `cursorStack` (see that module) is the source of truth for
 * whether ‹/› themselves are enabled and for "Seite N". `onGoTo` is
 * called with `'back'` or `'next'` — this module never fetches, same
 * split `_cursor-stack.js`'s own pure/DOM boundary already draws.
 */
export function renderLibraryPagination(host, cursorStack, total, pageSize, onGoTo) {
  if (!host) return;
  // The cursor stack's own canGoBack/canGoNext are EXACT (driven by the
  // server's real `next_cursor`) — hiding on those alone, rather than
  // also gating on the approximate `total`, means a `total` that hasn't
  // loaded yet (or has drifted) can never wrongly hide a widget that
  // genuinely has somewhere to go, or show one that doesn't.
  if (!cursorStack.canGoBack && !cursorStack.canGoNext) {
    host.innerHTML = '';
    return;
  }
  const totalPages = pageSize > 0 ? Math.max(1, Math.ceil(total / pageSize)) : 1;
  // POLISH-01a · the ‹ / › buttons carry a 44 px touch target but a
  // smaller visible chip (.page-pill-chip) so the row reads thinner —
  // identical markup to mediathek/_paging.js::renderMediaPagination.
  host.innerHTML =
    `<button type="button" class="page-pill" ${cursorStack.canGoBack ? '' : 'disabled'} aria-label="Vorherige Seite"><span class="page-pill-chip">‹</span></button>` +
    `<span class="page-label">Seite ${cursorStack.pageIndex} von ${totalPages}</span>` +
    `<button type="button" class="page-pill" ${cursorStack.canGoNext ? '' : 'disabled'} aria-label="Nächste Seite"><span class="page-pill-chip">›</span></button>`;
  const buttons = host.querySelectorAll('.page-pill');
  buttons.forEach((btn, i) => {
    btn.addEventListener('click', () => onGoTo(i === 0 ? 'back' : 'next'));
  });
}
