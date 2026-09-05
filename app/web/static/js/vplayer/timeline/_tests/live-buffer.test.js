// Der rollende Streifen bekommt seine Spuren von hier — vorher von
// nirgends.
//
// „wo ist der Durchlauf der Spur-/Objekt-KI-Informationen??"
//
// index.js reichte dem Streifen `frame.tracks`, und `mapFrame` erzeugt
// gar kein `tracks`-Feld. Das Argument war auf JEDEM Tick `undefined`,
// also wurde der Streifen mit einer leeren Spurliste gerendert — auf der
// Live-Ansicht und in der Simulation gleichermassen. Nichts warf einen
// Fehler; die Komponente hatte schlicht keine Eingabe.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { makeLiveTrackBuffer } from '../_live-buffer.js';
import { buildTimelineModel } from '../_model.js';

/** Ein Tick, wie mapFrame ihn liefert: Datensaetze mit .raw. */
function tick(dets) {
  return { detections: dets.map((raw) => ({ raw })) };
}

const PASS = (num, label, score) => ({
  label,
  score,
  verdict: 'pass',
  track_num: num,
  bbox: [10, 10, 40, 80],
});

test('nur Erkennungen MIT Spur-Nummer bilden eine Spur', () => {
  // An der laufenden Instanz gemessen: von 26 Erkennungen eines Ticks
  // trug genau die eine bestandene Person eine Nummer — jede gefilterte,
  // jede no_track und jede outside_zone hatte keine. Das ist die
  // richtige Grundmenge: eine Spur ist ein Objekt MIT Identitaet.
  const buf = makeLiveTrackBuffer();
  buf.push(
    tick([
      PASS(1, 'person', 0.84),
      { label: 'chair', score: 0.28, verdict: 'filtered', track_num: null, bbox: [0, 0, 5, 5] },
      { label: 'person', score: 0.27, verdict: 'no_track', bbox: [0, 0, 5, 5] },
    ]),
    100,
  );
  assert.equal(buf.size(), 1);
  assert.equal(buf.tracks()[0]._num, 1);
});

test('aufeinanderfolgende Ticks werden zu einer Spur mit Verlauf', () => {
  const buf = makeLiveTrackBuffer();
  buf.push(tick([PASS(1, 'person', 0.8)]), 100);
  buf.push(tick([PASS(1, 'person', 0.9)]), 101);
  buf.push(tick([PASS(1, 'person', 0.7)]), 102);
  const [tr] = buf.tracks();
  assert.equal(tr.samples.length, 3);
  assert.deepEqual(
    tr.samples.map((s) => s.t),
    [100, 101, 102],
  );
});

test('was aus dem Fenster faellt, wird vergessen', () => {
  const buf = makeLiveTrackBuffer({ windowS: 10 });
  buf.push(tick([PASS(1, 'person', 0.8)]), 100);
  buf.push(tick([PASS(1, 'person', 0.8)]), 105);
  buf.push(tick([PASS(1, 'person', 0.8)]), 118);
  const [tr] = buf.tracks();
  assert.deepEqual(
    tr.samples.map((s) => s.t),
    [118],
    'alles vor 108 ist draussen',
  );
});

test('eine Spur, die ganz aus dem Fenster laeuft, verschwindet', () => {
  const buf = makeLiveTrackBuffer({ windowS: 10 });
  buf.push(tick([PASS(2, 'cat', 0.8)]), 100);
  buf.push(tick([PASS(1, 'person', 0.8)]), 130);
  assert.equal(buf.size(), 1);
  assert.equal(buf.tracks()[0]._num, 1, 'die Katze ist Geschichte');
});

test('ein spaeter geschaerfter Name gewinnt', () => {
  // Die Wildtier-Stufe benennt eine Art erst einige Bilder spaeter. Die
  // Spur heisst dann so, nicht weiter wie ihr erstes Bild.
  const buf = makeLiveTrackBuffer();
  buf.push(tick([PASS(1, 'bird', 0.6)]), 100);
  buf.push(tick([PASS(1, 'Hausrotschwanz', 0.7)]), 101);
  assert.equal(buf.tracks()[0].label, 'Hausrotschwanz');
});

test('die Spuren passen ohne Umweg in das Zeitleisten-Modell', () => {
  // DER PUNKT DER GANZEN DATEI: die Ausgabe hat die Form von
  // tracks.json, also braucht buildTimelineModel keinen Live-Sonderweg.
  const buf = makeLiveTrackBuffer();
  buf.push(tick([PASS(1, 'person', 0.8), PASS(2, 'cat', 0.4)]), 100);
  buf.push(tick([PASS(1, 'person', 0.9)]), 104);
  const m = buildTimelineModel(buf.tracks(), { windowMs: 60000, now: 104, threshold: 0.5 });
  assert.equal(m.lanes.length, 2);
  assert.equal(m.rolling, true);
  // Die Katze lag mit 40 % unter der Spawn-Schwelle — ihre Spur muss
  // sich als schwach lesen, nicht als bestaetigt.
  const katze = m.lanes.find((l) => l.label === 'cat');
  assert.equal(katze.status, 'weak');
});

test('ein Tick ohne Erkennungen ist kein Absturz und kein Verlust', () => {
  const buf = makeLiveTrackBuffer();
  buf.push(tick([PASS(1, 'person', 0.8)]), 100);
  buf.push({ detections: [] }, 101);
  buf.push({}, 102);
  assert.equal(buf.size(), 1, 'die Spur bleibt im Fenster stehen');
});
