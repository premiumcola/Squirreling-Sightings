// ─── sichtungen/_tests/dossier-row.test.js ─────────────────────────────────
// Wo der Steckbrief aufgeht.
//
// „kannst du das dosier bitte direkt unter dem angeklicktem element
// einsliden?" — er stand unter dem ganzen Raster, also antwortete ein
// Tipp auf einen Vogel in der zweiten Reihe irgendwo unterhalb des
// Bildschirms.
//
// Hinter dem ZEILENENDE, nicht hinter der Kachel: das Panel spannt alle
// Spalten, also schöbe es sonst die restlichen Vögel dieser Zeile nach
// unten und das Raster ordnete sich um das um, was man gerade öffnet.
// Das hier ist die Arithmetik dahinter, ohne DOM.

import { test } from 'node:test';
import assert from 'node:assert/strict';

/** Dieselbe Rechnung wie in _achievements.js::_placeDossierUnderRow. */
function insertAt(index, cols) {
  return Math.ceil((index + 1) / Math.max(1, cols)) * Math.max(1, cols);
}

test('the panel lands after the last tile of the tapped row', () => {
  // 4 columns: tiles 0-3 are row one, 4-7 row two.
  assert.equal(insertAt(0, 4), 4, 'first tile → after tile 3');
  assert.equal(insertAt(3, 4), 4, 'last tile of row one → same place');
  assert.equal(insertAt(4, 4), 8, 'first tile of row two → after tile 7');
  assert.equal(insertAt(7, 4), 8);
});

test('a one-column layout puts it straight under the tile', () => {
  assert.equal(insertAt(0, 1), 1);
  assert.equal(insertAt(5, 1), 6);
});

test('a column count that never arrived does not divide by zero', () => {
  assert.equal(insertAt(2, 0), 3);
  assert.equal(insertAt(2, -1), 3);
});

test('every tile of a row resolves to the same insertion point', () => {
  // The property that matters: the row never breaks, whichever of its
  // tiles was tapped.
  const cols = 3;
  const row = [3, 4, 5].map((i) => insertAt(i, cols));
  assert.deepEqual(row, [6, 6, 6]);
});
