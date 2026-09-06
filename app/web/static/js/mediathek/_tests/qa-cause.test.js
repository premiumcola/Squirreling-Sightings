// Zwei rote Zeitraffer, zwei vollkommen verschiedene Ursachen.
//
// Beide Fixtures unten sind an der laufenden Anlage gemessen, am selben
// Tag, mit demselben Profil und derselben Note „red" — und mit
// Ursachen, die nichts miteinander zu tun haben. Genau das konnte das
// alte Modal nicht zeigen: es druckte declared/effective/unique fps und
// eine Duplikatquote, also viermal das Symptom.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { qaCause, qaSummary, REJECT_REASON_DE } from '../_qa-cause.js';

/** Nut Bar, 2026-09-05: die Aufnahme laeuft kaum. */
const STARVED = {
  quality_grade: 'red',
  capture: {
    expected_frames: 1350,
    captured_frames: 111,
    rejected_frames: 11,
    reject_reasons: { split_left_dead: 11 },
  },
  playback: { duplicate_ratio: 0.579, duration_s: 90.12, frames_in_file: 2253 },
};

/** Garten, derselbe Tag: der Bildpruefer wirft drei Viertel weg. */
const REJECTED = {
  quality_grade: 'red',
  capture: {
    expected_frames: 1350,
    captured_frames: 40,
    rejected_frames: 121,
    reject_reasons: { bottom_strip_bright: 106, grey_toned: 13, horizontal_anomaly_band: 2 },
  },
  playback: { duplicate_ratio: 0.77, duration_s: 90, frames_in_file: 2250 },
};

test('wenig aufgenommen, wenig verworfen → die Aufnahme ist das Problem', () => {
  const c = qaCause(STARVED);
  assert.equal(c.kind, 'starved');
  // 111 + 11 = 122 von 1350 = 9 %
  assert.match(c.headline, /9 %/);
  assert.match(c.lever, /Zeitraffer-Aufnahme/);
});

test('das meiste verworfen → das Bildmaterial ist das Problem', () => {
  const c = qaCause(REJECTED);
  assert.equal(c.kind, 'rejected');
  // 121 von 161 = 75 %
  assert.match(c.headline, /75 %/);
  // Und der Grund steht auf Deutsch da, nicht als Schluesselwort.
  assert.match(c.detail, /heller Streifen am unteren Rand/);
  assert.match(c.detail, /106/);
});

test('die beiden Faelle sind unterscheidbar — darum geht es', () => {
  // Beide sind „red" mit hoher Duplikatquote. Wer nur darauf schaut,
  // sieht denselben Fehler zweimal.
  assert.notEqual(qaCause(STARVED).kind, qaCause(REJECTED).kind);
  assert.notEqual(qaCause(STARVED).headline, qaCause(REJECTED).headline);
});

test('genug Material, trotzdem gestreckt → die Ziel-Laenge ist zu lang', () => {
  const c = qaCause({
    quality_grade: 'yellow',
    capture: { expected_frames: 1350, captured_frames: 1300, rejected_frames: 5 },
    playback: { duplicate_ratio: 0.35, duration_s: 90 },
  });
  assert.equal(c.kind, 'stretched');
  assert.match(c.lever, /Intervall|Ziel-Länge/);
});

test('ein sauberer Zeitraffer hat nichts zu erklaeren', () => {
  assert.equal(qaCause({ quality_grade: 'green' }), null);
  assert.equal(qaCause({ quality_grade: 'n/a' }), null);
  assert.equal(qaCause(null), null);
});

test('die Kennzahlen tragen immer vier Werte', () => {
  for (const qa of [STARVED, REJECTED]) {
    const c = qaCause(qa);
    assert.equal(c.numbers.length, 4);
    for (const n of c.numbers) assert.ok(n.value && n.label);
  }
});

test('kaputte Sidecars sind kein Absturz', () => {
  const c = qaCause({ quality_grade: 'red' });
  assert.ok(c, 'eine Note ohne Zahlen muss trotzdem etwas sagen');
  assert.equal(c.kind, 'other');
});

test('jeder Pruefgrund hat ein deutsches Wort', () => {
  // Die Liste kommt aus frame_helpers; ein Schluesselwort im Modal ist
  // fuer den Betreiber dasselbe wie gar keine Angabe.
  for (const key of ['split_left_dead', 'bottom_strip_bright', 'grey_toned']) {
    assert.ok(REJECT_REASON_DE[key], key + ' fehlt');
    assert.equal(/[a-z]_[a-z]/.test(REJECT_REASON_DE[key]), false, 'kein Schluesselwort');
  }
});

test('die Uebersicht zaehlt Noten und Ursachen', () => {
  const s = qaSummary([STARVED, REJECTED, { quality_grade: 'green' }, null]);
  assert.equal(s.total, 3);
  assert.equal(s.red, 2);
  assert.equal(s.green, 1);
  assert.equal(s.kinds.starved, 1);
  assert.equal(s.kinds.rejected, 1);
});

test('eine leere Uebersicht ist null, keine Null-Zeile', () => {
  assert.equal(qaSummary([]), null);
  assert.equal(qaSummary(null), null);
});
