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

const { getMediaAccentColor, mediaCardHTML } = await import('../_cards.js');

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

// ── the species chip beside the headline ───────────────────────────────
//
// The headline badge names ONE species — `pick_headline_species` ranks
// rarest-first and other things depend on that staying one name. What a
// clip holding several birds gets is a second, quieter line naming the
// rest. A clip holding one gets nothing extra at all, so the whole
// existing archive looks exactly as it did.

/** @param {string[]} names @param {boolean} [truncated] */
function clipWith(names, truncated = false) {
  return { whole_clip: { species: names.map((species) => ({ species })), truncated } };
}

const BIRD_CARD = {
  event_id: 'e1',
  camera_id: 'c1',
  labels: ['bird'],
  bird_species: 'Grünfink',
  video_relpath: 'x.mp4',
};

test('a clip with one species grows no extra chip', () => {
  const html = mediaCardHTML({ ...BIRD_CARD, ...clipWith(['Grünfink']) });
  assert.ok(html.includes('Grünfink'), 'the headline itself must still be there');
  assert.ok(!html.includes('mmc-species-more'));
});

test('an event with no whole_clip at all grows no extra chip', () => {
  // Every clip recorded before the aggregate existed.
  assert.ok(!mediaCardHTML(BIRD_CARD).includes('mmc-species-more'));
});

test('a clip with two birds names the second one beside the headline', () => {
  const html = mediaCardHTML({ ...BIRD_CARD, ...clipWith(['Grünfink', 'Blaumeise']) });
  assert.ok(html.includes('mmc-species-more'));
  assert.ok(html.includes('Blaumeise'));
  // and the headline is still the single ranked name, not a list
  assert.equal(html.split('Grünfink').length - 1, 1);
});

test('the chip escapes what it prints', () => {
  const html = mediaCardHTML({ ...BIRD_CARD, ...clipWith(['Grünfink', '<img src=x>']) });
  assert.ok(!html.includes('<img src=x>'));
  assert.ok(html.includes('&lt;img'));
});

test('a truncated species list says so on the card too', () => {
  const html = mediaCardHTML({ ...BIRD_CARD, ...clipWith(['Grünfink', 'Blaumeise'], true) });
  assert.ok(html.includes('Blaumeise …'));
});

test('the badge stack is one positioned element, not two competing ones', () => {
  // .mmc-actions sits at the same top offset on the right; the stack
  // owns the left side and passes clicks through to the card wrap.
  const html = mediaCardHTML({ ...BIRD_CARD, ...clipWith(['Grünfink', 'Blaumeise']) });
  assert.equal(html.split('mmc-badges').length - 1, 1);
});
