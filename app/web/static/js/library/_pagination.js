// ─── library/_pagination.js ──────────────────────────────────────────────
// Stage 4 of the Mediathek + Wetter-Ereignisse merge: how the unified
// grid pages through `/api/library`.
//
// Deliberately NOT `weather/_pagination.js`'s or `mediathek/_paging.js`'s
// "Seite X von Y" widget, even though both already exist and CLAUDE.md
// says grep-before-writing. Both of those assume the FULL list is
// already in memory (`state._allMedia` / the whole filtered sightings
// array) and a page is just a client-side slice of it — that's why they
// can compute a page COUNT at all. `/api/library` is cursor-paginated on
// purpose (see `library._feed`'s module docstring: the archive is years
// deep and a page cannot be produced by reading everything and sorting),
// so there is no total count to divide by and no page N to jump to —
// only "the next item after this cursor" or "nothing more". Forcing that
// into a page-number widget would mean either fetching everything up
// front (defeats the point of a cursor) or faking a page count that lies
// the moment the underlying store changes between two page loads.
// "Load more" has no such number to fake: it only ever asks for what
// comes after the cursor it was actually handed.
//
// Split into a plain state machine (this file, fetch-free and DOM-free,
// so it is unit-testable without a `window`/`document` stub) and a tiny
// render function for the affordance itself — the same state/DOM split
// `weather/_pagination.js` already uses for its own widget.

/**
 * Cursor state for one `/api/library` view. Fetch-free: the caller
 * still owns the actual `fetch('/api/library?...')` call and hands this
 * object each page's raw response.
 */
export function createLibraryPager() {
  let cursor = null;
  let hasMore = true;
  return {
    get cursor() {
      return cursor;
    },
    get hasMore() {
      return hasMore;
    },
    /**
     * Feed one page response (`{next_cursor, ...}`) after it lands.
     * `next_cursor: null` — the server has nothing further for this
     * query (see `library._feed.list_library_items`'s own contract) —
     * flips `hasMore` false for good, until `reset()`.
     */
    applyPage(pageResult) {
      cursor = (pageResult && pageResult.next_cursor) || null;
      hasMore = cursor !== null;
    },
    /** Filters changed, or a fresh view opened: forget the running
     * cursor and start from "first page" again. */
    reset() {
      cursor = null;
      hasMore = true;
    },
  };
}

/**
 * The "Mehr laden" affordance itself. Hidden entirely once
 * `pager.hasMore` is false — there is nothing to press, so there is
 * nothing to show, matching `weather/_pagination.js`'s own
 * single-page-hides-the-strip behaviour.
 */
export function renderLoadMoreControl(host, pager, onLoadMore) {
  if (!host) return;
  if (!pager || !pager.hasMore) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  host.hidden = false;
  // `.btn.btn-action` already carries a >=44px touch target elsewhere in
  // this codebase (see storms/_helpers.js::renderDeadEnd) — reused here
  // rather than inventing a new button class for one control.
  host.innerHTML = '<button type="button" class="btn btn-action lib-load-more">Mehr laden</button>';
  host.querySelector('.lib-load-more')?.addEventListener('click', () => onLoadMore());
}
