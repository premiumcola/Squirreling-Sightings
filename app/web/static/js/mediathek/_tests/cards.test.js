// ─── mediathek/_tests/cards.test.js ─────────────────────────────────────
// getMediaAccentColor(labels) drives the motion-card play button's
// colour — core/primary-label.js::primaryLabel drives its badge text,
// from the SAME `item.labels` array. Regression: an event tagged
// `["motion", "person"]` (fired as generic motion, classified as a
// person afterwards — the common order once a runtime enriches an
// already-created event) used to hit `colors.motion` before ever
// reaching `person`, since the old implementation returned the FIRST
// label with any colour entry at all, "motion" included. The badge
// (via primaryLabel, which explicitly treats "motion" as the fallback,
// never a real match) read "Person" while the play button stayed grey
// right next to it — reported as "manche Personen-Videos haben einen
// grauen statt gelben Play-Button".
import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = { addEventListener() {} };
globalThis.document = { getElementById: () => null };

const { getMediaAccentColor } = await import('../_cards.js');

test('a real object label wins over "motion" regardless of array order', () => {
  assert.equal(getMediaAccentColor(['motion', 'person']), getMediaAccentColor(['person']));
  assert.equal(getMediaAccentColor(['person', 'motion']), getMediaAccentColor(['person']));
});

test('a pure motion event with no object label still gets the motion colour', () => {
  assert.equal(getMediaAccentColor(['motion']), getMediaAccentColor([]));
});

test('a non-motion pseudo-label (e.g. the synthetic timelapse lookup) is unaffected', () => {
  assert.notEqual(getMediaAccentColor(['timelapse']), getMediaAccentColor(['motion']));
});

test('an empty or missing labels array falls back to the motion colour', () => {
  assert.equal(getMediaAccentColor([]), getMediaAccentColor(undefined));
});
