// ─── identities/_tests/identities.test.js ──────────────────────────────────
// „Dort würde ich auch die Personen dann benennen und neue Gesichter
// vorhandenen Personen zuordnen. … sobald man dann etliche eingeordnet
// hat, werden die nächsten automatisch zugeordnet."
//
// Die reinen Hälften der Identitäten-Karte: was unter einem Namen steht,
// was auf einer Kachel steht, welche Kacheln eine Auswahl meint, und wann
// die Leiste einen Namen vorschlägt.

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis.window || {};
globalThis.document = globalThis.document || { getElementById: () => null };

const { personMeta, personAvatar, personsHtml, catsHtml } = await import('../_persons.js');
const { suggestLabel, selectionItems, agreedSuggestion, confidentCount, facesHtml, assignBarHtml } =
  await import('../_faces.js');

test('the line under a name counts samples and says Probe in the singular', () => {
  assert.equal(personMeta({ samples: 1 }), '1 Probe');
  assert.equal(personMeta({ samples: 12 }), '12 Proben');
  assert.equal(personMeta({ samples: 0 }), '0 Proben');
});

test('whitelist and notes join the same line, in that order', () => {
  assert.equal(
    personMeta({ samples: 3, whitelisted: true, notes: 'Nachbar' }),
    '3 Proben · Whitelist · Nachbar',
  );
});

test('a profile without a crop still has a face: its initial', () => {
  // The registry holds hashes, not pictures. A profile filed before the
  // crops were kept has nothing to show, and an empty box next to one
  // with a portrait reads as a broken image rather than as "no picture".
  assert.match(personAvatar({ name: 'anna' }), /idy-av-txt">A</);
  assert.match(personAvatar({ name: 'Anna', crops: ['/media/a.jpg'] }), /<img[^>]+\/media\/a\.jpg/);
  assert.match(personAvatar({}), /idy-av-txt">\?</);
});

test('no names yet says what to do about it, not just that there is nothing', () => {
  const html = personsHtml([]);
  assert.match(html, /Noch niemand benannt/);
  assert.match(html, /schlägt die Erkennung die nächsten von selbst vor/);
});

test('cats are only drawn when there are cats', () => {
  assert.equal(catsHtml([]), '');
  assert.match(catsHtml([{ name: 'Mimi' }]), /idy-tag">Mimi</);
});

test('a suggestion is always phrased as a question', () => {
  // It comes from an image-similarity compare, not from face recognition.
  // Stating it as fact would be the one thing the panel must not do.
  assert.equal(suggestLabel({ suggest: { name: 'Anna', confident: true } }), 'Anna?');
  assert.equal(suggestLabel({ suggest: { name: 'Anna', confident: false } }), 'Anna ?');
  assert.equal(suggestLabel({}), '');
  assert.equal(suggestLabel(null), '');
});

test('a selection is the rows it names, in grid order', () => {
  const items = [{ relpath: 'a' }, { relpath: 'b' }, { relpath: 'c' }];
  assert.deepEqual(selectionItems(items, new Set(['c', 'a'])), [
    { relpath: 'a' },
    { relpath: 'c' },
  ]);
  assert.deepEqual(selectionItems(items, new Set()), []);
});

test('the bar leads with the name every selected tile agrees on', () => {
  const agreed = agreedSuggestion([{ suggest: { name: 'Anna' } }, { suggest: { name: 'Anna' } }]);
  assert.equal(agreed, 'Anna');
  // One dissenter, or one tile with no suggestion at all, and there is
  // nothing to lead with — guessing here would be worse than not guessing.
  assert.equal(agreedSuggestion([{ suggest: { name: 'Anna' } }, { suggest: { name: 'Bo' } }]), '');
  assert.equal(agreedSuggestion([{ suggest: { name: 'Anna' } }, {}]), '');
  assert.equal(agreedSuggestion([]), '');
});

test('only the confident suggestions count towards the one-tap button', () => {
  assert.equal(
    confidentCount([
      { suggest: { name: 'Anna', confident: true } },
      { suggest: { name: 'Bo', confident: false } },
      {},
    ]),
    1,
  );
  assert.equal(confidentCount([]), 0);
});

test('an empty grid points at the sweep that fills it', () => {
  assert.match(facesHtml([], new Set()), /Gesichter suchen/);
});

test('a selected tile is marked pressed, not merely styled', () => {
  const html = facesHtml([{ relpath: 'a', url: '/media/a.jpg' }], new Set(['a']));
  assert.match(html, /aria-pressed="true"/);
  assert.match(
    facesHtml([{ relpath: 'a', url: '/media/a.jpg' }], new Set()),
    /aria-pressed="false"/,
  );
});

test('the assign bar stays away until there is something to assign', () => {
  assert.equal(assignBarHtml(0, ['Anna'], ''), '');
  const html = assignBarHtml(3, ['Bo', 'Anna'], 'Anna');
  assert.match(html, /3 ausgewählt/);
  // Agreed name first AND highlighted; the rest keep their order.
  assert.match(html, /data-name="Anna">Anna<\/button><button[^>]*data-name="Bo"/);
  assert.match(html, /idy-chip is-hint[^>]*data-name="Anna"/);
});

test('without an agreed name no chip is highlighted', () => {
  const html = assignBarHtml(2, ['Anna', 'Bo'], '');
  assert.ok(!html.includes('is-hint'));
});
