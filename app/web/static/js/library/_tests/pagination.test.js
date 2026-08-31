// ─── library/_tests/pagination.test.js ──────────────────────────────────
// The cursor state machine (`createLibraryPager`) and the "load more"
// affordance it drives (`renderLoadMoreControl`) — see _pagination.js's
// own module comment for why this shape was chosen over the existing
// page-number widgets.
import './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createLibraryPager, renderLoadMoreControl } from '../index.js';

test('a fresh pager starts with no cursor and assumes more may exist', () => {
  const pager = createLibraryPager();
  assert.equal(pager.cursor, null);
  assert.equal(pager.hasMore, true);
});

test('applyPage advances the cursor from a real next_cursor', () => {
  const pager = createLibraryPager();
  pager.applyPage({ next_cursor: 'opaque_cursor_1', items: [] });
  assert.equal(pager.cursor, 'opaque_cursor_1');
  assert.equal(pager.hasMore, true);
});

test('a next_cursor: null page ends pagination', () => {
  const pager = createLibraryPager();
  pager.applyPage({ next_cursor: 'opaque_cursor_1', items: [] });
  pager.applyPage({ next_cursor: null, items: [] });
  assert.equal(pager.cursor, null);
  assert.equal(pager.hasMore, false);
});

test('reset() forgets the cursor and re-arms hasMore', () => {
  const pager = createLibraryPager();
  pager.applyPage({ next_cursor: null, items: [] });
  assert.equal(pager.hasMore, false);
  pager.reset();
  assert.equal(pager.cursor, null);
  assert.equal(pager.hasMore, true);
});

function _fakeButtonHost() {
  const listeners = {};
  return {
    hidden: false,
    innerHTML: '',
    querySelector(sel) {
      if (sel !== '.lib-load-more') return null;
      return {
        addEventListener(evt, fn) {
          listeners[evt] = fn;
        },
      };
    },
    _fireClick() {
      listeners.click?.();
    },
  };
}

test('renderLoadMoreControl shows a button while hasMore is true', () => {
  const pager = createLibraryPager();
  const host = _fakeButtonHost();
  renderLoadMoreControl(host, pager, () => {});
  assert.equal(host.hidden, false);
  assert.match(host.innerHTML, /lib-load-more/);
});

test('renderLoadMoreControl hides the affordance once next_cursor is null', () => {
  const pager = createLibraryPager();
  pager.applyPage({ next_cursor: null, items: [] });
  const host = _fakeButtonHost();
  renderLoadMoreControl(host, pager, () => {});
  assert.equal(host.hidden, true);
  assert.equal(host.innerHTML, '');
});

test('clicking the load-more button invokes the supplied callback', () => {
  const pager = createLibraryPager();
  const host = _fakeButtonHost();
  let calls = 0;
  renderLoadMoreControl(host, pager, () => {
    calls += 1;
  });
  host._fireClick();
  assert.equal(calls, 1);
});

test('a null host is a no-op, not a throw', () => {
  assert.doesNotThrow(() => renderLoadMoreControl(null, createLibraryPager(), () => {}));
});
