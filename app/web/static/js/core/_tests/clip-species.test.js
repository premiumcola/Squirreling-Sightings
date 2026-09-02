// ─── core/_tests/clip-species.test.js ──────────────────────────────────────
// The two pure questions asked of an event's `whole_clip` block.
//
// `subjectLabel` exists to have ONE answer to "what is this called".
// The rule was written inline in mediathek/_cards.js and was about to be
// written a second time in the player's object rows, which is the
// parallel implementation CLAUDE.md forbids. These tests pin the shared
// rule so the card and the row can never drift apart again.
//
// Every function here must answer "nothing" for an event that has no
// `whole_clip` at all — that is what keeps clips recorded before the
// aggregate existed rendering exactly as they did.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  clipSpeciesNames,
  secondarySpeciesNames,
  speciesChipText,
  subjectLabel,
} from '../clip-species.js';

// ── subjectLabel ───────────────────────────────────────────────────────

test('an identified bird is called by its species, not "Vogel"', () => {
  assert.equal(subjectLabel('bird', 'Grünfink'), 'Grünfink');
});

test('an unidentified bird keeps the German class name', () => {
  assert.equal(subjectLabel('bird', null), 'Vogel');
  assert.equal(subjectLabel('bird', ''), 'Vogel');
});

test('a species on a non-bird is ignored', () => {
  // The wildlife stage reuses `species` for its raw ImageNet label,
  // which is not a binomial. app/app/camera_runtime/_clip_tally.py
  // refuses it on the way in for the same reason; a renderer that
  // printed it anyway would undo that.
  assert.equal(subjectLabel('cat', 'tabby, tabby cat'), 'Katze');
});

test('every other class gets its German name', () => {
  assert.equal(subjectLabel('person', null), 'Person');
  assert.equal(subjectLabel('squirrel', null), 'Eichhörnchen');
});

test('an unknown class falls through to the raw token, not a blank', () => {
  assert.equal(subjectLabel('badger', null), 'badger');
});

test('no class at all returns the empty string, so callers pick the placeholder', () => {
  assert.equal(subjectLabel('', null), '');
  assert.equal(subjectLabel(undefined, null), '');
});

// ── clipSpeciesNames ───────────────────────────────────────────────────

test('an event with no whole_clip has no species, rather than throwing', () => {
  assert.deepEqual(clipSpeciesNames(null), []);
  assert.deepEqual(clipSpeciesNames({}), []);
  assert.deepEqual(clipSpeciesNames({ whole_clip: {} }), []);
  assert.deepEqual(clipSpeciesNames({ whole_clip: { species: null } }), []);
});

test('the backend order is kept — it is already best-scoring first', () => {
  const item = {
    whole_clip: {
      species: [
        { species: 'Grünfink', best_score: 0.91 },
        { species: 'Blaumeise', best_score: 0.62 },
      ],
    },
  };
  assert.deepEqual(clipSpeciesNames(item), ['Grünfink', 'Blaumeise']);
});

test('two latin binomials sharing one display name are listed once', () => {
  // SpeciesTally keys on the latin binomial, so one German name can
  // legitimately arrive twice. The card would otherwise read
  // "Grünfink · Grünfink".
  const item = {
    whole_clip: {
      species: [
        { species: 'Grünfink', species_latin: 'Chloris chloris' },
        { species: 'Grünfink', species_latin: 'Carduelis chloris' },
      ],
    },
  };
  assert.deepEqual(clipSpeciesNames(item), ['Grünfink']);
});

test('blank and non-string species rows are skipped', () => {
  const item = {
    whole_clip: {
      species: [{ species: '  ' }, { species: null }, {}, { species: 'Kohlmeise' }],
    },
  };
  assert.deepEqual(clipSpeciesNames(item), ['Kohlmeise']);
});

// ── what belongs BESIDE the headline ───────────────────────────────────

/** @param {string[]} names @param {boolean} [truncated] */
function clip(names, truncated = false) {
  return { whole_clip: { species: names.map((species) => ({ species })), truncated } };
}

test('the species already on display is not repeated next to itself', () => {
  const item = clip(['Grünfink', 'Blaumeise']);
  assert.deepEqual(secondarySpeciesNames(item, 'Grünfink'), ['Blaumeise']);
});

test('a clip with one species adds nothing at all', () => {
  // The headline already said it. A chip repeating it would be the
  // duplication the design rules forbid.
  assert.equal(speciesChipText(clip(['Grünfink']), 'Grünfink'), '');
  assert.equal(speciesChipText(clip([]), 'Katze'), '');
  assert.equal(speciesChipText({}, 'Katze'), '');
});

test('a clip with two birds names the second one', () => {
  // The operator's actual complaint, in one assertion.
  assert.equal(speciesChipText(clip(['Grünfink', 'Blaumeise']), 'Grünfink'), 'Blaumeise');
});

test('when the headline is not a bird, every species is secondary', () => {
  // A clip that fired on a cat but also held birds: the badge says
  // "Katze" and none of the species have been shown yet.
  assert.equal(speciesChipText(clip(['Grünfink', 'Blaumeise']), 'Katze'), 'Grünfink · Blaumeise');
});

test('a busy clip is bounded, and says how many it did not name', () => {
  const item = clip(['Grünfink', 'Blaumeise', 'Kohlmeise', 'Rotkehlchen', 'Buntspecht']);
  assert.equal(speciesChipText(item, 'Grünfink'), 'Blaumeise · Kohlmeise · +2');
});

test('a truncated list ends in an ellipsis rather than reading as complete', () => {
  // `truncated` means a cap refused something. The names present are
  // then a partial answer and must not be presented as the whole one.
  assert.equal(speciesChipText(clip(['Grünfink', 'Blaumeise'], true), 'Grünfink'), 'Blaumeise …');
});

test('a truncated clip with nothing left to add still stays silent', () => {
  // The headline never claimed to be a complete species list, so there
  // is nothing here to correct.
  assert.equal(speciesChipText(clip(['Grünfink'], true), 'Grünfink'), '');
});
