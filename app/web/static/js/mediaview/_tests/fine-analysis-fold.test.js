// ─── mediaview/_tests/fine-analysis-fold.test.js ───────────────────────────
// resolveFoldOpen is the pure decision behind the fold's initial open/
// closed state — split out of _isOpen (which touches localStorage) the
// same way device-tier.js splits resolveDeviceTier from getDeviceTier, so
// the RULE is testable without a localStorage/DOM stub. Table covers
// every (storage-state × per-mode default × tier) combination that
// matters, with special emphasis on proving an operator's explicit past
// choice ('0' or '1' in storage) keeps winning on BOTH tiers — the one
// thing this stage was explicitly told not to break.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveFoldOpen } from '../fine-analysis-fold.js';
import { TIER_FULL, TIER_COMPACT } from '../device-tier.js';

test('explicit "1" in storage always wins, regardless of default or tier', () => {
  for (const defaultOpen of [true, false]) {
    for (const tier of [TIER_FULL, TIER_COMPACT, undefined]) {
      assert.equal(resolveFoldOpen('1', defaultOpen, tier), true);
    }
  }
});

test('explicit "0" in storage always wins, EVEN on full tier where the new default would otherwise open it', () => {
  for (const defaultOpen of [true, false]) {
    for (const tier of [TIER_FULL, TIER_COMPACT, undefined]) {
      assert.equal(
        resolveFoldOpen('0', defaultOpen, tier),
        false,
        `raw='0' defaultOpen=${defaultOpen} tier=${tier} must stay closed`,
      );
    }
  }
});

test("never touched (raw=null) + compact tier: today's per-mode default is unchanged", () => {
  // recorded/weather-style default (closed)
  assert.equal(resolveFoldOpen(null, false, TIER_COMPACT), false);
  // live-detect-style default (open) — its own call site always passes
  // defaultOpen:true regardless of tier, so this must stay open too.
  assert.equal(resolveFoldOpen(null, true, TIER_COMPACT), true);
});

test('never touched (raw=null) + full tier: defaults OPEN even for a mode whose default is closed', () => {
  assert.equal(resolveFoldOpen(null, false, TIER_FULL), true);
  assert.equal(resolveFoldOpen(null, true, TIER_FULL), true);
});

test('never touched + no tier resolved (undefined): falls back to the caller default, same as before tier existed', () => {
  assert.equal(resolveFoldOpen(null, false, undefined), false);
  assert.equal(resolveFoldOpen(null, true, undefined), true);
});

test('a garbage tier string behaves like compact (only TIER_FULL forces open)', () => {
  assert.equal(resolveFoldOpen(null, false, 'bogus'), false);
});
