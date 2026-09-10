// ─── core/_tests/grid-page-size.test.js ─────────────────────────────────
// The shared "rows × responsive columns" page-size math both
// mediathek/_paging.js's camera drilldown and library/_pagination.js's
// merged grid page by — see grid-page-size.js's own header for why it
// lives here instead of in either feature package. Every test below
// hands `calcGridPageSize` a container with a real measured width, so
// the `fallbackContainerWidth()` branch (the only part of this module
// that touches `document`/`window`) is never exercised — this repo's
// plain-node test harness has no DOM to give it one.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  calcColumnsForWidth,
  calcGridPageSize,
  gridMetrics,
  measuredColumns,
  GRID_PAGE_ROWS,
} from '../grid-page-size.js';

function _fakeGrid(width) {
  return { getBoundingClientRect: () => ({ width }) };
}

// ── calcColumnsForWidth ──────────────────────────────────────────────

test('a single-card-wide container fits exactly one column', () => {
  assert.equal(calcColumnsForWidth(192), 1);
});

test('two cards plus the gap between them fit two columns', () => {
  assert.equal(calcColumnsForWidth(192 * 2 + 10), 2);
});

test('a width that only just falls short of a third column stays at two', () => {
  assert.equal(calcColumnsForWidth(192 * 3 + 10 * 2 - 1), 2);
});

test('a zero or negative width never produces fewer than one column', () => {
  assert.equal(calcColumnsForWidth(0), 1);
  assert.equal(calcColumnsForWidth(-50), 1);
});

// ── calcGridPageSize ─────────────────────────────────────────────────

test('page size is GRID_PAGE_ROWS x the measured column count by default', () => {
  const size = calcGridPageSize(_fakeGrid(192 * 3 + 10 * 2));
  assert.equal(size, GRID_PAGE_ROWS * 3);
});

test('a custom row count overrides GRID_PAGE_ROWS', () => {
  const size = calcGridPageSize(_fakeGrid(192), { rows: 2 });
  assert.equal(size, 2);
});

test('lastKnownCols wins over a fresh measurement when given', () => {
  const size = calcGridPageSize(_fakeGrid(192 * 5), { lastKnownCols: 1 });
  assert.equal(size, GRID_PAGE_ROWS * 1);
});

test('a container reporting zero width falls through to lastKnownCols, not a zero page size', () => {
  const size = calcGridPageSize(_fakeGrid(0), { lastKnownCols: 2 });
  assert.equal(size, GRID_PAGE_ROWS * 2);
});

// ── ask the layout, don't predict it ─────────────────────────────────────
//
// A page of four cards on a phone is what predicting cost: the CSS
// narrows `.media-grid`'s cards twice on the way down to a 393 px screen
// (192 → 160 → 140 px) and this module knew about neither breakpoint, so
// it paged by ONE column while the browser drew two — „jetzt grade sind
// hier nur zwei Zeilen, das ist zu wenig".

test('the browser’s own track list wins over any width arithmetic', () => {
  const grid = { ..._fakeGrid(370) };
  globalThis.getComputedStyle = () => ({ gridTemplateColumns: '181.5px 181.5px' });
  try {
    assert.equal(calcGridPageSize(grid), GRID_PAGE_ROWS * 2);
  } finally {
    delete globalThis.getComputedStyle;
  }
});

test('a grid that has not painted reports no columns to read', () => {
  globalThis.getComputedStyle = () => ({ gridTemplateColumns: 'none' });
  try {
    assert.equal(measuredColumns(_fakeGrid(370)), 0);
  } finally {
    delete globalThis.getComputedStyle;
  }
  assert.equal(measuredColumns(null), 0);
  // No getComputedStyle at all — this repo's node harness — reads as 0
  // rather than throwing, so the width math stays the fallback.
  assert.equal(measuredColumns(_fakeGrid(370)), 0);
});

test('the fallback knows the same breakpoints the stylesheets do', () => {
  assert.deepEqual(gridMetrics(1440), { card: 192, gap: 10 });
  // 03-dashboard.css drops to 160 px below 768…
  assert.deepEqual(gridMetrics(600), { card: 160, gap: 8 });
  // …and 25-mobile.css to 140 px below 400, which is where both an
  // iPhone SE (375) and an iPhone 14 (393) land.
  assert.deepEqual(gridMetrics(393), { card: 140, gap: 8 });
  assert.deepEqual(gridMetrics(375), { card: 140, gap: 8 });
  // An unknown viewport falls back to the desktop pair rather than
  // guessing narrow — a too-large page is a scroll, a too-small one is
  // the bug being fixed.
  assert.deepEqual(gridMetrics(0), { card: 192, gap: 10 });
});

test('a 393 px phone fits two columns, not one', () => {
  // ~370 px of grid inside a 393 px screen. With the desktop pair that
  // is one column and a two-row page; with the phone's own it is two.
  assert.equal(calcColumnsForWidth(370), 1);
  assert.equal(calcColumnsForWidth(370, gridMetrics(393)), 2);
});
