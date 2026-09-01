// ─── library/_tests/pagination.test.js ──────────────────────────────────
// Stage 11: the cursor-stack state machine (`createLibraryCursorStack`,
// `_cursor-stack.js`) and the "Seite N von M" widget it drives
// (`renderLibraryPagination`, `_pagination.js`) — see those modules'
// own headers for why prev/next needs a client-held cursor HISTORY
// (`/api/library` only ever hands back "the cursor for the page after
// this one") and why `total`/`pageSize` only approximate a page count
// rather than being authoritative.
import './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createLibraryCursorStack, renderLibraryPagination } from '../index.js';

// ── createLibraryCursorStack ─────────────────────────────────────────────

test('a fresh stack starts on page 1, cursor null, nowhere to go', () => {
  const stack = createLibraryCursorStack();
  assert.equal(stack.current, null);
  assert.equal(stack.pageIndex, 1);
  assert.equal(stack.canGoBack, false);
  assert.equal(stack.canGoNext, false);
});

test('applyPage with a real next_cursor makes canGoNext true', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  assert.equal(stack.canGoNext, true);
});

test('applyPage with next_cursor: null means no further page', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: null });
  assert.equal(stack.canGoNext, false);
});

test('advance() with no known next page is a no-op, returns undefined', () => {
  const stack = createLibraryCursorStack();
  const result = stack.advance();
  assert.equal(result, undefined);
  assert.equal(stack.pageIndex, 1);
});

test('advance() pushes the current cursor and returns the next one', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  const cursor = stack.advance();
  assert.equal(cursor, 'cur_page2');
  assert.equal(stack.current, 'cur_page2');
  assert.equal(stack.pageIndex, 2);
  assert.equal(stack.canGoBack, true);
});

test('back() on page 1 (empty stack) is a no-op, returns undefined', () => {
  const stack = createLibraryCursorStack();
  const result = stack.back();
  assert.equal(result, undefined);
  assert.equal(stack.pageIndex, 1);
});

test('advance then back returns to page 1 with cursor null — "from scratch"', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  stack.advance();
  const cursor = stack.back();
  assert.equal(cursor, null);
  assert.equal(stack.current, null);
  assert.equal(stack.pageIndex, 1);
  assert.equal(stack.canGoBack, false);
});

test('a three-page walk forward then all the way back replays every cursor exactly', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  assert.equal(stack.advance(), 'cur_page2');
  stack.applyPage({ next_cursor: 'cur_page3' });
  assert.equal(stack.advance(), 'cur_page3');
  assert.equal(stack.pageIndex, 3);

  assert.equal(stack.back(), 'cur_page2');
  assert.equal(stack.pageIndex, 2);
  assert.equal(stack.back(), null);
  assert.equal(stack.pageIndex, 1);
  assert.equal(stack.canGoBack, false);
});

test('applyPage after going back re-establishes canGoNext for that page', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  stack.advance();
  stack.back();
  // Re-fetching page 1 lands the SAME next_cursor it had the first time.
  stack.applyPage({ next_cursor: 'cur_page2' });
  assert.equal(stack.canGoNext, true);
  assert.equal(stack.advance(), 'cur_page2');
});

test('reset() forgets the whole history and returns to page 1', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  stack.advance();
  stack.reset();
  assert.equal(stack.current, null);
  assert.equal(stack.pageIndex, 1);
  assert.equal(stack.canGoBack, false);
  assert.equal(stack.canGoNext, false);
});

// ── renderLibraryPagination ──────────────────────────────────────────────

// `renderLibraryPagination` always emits exactly two `.page-pill`
// buttons (‹ then ›) whenever it renders anything at all — the fake
// host's `querySelectorAll` hands back two fixed fake elements rather
// than parsing `innerHTML`, the same "don't reimplement a DOM parser"
// shortcut `library/_tests/pagination.test.js`'s own predecessor took
// for its single "Mehr laden" button.
function _fakePaginationHost() {
  const buttons = [{ _click: null }, { _click: null }];
  buttons.forEach((b) => {
    b.addEventListener = (evt, fn) => {
      b._click = fn;
    };
  });
  return {
    innerHTML: '',
    querySelectorAll(sel) {
      return sel === '.page-pill' ? buttons : [];
    },
    _click(i) {
      buttons[i]?._click?.();
    },
  };
}

test('a stack with nowhere to go renders an empty widget', () => {
  const stack = createLibraryCursorStack();
  const host = _fakePaginationHost();
  renderLibraryPagination(host, stack, 0, 24, () => {});
  assert.equal(host.innerHTML, '');
});

test('"Seite N von M" reflects pageIndex and Math.ceil(total/pageSize)', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  const host = _fakePaginationHost();
  renderLibraryPagination(host, stack, 100, 24, () => {});
  assert.match(host.innerHTML, /Seite 1 von 5/);
});

test('the back button is disabled on page 1', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  const host = _fakePaginationHost();
  renderLibraryPagination(host, stack, 50, 24, () => {});
  const firstButton = host.innerHTML.slice(0, host.innerHTML.indexOf('</button>'));
  assert.match(firstButton, /disabled/);
});

test('the next button is disabled once there is no further page', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  stack.advance();
  stack.applyPage({ next_cursor: null });
  const host = _fakePaginationHost();
  renderLibraryPagination(host, stack, 48, 24, () => {});
  const lastButton = host.innerHTML.slice(host.innerHTML.lastIndexOf('<button'));
  assert.match(lastButton, /disabled/);
});

test('clicking next invokes onGoTo("next")', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  const host = _fakePaginationHost();
  const calls = [];
  renderLibraryPagination(host, stack, 100, 24, (dir) => calls.push(dir));
  host._click(1);
  assert.deepEqual(calls, ['next']);
});

test('clicking back invokes onGoTo("back")', () => {
  const stack = createLibraryCursorStack();
  stack.applyPage({ next_cursor: 'cur_page2' });
  stack.advance();
  const host = _fakePaginationHost();
  const calls = [];
  renderLibraryPagination(host, stack, 100, 24, (dir) => calls.push(dir));
  host._click(0);
  assert.deepEqual(calls, ['back']);
});

test('a null host is a no-op, not a throw', () => {
  assert.doesNotThrow(() =>
    renderLibraryPagination(null, createLibraryCursorStack(), 10, 24, () => {}),
  );
});
