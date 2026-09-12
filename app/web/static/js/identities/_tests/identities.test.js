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

const { personMeta, personAvatar, personsHtml, catsHtml, qualityLine, regionRows, regionsHtml } =
  await import('../_persons.js');
const {
  suggestLabel,
  selectionItems,
  agreedSuggestion,
  confidentCount,
  facesHtml,
  assignBarHtml,
  isKnownReject,
  knownRejectCount,
} = await import('../_faces.js');

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

// ── bekannt, ohne Namen ────────────────────────────────────────────────

test('a profile without a name says so in its own line', () => {
  assert.equal(personMeta({ samples: 4, anonymous: true }), '4 Proben · ohne Namen');
});

test('the bar always offers the nameless option', () => {
  assert.match(assignBarHtml(1, [], ''), /data-idy="assign-anon"/);
});

// ── wie gut das Profil schon ist ───────────────────────────────────────

test('no measurement at all shows nothing rather than a zero', () => {
  assert.equal(qualityLine(undefined), null);
  assert.equal(qualityLine(null), null);
});

test('a profile that could not be measured says what to do about it', () => {
  // Eine erfundene 0 % sähe aus wie ein schlechtes Profil statt wie ein
  // ungeprüftes — das ist der Unterschied, den diese Zeile trägt.
  const q = qualityLine({ state: 'zu-wenig', events: 1 });
  assert.equal(q.pct, null);
  assert.match(q.text, /noch nicht messbar/);
  assert.match(q.hint, /zweiten Auftritt/);
});

test('a measured profile reports the count, not only the percentage', () => {
  const q = qualityLine({ state: 'gemessen', rate: 0.778, hits: 7, checked: 9, confused: 0 });
  assert.equal(q.pct, 78);
  assert.equal(q.text, '7 von 9 wiedererkannt');
});

test('confusions are named, because they are the other half of the question', () => {
  const q = qualityLine({ state: 'gemessen', rate: 0.5, hits: 2, checked: 4, confused: 1 });
  assert.match(q.text, /1× verwechselt/);
});

// ── „das ist gar keine Person" ─────────────────────────────────────────

test('a known reject wins over a name suggestion on the tile', () => {
  // Für etwas, von dem der Betreiber gesagt hat, es sei kein Mensch,
  // einen Namen vorzuschlagen wäre die falsche Frage — und er hat sie
  // schon beantwortet.
  const row = { reject: { name: 'Keine Person' }, suggest: { name: 'Anna', confident: true } };
  assert.equal(suggestLabel(row), '∅ Keine Person');
  assert.ok(isKnownReject(row));
});

test('without a reject the tile still suggests a name', () => {
  assert.equal(suggestLabel({ suggest: { name: 'Anna', confident: true } }), 'Anna?');
  assert.ok(!isKnownReject({ suggest: { name: 'Anna' } }));
});

test('the header can say how much yesterday’s tagging saved today', () => {
  assert.equal(
    knownRejectCount([{ reject: { name: 'Keine Person' } }, { suggest: { name: 'Anna' } }, {}]),
    1,
  );
  assert.equal(knownRejectCount([]), 0);
});

test('a tile the register already knows is dimmed, not hidden', () => {
  // Verschwinden zu lassen, was man gerade getaggt hat, sieht aus wie
  // ein verlorener Tipp.
  const html = facesHtml([{ relpath: 'a', url: '/m/a.jpg', reject: { name: 'X' } }], new Set());
  assert.match(html, /class="idy-face is-reject"/);
});

test('the bar always offers the not-a-person way out', () => {
  assert.match(assignBarHtml(2, ['Anna'], ''), /data-idy="reject"/);
});

// ── ganze Person / Oberkörper / Kopf ───────────────────────────────────

test('the regions are listed best first, so the answer is the top row', () => {
  const rows = regionRows(
    {
      full: { checked: 10, hits: 7, rate: 0.7 },
      head: { checked: 10, hits: 9, rate: 0.9 },
      upper: { checked: 10, hits: 8, rate: 0.8 },
    },
    'full',
  );
  assert.deepEqual(
    rows.map((r) => r.key),
    ['head', 'upper', 'full'],
  );
  assert.equal(rows[0].pct, 90);
});

test('an unmeasured region is left out rather than shown as zero', () => {
  const rows = regionRows(
    { full: { checked: 4, hits: 2, rate: 0.5 }, head: { checked: 0 } },
    'full',
  );
  assert.deepEqual(
    rows.map((r) => r.key),
    ['full'],
  );
});

test('the region actually in use is marked', () => {
  const rows = regionRows({ full: { checked: 4, hits: 2, rate: 0.5 } }, 'full');
  assert.equal(rows[0].active, true);
  assert.match(regionsHtml({ full: { checked: 4, hits: 2, rate: 0.5 } }, 'full'), /is-active/);
});

test('nothing measured means no table at all', () => {
  assert.equal(regionsHtml({}, 'full'), '');
  assert.equal(regionsHtml({ head: { checked: 0 } }, 'full'), '');
});

test('the rows carry the count, not only the percentage', () => {
  const html = regionsHtml({ upper: { checked: 9, hits: 7, rate: 0.778 } }, 'full');
  assert.match(html, /Oberkörper/);
  assert.match(html, /78/);
  assert.match(html, /7\/9/);
});
