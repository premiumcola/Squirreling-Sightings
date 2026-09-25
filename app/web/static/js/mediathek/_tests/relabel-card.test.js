// ─── mediathek/_tests/relabel-card.test.js ─────────────────────────────────
// Die Kachel hinter dem Player muss die Korrektur zeigen, sobald man
// zurückkommt — nicht erst nach einem Filterwechsel.
//
// „Wenn ich dann ins, in die Mediathek … sage Fehlalarm … dann fertig
// drücke, dann zurück in die Mediathek gehe, dann steht das gleiche Video
// immer noch als Auto."
//
// Zwei Fehler hintereinander, beide hier festgehalten:
//
//   1. `onSaved: applyLabelSaveResult` — die Korrektur-Leiste ruft
//      onSaved(res, labels), das Label-Array landete also im `item`-
//      Parameter. Nach „Fehlalarm" war es `[]`: wahr genug, um den
//      Standardwert lbState.item zu verdrängen, und gepatcht wurde das
//      Array statt der Kachel.
//   2. repaintMediaCard suchte nur in #mediaGrid. Die gefilterte
//      Mediathek (Art-Chip, Label-Filter) ist #libraryGrid.
//
// Quelltext-Verträge wie in vplayer/_tests/relabel-repaint.test.js: die
// Module ziehen beim Import das halbe Lightbox-Gerüst mit.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const read = (rel) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

function code(src) {
  return src
    .replaceAll(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .map((l) => l.replace(/\/\/.*$/, ''))
    .join('\n');
}

test('the player hands only the reply on, so the item defaults to the open clip', () => {
  const src = code(read('../../mediaview/recorded-mode.js'));
  assert.ok(
    !/onSaved:\s*applyLabelSaveResult\s*,/.test(src),
    'onSaved gibt (res, labels) weiter — direkt übergeben wird das Array zum item',
  );
  assert.match(src, /onSaved:\s*\(res\)\s*=>\s*applyLabelSaveResult\(res\)/);
});

test('the card is repainted in BOTH grids', () => {
  const src = code(read('../_paging.js'));
  const fn = src.slice(src.indexOf('export function repaintMediaCard'));
  assert.match(fn, /'mediaGrid'/);
  assert.match(fn, /'libraryGrid'/, 'die gefilterte Mediathek ist #libraryGrid');
});
