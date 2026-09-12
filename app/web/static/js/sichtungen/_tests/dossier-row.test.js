// ─── sichtungen/_tests/dossier-row.test.js ─────────────────────────────────
// Wo der Steckbrief aufgeht — und dass er eine Neuzeichnung überlebt.
//
// „Kann's sein, dass die Dosiers mit dem Unterschieben am Handy irgendwie
// noch nicht so richtig funktionieren? Das eine untere schiebt's runter,
// aber die anderen erkannten, da schiebt sich gar nix auf."
//
// Zwei Fehler, beide hier eingefangen:
//
//   1. Die Vorgängerfassung dieser Datei hat die Zeilenrechnung
//      ABGESCHRIEBEN statt sie zu importieren („dieselbe Rechnung wie in
//      _achievements.js"). Damit konnte sie grün bleiben, während die
//      echte Rechnung am Handy dreifach danebenlag — sie rechnete mit der
//      gemessenen SPURENZAHL (12), während vier Kacheln in eine Zeile
//      passen. Jetzt wird das echte Modul importiert.
//
//   2. `#achievementsGrid.innerHTML = …` löschte das Panel, sobald es
//      einmal im Raster stand. Ab dem zweiten Vogel tat ein Tipp gar
//      nichts mehr.

import { test } from 'node:test';
import assert from 'node:assert/strict';

// ── ein Mini-DOM, nur so viel wie das Modul anfasst ────────────────────
function el(cls = '', top = 0) {
  return {
    className: cls,
    offsetTop: top,
    hidden: false,
    parentElement: null,
    nextElementSibling: null,
    children: [],
    classList: {
      _s: new Set(cls.split(' ').filter(Boolean)),
      add(c) {
        this._s.add(c);
      },
      remove(c) {
        this._s.delete(c);
      },
      contains(c) {
        return this._s.has(c);
      },
    },
    insertBefore(node, ref) {
      if (node.parentElement) {
        const old = node.parentElement.children;
        const at = old.indexOf(node);
        if (at >= 0) old.splice(at, 1);
      }
      const i = ref ? this.children.indexOf(ref) : -1;
      if (i >= 0) this.children.splice(i, 0, node);
      else this.children.push(node);
      node.parentElement = this;
      return node;
    },
    querySelector(sel) {
      const want = sel.replace('.', '');
      return this.children.find((c) => c.classList.contains(want)) || null;
    },
  };
}

const _ids = new Map();
globalThis.window = globalThis.window || {};
globalThis.document = {
  getElementById: (id) => _ids.get(id) || null,
};

const { cardAfterRowOf, liftDossierOutOfGrid, placeDossierUnderRow, _forgetDossierHome } =
  await import('../_dossier-placement.js');

/** Ein Raster aus `n` Kacheln, `perRow` je Zeile, plus das Panel an
 *  seinem Heimatplatz hinter dem Raster. */
function scene(n, perRow, activeIndex) {
  _ids.clear();
  _forgetDossierHome();
  const section = el('section');
  const gridHost = el('ach-grid');
  const cardsGrid = el('ach-cards-grid');
  const panel = el('sd-panel');
  panel.hidden = false;
  section.insertBefore(gridHost, null);
  gridHost.insertBefore(cardsGrid, null);
  section.insertBefore(panel, null);
  const cards = [];
  for (let i = 0; i < n; i++) {
    const c = el('ach-card', Math.floor(i / perRow) * 100);
    if (i === activeIndex) c.classList.add('ach-card--active');
    cardsGrid.insertBefore(c, null);
    cards.push(c);
  }
  _ids.set('achievementsGrid', gridHost);
  _ids.set('speciesDossierPanel', panel);
  return { section, gridHost, cardsGrid, panel, cards };
}

const positionOf = (s) => s.cardsGrid.children.indexOf(s.panel);

// ── die Zeilenrechnung ─────────────────────────────────────────────────

test('the row is read off the layout, not off a column count', () => {
  // Genau der Fall vom Handy: 27 Kacheln, vier je Zeile, angetippt ist
  // die zweite Kachel der fünften Zeile (Hausrotschwanz, Index 17).
  const cards = Array.from({ length: 27 }, (_, i) => ({ offsetTop: Math.floor(i / 4) * 100 }));
  // Die nächste Kachel nach Zeile fünf ist Index 20 — NICHT 24, was die
  // alte Spaltenrechnung mit den gemessenen 12 Spuren geliefert hat.
  assert.equal(cardAfterRowOf(cards, cards[17]), cards[20]);
});

test('every tile of a row resolves to the same insertion point', () => {
  const cards = Array.from({ length: 12 }, (_, i) => ({ offsetTop: Math.floor(i / 3) * 100 }));
  const row = [3, 4, 5].map((i) => cardAfterRowOf(cards, cards[i]));
  assert.deepEqual(row, [cards[6], cards[6], cards[6]]);
});

test('a tile in the last row inserts at the end', () => {
  const cards = Array.from({ length: 6 }, (_, i) => ({ offsetTop: Math.floor(i / 3) * 100 }));
  assert.equal(cardAfterRowOf(cards, cards[4]), null);
});

test('a one-per-row layout puts it straight under the tile', () => {
  const cards = Array.from({ length: 4 }, (_, i) => ({ offsetTop: i * 100 }));
  assert.equal(cardAfterRowOf(cards, cards[0]), cards[1]);
  assert.equal(cardAfterRowOf(cards, cards[2]), cards[3]);
});

test('sub-pixel row tops still count as one row', () => {
  const cards = [{ offsetTop: 100 }, { offsetTop: 100.4 }, { offsetTop: 200 }];
  assert.equal(cardAfterRowOf(cards, cards[0]), cards[2]);
});

test('a card that is not in the list means hands off, not append', () => {
  // `undefined` und `null` sind hier zwei verschiedene Antworten: die
  // eine heißt „nichts anfassen", die andere „ans Ende".
  const cards = [{ offsetTop: 0 }];
  assert.equal(cardAfterRowOf(cards, { offsetTop: 0 }), undefined);
  assert.equal(cardAfterRowOf([], { offsetTop: 0 }), undefined);
});

// ── das Verschieben ────────────────────────────────────────────────────

test('the panel slides in behind the tapped row', () => {
  const s = scene(27, 4, 17);
  placeDossierUnderRow();
  assert.equal(positionOf(s), 20, 'hinter Kachel 19, also am Ende der fünften Zeile');
  assert.ok(s.panel.classList.contains('sd-panel--inrow'));
});

test('with no active tile it goes back home, outside the grid', () => {
  const s = scene(8, 4, 17); // kein Index 17 → keine aktive Kachel
  placeDossierUnderRow();
  assert.equal(positionOf(s), -1);
  assert.equal(s.panel.parentElement, s.section);
  assert.ok(!s.panel.classList.contains('sd-panel--inrow'));
});

test('a hidden panel is never parked inside the grid', () => {
  const s = scene(8, 4, 2);
  s.panel.hidden = true;
  placeDossierUnderRow();
  assert.equal(positionOf(s), -1);
});

// ── und dass es die Neuzeichnung überlebt ──────────────────────────────

test('the panel is lifted out before the grid is rewritten', () => {
  // DER Fehler: nach dem ersten Öffnen steht das Panel IM Raster, und
  // `innerHTML = …` hätte es gelöscht. Danach fand jeder weitere Tipp
  // nichts mehr vor und tat gar nichts.
  const s = scene(27, 4, 17);
  placeDossierUnderRow();
  assert.equal(s.panel.parentElement, s.cardsGrid, 'Voraussetzung: es steht drin');

  liftDossierOutOfGrid();
  assert.equal(s.panel.parentElement, s.section, 'vor dem Neuzeichnen wieder draußen');
  assert.equal(positionOf(s), -1);

  // Das Raster wird neu geschrieben — das Panel ist nicht betroffen.
  s.cardsGrid.children = s.cards.map((c) => c);
  placeDossierUnderRow();
  assert.equal(s.panel.parentElement, s.cardsGrid, 'und danach wieder an seiner Zeile');
});

test('lifting out twice in a row is harmless', () => {
  const s = scene(8, 4, 1);
  placeDossierUnderRow();
  liftDossierOutOfGrid();
  liftDossierOutOfGrid();
  assert.equal(s.panel.parentElement, s.section);
});
