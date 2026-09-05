// Die Tastatur des Players — eine Taste, eine Absicht.
//
// „Zudem bitte auf Leertaste will ich pausieren und auf Pfeiltaste links,
// rechts, wenn ich will hin und her spulen können und Leertaste dann auch
// wieder play."
//
// Der Shell hat diese Tasten schon vorher GESCHLUCKT — bewusst, damit
// mediaview/keyboard.js unter einem offenen Player nicht zurücknavigiert
// — und dann nur Escape ausgewertet. Die Tasten fehlten also nicht, sie
// wurden still gefressen, was das schlechtere der beiden Versagen ist:
// fester drücken sieht aus wie dasselbe Nichts.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { keyAction, seekTarget, STEP_S, STEP_BIG_S } from '../_keys.js';

// ── Die Zuordnung ─────────────────────────────────────────────────────

test('Leertaste schaltet um, in beide Richtungen', () => {
  assert.deepEqual(keyAction(' '), { type: 'toggle' });
  // Aeltere Firefox-ESR und das alte Edge melden diesen Namen. Eine
  // Taste, die auf einem Browser nichts tut, ist eine kaputte Taste.
  assert.deepEqual(keyAction('Spacebar'), { type: 'toggle' });
});

test('die Pfeile spulen, links negativ und rechts positiv', () => {
  assert.deepEqual(keyAction('ArrowLeft'), { type: 'seek', delta: -STEP_S });
  assert.deepEqual(keyAction('ArrowRight'), { type: 'seek', delta: STEP_S });
});

test('mit Shift wird der Schritt gröber', () => {
  assert.equal(keyAction('ArrowRight', { shift: true }).delta, STEP_BIG_S);
  assert.equal(keyAction('ArrowLeft', { shift: true }).delta, -STEP_BIG_S);
  assert.ok(STEP_BIG_S > STEP_S, 'sonst ist Shift bedeutungslos');
});

test('hoch und runter sind das grobe Paar, nicht die Lautstärke', () => {
  // Diese Clips werden angesehen, WEIL sich etwas bewegt hat; Ton ist auf
  // jeder Kamera hier abgeschaltet. Eine Lautstärketaste auf einem
  // stummen Clip ist eine Taste, die nichts tut.
  assert.equal(keyAction('ArrowUp').delta, STEP_BIG_S);
  assert.equal(keyAction('ArrowDown').delta, -STEP_BIG_S);
});

test('Home und End springen an die Enden, Escape schliesst', () => {
  assert.deepEqual(keyAction('Home'), { type: 'seekTo', to: 0 });
  assert.equal(keyAction('End').to, Infinity);
  assert.deepEqual(keyAction('Escape'), { type: 'close' });
});

test('eine Taste ohne Bedeutung wird nicht beansprucht', () => {
  // null heisst: der Aufrufer lässt das Ereignis in Ruhe. Alles andere
  // hiesse, Tasten zu schlucken, ohne etwas mit ihnen zu tun — genau der
  // Zustand, aus dem diese Datei entstanden ist.
  for (const k of ['a', 'Enter', 'Tab', 'F5', 'PageDown']) {
    assert.equal(keyAction(k), null, `${k} gehoert dem Browser`);
  }
});

// ── Die Arithmetik ────────────────────────────────────────────────────

test('gespult wird innerhalb des Clips, nie darüber hinaus', () => {
  assert.equal(seekTarget(keyAction('ArrowLeft'), 2, 30), 0, 'nicht ins Negative');
  const ans = seekTarget(keyAction('ArrowRight'), 28, 30);
  assert.ok(ans < 30, 'nie genau auf die Dauer');
  assert.ok(ans > 29, 'aber so weit wie möglich');
});

test('End landet kurz VOR dem Ende, nicht darauf', () => {
  // Genau auf der Dauer parken manche Browser mit gesetztem `ended` —
  // was jede andere Fläche im Player als „ist durchgelaufen" liest.
  const t = seekTarget(keyAction('End'), 0, 30);
  assert.ok(t < 30 && t > 29.9, `unerwartet: ${t}`);
});

test('ohne bekannte Dauer wird nicht geraten', () => {
  assert.equal(seekTarget(keyAction('ArrowRight'), 5, 0), 0);
  assert.equal(seekTarget(keyAction('ArrowRight'), 5, NaN), 0);
});

test('was kein Sprung ist, ergibt kein Ziel', () => {
  assert.equal(seekTarget(keyAction(' '), 5, 30), null);
  assert.equal(seekTarget(keyAction('Escape'), 5, 30), null);
  assert.equal(seekTarget(null, 5, 30), null);
});

test('eine unbekannte aktuelle Position zählt als Anfang', () => {
  // `video.currentTime` ist vor den Metadaten NaN. Daraus darf kein NaN
  // als Sprungziel werden — das setzt currentTime still auf 0 zurück und
  // sieht aus wie ein Sprung an den Anfang ohne Grund.
  assert.equal(seekTarget(keyAction('ArrowRight'), NaN, 30), STEP_S);
});
