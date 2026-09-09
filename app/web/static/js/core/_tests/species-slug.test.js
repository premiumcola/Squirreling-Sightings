// ─── core/_tests/species-slug.test.js ───────────────────────────────────────
// Pins the transliteration rule against app/app/species_unlock.py's
// `_SPECIES_TO_ACH_ID` two-key-per-species pattern (German name +
// ASCII transliteration → the same id) so the two never silently drift.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { speciesSlug } from '../species-slug.js';

test('a plain name lowercases with no umlauts to transliterate', () => {
  assert.equal(speciesSlug('Elster'), 'elster');
  assert.equal(speciesSlug('Amsel'), 'amsel');
});

test('ä, ö, ü, ß transliterate to ae, oe, ue, ss', () => {
  assert.equal(speciesSlug('Grünfink'), 'gruenfink');
  assert.equal(speciesSlug('Rabenkrähe'), 'rabenkraehe');
  assert.equal(speciesSlug('Eichhörnchen'), 'eichhoernchen');
});

test('the umlaut spelling and the ASCII spelling of one species agree', () => {
  // Mirrors _SPECIES_TO_ACH_ID's own two-key pattern, e.g.
  // "grünfink"/"gruenfink" both mapping to "gruenfink".
  assert.equal(speciesSlug('Grünfink'), speciesSlug('Gruenfink'));
  assert.equal(speciesSlug('Rabenkrähe'), speciesSlug('Rabenkraehe'));
});

test('surrounding whitespace is trimmed', () => {
  assert.equal(speciesSlug('  Elster  '), 'elster');
});

test('blank or non-string input returns the empty string, not a throw', () => {
  assert.equal(speciesSlug(''), '');
  assert.equal(speciesSlug('   '), '');
  assert.equal(speciesSlug(null), '');
  assert.equal(speciesSlug(undefined), '');
});
