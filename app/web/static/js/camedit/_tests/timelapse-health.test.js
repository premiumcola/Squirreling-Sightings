// Der Anteil, nicht die Anzahl.
//
// Die Profilzeile druckte „121 verworfen" neben „40 / 1350 Frames" —
// zwei Zahlen, die nebeneinander wie eine Fussnote aussehen, waehrend
// sie sagen, dass drei Viertel von allem, was diese Kamera aufgenommen
// hat, als unbrauchbar weggeworfen wurde. Genau das war die Ursache
// dafuer, dass die fertigen Videos immer wieder „lossy" herauskamen,
// ohne dass es jemand kommen sah.

import { test } from 'node:test';
import assert from 'node:assert/strict';

// Aus dem MODELL-Modul, nicht aus der Ansicht: timelapse-status.js fasst
// beim Laden `window` an und ist damit im Test gar nicht importierbar.
// Genau dafür gibt es hier die Trennung Modell/Ansicht.
import { captureHealthNote } from '../_timelapse-model.js';

test('drei Viertel verworfen wird als Anteil gesagt', () => {
  // Gartenkamera, an der laufenden Anlage gemessen.
  const note = captureHealthNote({ captured: 40, rejected: 121 });
  assert.match(note, /75 %/);
  assert.match(note, /lückenhaft/);
});

test('ein paar verworfene Bilder sind kein Alarm', () => {
  // Nut Bar am selben Tag: 11 von 122 — das ist normaler Betrieb, und
  // eine Warnung darauf waere die, die man kuenftig ueberliest.
  assert.equal(captureHealthNote({ captured: 111, rejected: 11 }), '');
});

test('ohne Verworfene bleibt die Zeile leer', () => {
  assert.equal(captureHealthNote({ captured: 900, rejected: 0 }), '');
});

test('zu wenig Material fuer eine Aussage schweigt', () => {
  // 2 von 3 sind 67 % und trotzdem nichts wert — der Tag hat gerade
  // erst angefangen.
  assert.equal(captureHealthNote({ captured: 1, rejected: 2 }), '');
});

test('fehlende Felder sind kein Absturz', () => {
  assert.equal(captureHealthNote(null), '');
  assert.equal(captureHealthNote({}), '');
  assert.equal(captureHealthNote({ rejected: 'viele' }), '');
});

test('die Schwelle liegt zwischen normalem Betrieb und Alarm', () => {
  // 29 % schweigt, 31 % spricht — damit die Grenze eine Entscheidung
  // ist und kein Zufall.
  assert.equal(captureHealthNote({ captured: 71, rejected: 29 }), '');
  assert.match(captureHealthNote({ captured: 69, rejected: 31 }), /31 %/);
});
