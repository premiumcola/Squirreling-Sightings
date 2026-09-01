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
import { calcColumnsForWidth, calcGridPageSize, GRID_PAGE_ROWS } from '../grid-page-size.js';

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
