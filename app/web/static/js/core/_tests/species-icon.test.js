// ─── core/_tests/species-icon.test.js ───────────────────────────────────────
// A species row's icon: a real silhouette from core/animal-icons.js when
// the catalogue has one, the same bird-emoji fallback
// sichtungen/_achievements.js uses when it doesn't.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { BIRD_SVGS } from '../animal-icons.js';
import {
  SPECIES_ICON_FALLBACK_EMOJI,
  speciesIconMarkup,
  speciesIconSvg,
} from '../species-icon.js';

test('a known species resolves to its real SVG', () => {
  const svg = speciesIconSvg('Elster');
  assert.equal(svg, BIRD_SVGS.elster);
  assert.match(svg, /^<svg/);
});

test('an unknown species falls back to the emoji, not null markup', () => {
  // Stockente (mallard) is outside the current top-27 catalogue.
  assert.equal(speciesIconSvg('Stockente'), null);
  const markup = speciesIconMarkup('Stockente');
  assert.match(markup, new RegExp(SPECIES_ICON_FALLBACK_EMOJI));
  assert.doesNotMatch(markup, /^<svg/);
});

test('umlaut and ASCII-transliterated spellings resolve to the same icon', () => {
  assert.equal(speciesIconSvg('Grünfink'), speciesIconSvg('Gruenfink'));
  assert.equal(speciesIconSvg('Grünfink'), BIRD_SVGS.gruenfink);
});

test('markup renders the SVG directly for a known species (no emoji)', () => {
  const markup = speciesIconMarkup('Kohlmeise');
  assert.equal(markup, BIRD_SVGS.kohlmeise);
  assert.doesNotMatch(markup, new RegExp(SPECIES_ICON_FALLBACK_EMOJI));
});

test('blank input falls back to the emoji rather than throwing', () => {
  assert.equal(speciesIconSvg(''), null);
  assert.match(speciesIconMarkup(''), new RegExp(SPECIES_ICON_FALLBACK_EMOJI));
});
