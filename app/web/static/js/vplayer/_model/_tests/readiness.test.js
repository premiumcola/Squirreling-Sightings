// ─── vplayer/_model/_tests/readiness.test.js ───────────────────────────────
// Was der Player über einen Clip weiß — und was er daraus zeichnen darf.
//
// Der gemeldete Fall: ein Vogelvideo, Panel zeigt „Vogel 57 %", Zeitraum
// „— · —", Timeline ohne eine einzige Lane, Bild ohne einen Kasten. Für
// diesen Clip gibt es kein tracks.json. Der Overlay las AUSSCHLIESSLICH
// den Sidecar, malte also korrekterweise nichts — und sagte nichts.
//
// Die Unterscheidung, die diese Datei festnagelt, ist die, deren Fehlen
// den Betreiber „warum ist da überall nichts" schreiben ließ: „noch nicht
// geladen", „gibt es nicht" und „die Nachanalyse hat nichts gefunden"
// sind DREI Zustände. Sie dürfen nie gleich aussehen.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  CLIP_COARSE,
  CLIP_EMPTY,
  CLIP_MISSING,
  CLIP_PENDING,
  CLIP_READY,
  GEOM_NONE,
  GEOM_PER_FRAME,
  GEOM_TRIGGER,
  clipReadiness,
  triggerBoxVisible,
} from '../readiness.js';

const TRIGGER_ITEM = {
  detections: [
    { label: 'bird', score: 0.57, bbox: { x1: 200, y1: 150, x2: 290, y2: 218 } },
    { label: 'cat', score: 0.31, bbox: { x1: 60, y1: 200, x2: 140, y2: 300 } },
  ],
};

const SIDECAR = {
  tracks: [{ _num: 1, label: 'bird', samples: [{ t: 1, bbox: { x1: 1, y1: 1, x2: 9, y2: 9 } }] }],
};

test('ein Sidecar mit Spuren ist die volle Auskunft', () => {
  const r = clipReadiness(TRIGGER_ITEM, SIDECAR);
  assert.equal(r.state, CLIP_READY);
  assert.equal(r.geometry, GEOM_PER_FRAME);
  assert.equal(r.note, null, 'ein vollständiger Clip braucht keinen Hinweis');
});

test('noch nicht geladen ist NICHT dasselbe wie nicht vorhanden', () => {
  // `undefined` heißt: die Anfrage läuft noch. Genau diese Unterscheidung
  // fehlte — beides sah als leeres Bild identisch aus.
  const pending = clipReadiness(TRIGGER_ITEM, undefined);
  const absent = clipReadiness(TRIGGER_ITEM, null);
  assert.equal(pending.state, CLIP_PENDING);
  assert.equal(absent.state, CLIP_COARSE);
  assert.notEqual(pending.state, absent.state);
});

test('ohne Sidecar trägt das Auslöse-Bild die Kästen', () => {
  const r = clipReadiness(TRIGGER_ITEM, null);
  assert.equal(r.state, CLIP_COARSE);
  assert.equal(r.geometry, GEOM_TRIGGER);
  assert.equal(r.trigger.length, 2);
  assert.match(r.note, /Auslöse-Bild/);
});

test('nur Erkennungen MIT Kasten zählen als zeichenbar', () => {
  // Eine Erkennung ohne bbox ist eine Zeile im Panel, aber nichts fürs
  // Bild. Sie als zeichenbar zu zählen hieße, einen leeren Zustand als
  // „grob" zu melden und dann doch nichts zu malen.
  const r = clipReadiness({ detections: [{ label: 'bird', score: 0.4 }] }, null);
  assert.equal(r.state, CLIP_MISSING);
  assert.equal(r.geometry, GEOM_NONE);
});

test('ein leerer Sidecar ist eine Antwort, keine Lücke', () => {
  const r = clipReadiness(TRIGGER_ITEM, { tracks: [] });
  assert.equal(r.state, CLIP_EMPTY);
  assert.match(r.note, /nichts gefunden/);
});

test('ein leerer Sidecar bietet den Auslöse-Kasten NICHT als Trostpreis an', () => {
  // Die Nachanalyse ist den ganzen Clip mit einer niedrigeren Schwelle
  // abgelaufen als die Live-Pipeline und hat nichts gefunden. Ein
  // einzelner Auslöse-Kasten würde der gründlicheren Antwort
  // widersprechen, die schon vorliegt.
  const r = clipReadiness(TRIGGER_ITEM, { tracks: [] });
  assert.deepEqual(r.trigger, []);
  assert.equal(r.geometry, GEOM_NONE);
});

test('gar nichts bekannt sagt das auch', () => {
  const r = clipReadiness({}, null);
  assert.equal(r.state, CLIP_MISSING);
  assert.match(r.note, /keine Feinspur/);
});

test('ein Auslöse-Kasten steht still — also nur bei Pause', () => {
  // Er ist ein einziger Augenblick. Ihn während der Wiedergabe stehen zu
  // lassen behauptet, das Subjekt sei dort, wo es längst weg ist. Das ist
  // die Regel, die der alte Renderer erarbeitet hatte.
  const coarse = clipReadiness(TRIGGER_ITEM, null);
  assert.equal(triggerBoxVisible(coarse, false), true, 'pausiert: sichtbar');
  assert.equal(triggerBoxVisible(coarse, true), false, 'läuft: verschwindet');
});

test('mit Feinspur gilt die Pausenregel nicht', () => {
  // Per-Frame-Geometrie folgt dem Subjekt, also darf und soll sie während
  // der Wiedergabe stehen bleiben.
  const ready = clipReadiness(TRIGGER_ITEM, SIDECAR);
  assert.equal(triggerBoxVisible(ready, false), false);
  assert.equal(triggerBoxVisible(ready, true), false);
});
