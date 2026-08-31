// ─── mediaview/_tests/device-tier.test.js ──────────────────────────────────
// resolveDeviceTier is pure (no DOM), so it is tested directly at a few
// representative viewport/pointer combinations — no browser stub needed.
// getDeviceTier (the live matchMedia/viewport wrapper) is NOT exercised
// here: it is a thin DOM-reading shell around this same rule, consistent
// with how this codebase splits pure arithmetic from its DOM wrapper
// (see mediaview/live-chrome-budget.js's mvChromeBudgetPx vs
// observeLiveChromeBudget).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  resolveDeviceTier,
  TIER_COMPACT,
  TIER_FULL,
  FULL_TIER_MIN_WIDTH_PX,
} from '../device-tier.js';

test('narrow + touch (iPhone SE, 375px, no hover/fine pointer) resolves compact', () => {
  assert.equal(resolveDeviceTier({ width: 375, hoverFine: false }), TIER_COMPACT);
});

test('wide + mouse (1440px desktop, hover+fine pointer) resolves full', () => {
  assert.equal(resolveDeviceTier({ width: 1440, hoverFine: true }), TIER_FULL);
});

test('edge case: wide + touch tablet (1024px iPad landscape, no hover) stays compact', () => {
  // A landscape iPad is "wide" by the same breakpoint a desktop window
  // is, but it is touch-primary — no hover affordance, no mouse
  // precision — so it must NOT get PC-only chrome just because of its
  // width. Pointer capability, not viewport size alone, decides.
  assert.equal(resolveDeviceTier({ width: 1024, hoverFine: false }), TIER_COMPACT);
});

test('edge case: the same wide tablet WITH a trackpad attached resolves full', () => {
  // iPadOS reports hover:hover + pointer:fine once an external pointer
  // is connected — at that point it genuinely has mouse-grade precision
  // and should get the same tier a desktop window does.
  assert.equal(resolveDeviceTier({ width: 1024, hoverFine: true }), TIER_FULL);
});

test('boundary width: exactly at the threshold with a mouse is full, one px under is compact', () => {
  assert.equal(resolveDeviceTier({ width: FULL_TIER_MIN_WIDTH_PX, hoverFine: true }), TIER_FULL);
  assert.equal(
    resolveDeviceTier({ width: FULL_TIER_MIN_WIDTH_PX - 1, hoverFine: true }),
    TIER_COMPACT,
  );
});

test('missing/garbage input defaults to compact rather than throwing', () => {
  assert.equal(resolveDeviceTier(), TIER_COMPACT);
  assert.equal(resolveDeviceTier({}), TIER_COMPACT);
  assert.equal(resolveDeviceTier({ width: Number.NaN, hoverFine: true }), TIER_COMPACT);
});
