// ─── core/_tests/fold.test.js ──────────────────────────────────────────────
// The reason this module exists: PER-KEY state. The fold it was
// extracted from hardcoded one storage key, which was right while there
// was one fold. The player has three independent ones, and three copies
// of a single-key fold would have given all three a shared open state —
// opening the debug log would have opened the recording details too.
//
// resolveFoldOpen's own three-state rule is covered from its previous
// home in mediaview/_tests/fine-analysis-fold.test.js, which still
// passes unedited against this implementation. What is added here is
// the key independence and the storage-failure behaviour.

import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { isFoldOpen, resolveFoldOpen, saveFoldOpen } from '../fold.js';

/** Minimal Map-backed localStorage; node has none by default. */
function stubStorage() {
  const map = new Map();
  globalThis.localStorage = {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
  };
  return map;
}

/** A storage that throws on every access, the way private mode does. */
function hostileStorage() {
  globalThis.localStorage = {
    getItem() {
      throw new Error('SecurityError');
    },
    setItem() {
      throw new Error('QuotaExceededError');
    },
  };
}

beforeEach(() => {
  stubStorage();
});

test('two folds with different keys hold independent open state', () => {
  saveFoldOpen('fold.a', true);
  saveFoldOpen('fold.b', false);
  assert.equal(isFoldOpen('fold.a', false), true);
  assert.equal(isFoldOpen('fold.b', true), false);

  // Flipping one must not disturb the other.
  saveFoldOpen('fold.a', false);
  assert.equal(isFoldOpen('fold.a', true), false);
  assert.equal(isFoldOpen('fold.b', true), false);
});

test('three folds, as the player has, stay independent', () => {
  const keys = ['vp.details', 'vp.raw', 'vp.debug'];
  for (const k of keys) saveFoldOpen(k, false);
  saveFoldOpen('vp.debug', true);
  assert.deepEqual(
    keys.map((k) => isFoldOpen(k, false)),
    [false, false, true],
  );
});

test('an untouched key falls back to the caller default', () => {
  assert.equal(isFoldOpen('never.seen', true), true);
  assert.equal(isFoldOpen('never.seen', false), false);
});

test('a closed fold is persisted as an explicit 0, not as an absent key', () => {
  // Removing the key instead would let a default-open mode reopen a
  // fold the operator deliberately closed.
  const map = stubStorage();
  saveFoldOpen('fold.a', false);
  assert.equal(map.get('fold.a'), '0');
  assert.equal(isFoldOpen('fold.a', true), false);
});

test('an explicit choice outranks the device tier in both directions', () => {
  saveFoldOpen('fold.a', false);
  assert.equal(isFoldOpen('fold.a', true, 'full'), false, 'full tier must not reopen it');
  saveFoldOpen('fold.b', true);
  assert.equal(isFoldOpen('fold.b', false, 'compact'), true);
});

test('storage that throws degrades to the default instead of breaking', () => {
  hostileStorage();
  assert.equal(isFoldOpen('fold.a', true), true);
  assert.equal(isFoldOpen('fold.a', false), false);
  assert.doesNotThrow(() => saveFoldOpen('fold.a', true));
});

test('the pure rule is reachable from the new home', () => {
  assert.equal(resolveFoldOpen('1', false, 'compact'), true);
  assert.equal(resolveFoldOpen('0', true, 'full'), false);
  assert.equal(resolveFoldOpen(null, false, 'full'), true);
  assert.equal(resolveFoldOpen(null, false, undefined), false);
});
