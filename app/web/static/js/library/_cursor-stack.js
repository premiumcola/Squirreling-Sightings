// ─── library/_cursor-stack.js ───────────────────────────────────────────
// Stage 11 of the Mediathek + Wetter-Ereignisse merge: the pure prev/next
// state machine behind the merged grid's page-numbered pagination — see
// `_pagination.js`'s own header for why `/api/library`'s cursor
// (opaque, server-side, no total-count contract of its own) is driven
// through a page-number WIDGET now instead of a "Mehr laden" accumulate.
//
// `/api/library` only ever hands back "the cursor for whatever comes
// after THIS page" (`next_cursor`) — there is no "cursor for the page
// before this one". Going back therefore needs its own memory: this
// keeps a client-held STACK of the cursors used to reach every page
// behind the current one. Page 1's own cursor is `null` (no `before`
// param at all) — pushed onto the stack like any other page's, which is
// what makes "pop all the way back to page 1" fall out of the same
// `stack.pop()` call as every other back-step, no special case needed.
//
// A cursor value of `null` is a MEANINGFUL, valid result ("fetch page 1,
// no `before` param"), so "cannot advance/go back" is signalled with
// `undefined` instead — the two are deliberately never conflated.
export function createLibraryCursorStack() {
  let stack = []; // cursors that fetched every page BEHIND the current one
  let current = null; // the `before` param that fetched the CURRENT page
  let nextCursor = null; // this page's own `next_cursor`, once known
  let pageIndex = 1;

  return {
    get current() {
      return current;
    },
    get pageIndex() {
      return pageIndex;
    },
    get canGoBack() {
      return stack.length > 0;
    },
    get canGoNext() {
      return nextCursor !== null;
    },
    /** Feed the just-loaded page's raw `/api/library` response — records
     * whether a next page exists, for `canGoNext`/`advance()`. */
    applyPage(pageResult) {
      nextCursor = (pageResult && pageResult.next_cursor) || null;
    },
    /** Advance to the next page: pushes the CURRENT cursor onto the
     * stack and returns the cursor to re-fetch with (this page's own
     * `next_cursor`) — `undefined`, with no state change, when there is
     * no next page. The caller re-fetches with the returned value as
     * `before` and REPLACES its item list, then calls `applyPage` on
     * the fresh response. */
    advance() {
      if (nextCursor === null) return undefined;
      stack.push(current);
      current = nextCursor;
      pageIndex += 1;
      return current;
    },
    /** Go back one page: pops the stack and returns the cursor to
     * re-fetch with — `null` once popped all the way back to page 1
     * (the value page 1 was originally pushed with), `undefined` with
     * no state change when already on page 1 (nothing to pop). */
    back() {
      if (!stack.length) return undefined;
      current = stack.pop();
      pageIndex -= 1;
      return current;
    },
    /** Filters changed, or a fresh view opened: forget the whole
     * history and start from page 1 again. */
    reset() {
      stack = [];
      current = null;
      nextCursor = null;
      pageIndex = 1;
    },
  };
}
