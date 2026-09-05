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
  CLIP_BUILDING,
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
  video_relpath: 'motion_detection/cam_a/2026-08-30/e1.mp4',
  detections: [
    { label: 'bird', score: 0.57, bbox: { x1: 200, y1: 150, x2: 290, y2: 218 } },
    { label: 'cat', score: 0.31, bbox: { x1: 60, y1: 200, x2: 140, y2: 300 } },
  ],
};

const SIDECAR = {
  tracks: [{ _num: 1, label: 'bird', samples: [{ t: 1, bbox: { x1: 1, y1: 1, x2: 9, y2: 9 } }] }],
};

/** Werte, die der Worker wirklich angelegt hat — Sidecar-Schema 4,
 *  tracking_worker/_payload.py::build_payload. */
const EMPTY_SIDECAR = {
  schema: 4,
  built_at: '2026-08-30T14:35:02',
  gates: { min_confidence: 0.5, raw_floor: 0.2, miss_grace_s: 2 },
  tracks: [],
};

/** Der Wert im Chip kommt aus dem Namen, nicht aus der Position. */
function factValue(readiness, label) {
  return (readiness.facts.find((f) => f.label === label) || {}).value;
}

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

test('ein leerer Sidecar ohne Auslöse-Kasten ist eine Antwort, keine Lücke', () => {
  const r = clipReadiness({ video_relpath: 'a/b.mp4' }, { tracks: [] });
  assert.equal(r.state, CLIP_EMPTY);
  assert.match(r.note, /keine Spur bestätigt/);
  assert.equal(r.geometry, GEOM_NONE);
  // Derselbe Lauf mit denselben Schwellen liefert dasselbe Nichts.
  assert.equal(r.rebuildable, false);
});

test('ein leerer Sidecar zeigt den Auslöse-Kasten TROTZDEM', () => {
  // Die Umkehr einer früheren Regel, und zwar an Belegen: ein Ereignis
  // mit einem Vogel bei 57 % samt Kasten und bestimmter Art hat auf
  // dieser Kiste einen leeren Sidecar daneben liegen. „auch hier ist 'n
  // Vogel drin. Keine Box." Der Kasten ist die Messung, der leere
  // Sidecar die Schlussfolgerung — bei Widerspruch gewinnt die Messung.
  const r = clipReadiness(TRIGGER_ITEM, { tracks: [] });
  assert.equal(r.state, CLIP_EMPTY);
  assert.equal(r.geometry, GEOM_TRIGGER);
  assert.equal(r.trigger.length, 2);
});

test('lag der Auslöser über der Schwelle, wird der Widerspruch benannt', () => {
  const r = clipReadiness(TRIGGER_ITEM, {
    tracks: [],
    gates: { min_confidence: 0.5 },
    built_at: '2026-09-01T15:46:21',
  });
  assert.match(r.note, /obwohl der Auslöser über der Schwelle lag/);
  // Und NUR dann lohnt ein zweiter Lauf.
  assert.equal(r.rebuildable, true);
});

test('unter der Schwelle ist kein Widerspruch und kein Nachbau', () => {
  const low = { ...TRIGGER_ITEM, detections: [{ ...TRIGGER_ITEM.detections[0], score: 0.3 }] };
  const r = clipReadiness(low, { tracks: [], gates: { min_confidence: 0.5 } });
  assert.equal(r.geometry, GEOM_TRIGGER, 'gezeigt wird er trotzdem');
  assert.equal(/über der Schwelle/.test(r.note), false);
  assert.equal(r.rebuildable, false);
});

test('gar nichts bekannt sagt das auch — und sagt WAS fehlt', () => {
  // Ohne Videodatei kann die Nachanalyse nichts ablaufen, und
  // /api/tracking/reindex/<id> antwortet genau darauf mit 404. „Keine
  // Feinspur" allein hätte den Knopf angeboten, der nur scheitern kann.
  const r = clipReadiness({}, null);
  assert.equal(r.state, CLIP_MISSING);
  assert.match(r.note, /keine Videodatei/);
  assert.equal(r.rebuildable, false);
});

test('ein Clip mit Video, aber ohne je gebaute Feinspur, darf nachgebaut werden', () => {
  const r = clipReadiness({ video_relpath: 'a/b.mp4' }, null);
  assert.equal(r.state, CLIP_MISSING);
  assert.match(r.note, /nie eine Feinspur/);
  assert.equal(r.rebuildable, true);
});

test('eine fehlgeschlagene Umwandlung nennt den Grund und bietet nichts an', () => {
  // clip_recovery.py::mark_interrupted schreibt genau diese drei Felder.
  const r = clipReadiness(
    {
      status: 'error',
      stage: 'failed',
      encode_error: 'Ein Neustart hat die Verarbeitung unterbrochen.',
    },
    null,
  );
  assert.equal(r.state, CLIP_MISSING);
  assert.match(r.note, /fehlgeschlagen/);
  // Der Satz des Recorders steht als eigene Zeile, nicht als Chip: ein
  // dreizeiliger String in einem Feld für „50 %" ist Layout, keine Angabe.
  assert.equal(r.sub, 'Ein Neustart hat die Verarbeitung unterbrochen.');
  assert.deepEqual(r.facts, []);
  assert.equal(r.rebuildable, false);
});

// ── Der Clip selbst ist noch nicht fertig ──────────────────────────────────

test('ein Clip in der Umwandlung ist kein Clip ohne Feinspur', () => {
  // Erreichbar über Vor/Zurück im Player: die Liste ist state._allMedia,
  // und die enthält die noch entstehenden Clips (media_index/_visible.py).
  // Vorher landete so ein Clip in „keine Feinspur" samt Nachbau-Knopf,
  // den die Route mangels Video mit 404 beantwortet.
  const r = clipReadiness({ stage: 'encoding', status: 'processing', stage_age_s: 42 }, null);
  assert.equal(r.state, CLIP_BUILDING);
  assert.equal(r.geometry, GEOM_NONE);
  assert.equal(r.rebuildable, false);
});

test('die Produktion des Clips schlägt jede Sidecar-Frage', () => {
  // Auch mit vorliegendem Sidecar: solange ffmpeg schreibt, ist die
  // ehrliche Auskunft die Phase, nicht die Spurenlage.
  const item = { stage: 'recording', status: 'recording' };
  assert.equal(clipReadiness(item, SIDECAR).state, CLIP_BUILDING);
  assert.equal(clipReadiness(item, undefined).state, CLIP_BUILDING);
});

test('ein Ereignis ohne Stage-Angabe ist fertig, nicht in Arbeit', () => {
  // _stages.py::stage_of fällt für alte Ereignisse auf „ready" zurück;
  // ein leeres Objekt darf nie als laufende Aufnahme gelesen werden.
  assert.notEqual(clipReadiness({}, null).state, CLIP_BUILDING);
  assert.notEqual(clipReadiness({ status: 'ready' }, SIDECAR).state, CLIP_BUILDING);
});

// ── Die Gründe, die jeder Zustand mitbringt ────────────────────────────────

test('nichts gefunden nennt die Schwelle, gegen die es nichts fand', () => {
  const item = {
    ...TRIGGER_ITEM,
    whole_clip: { detections: [{ label: 'bird', score: 0.33 }] },
  };
  const r = clipReadiness(item, EMPTY_SIDECAR);
  assert.equal(r.gate.threshold, 0.5, 'gates.min_confidence, nicht geraten');
  assert.equal(r.gate.best, 0.33, 'der beste Wert, den die Live-Pipeline je hatte');
  assert.equal(r.gate.bestFrom, 'clip');
  assert.equal(factValue(r, 'Schwelle'), '50 %');
  assert.equal(factValue(r, 'bester Live-Wert'), '33 %');
  assert.equal(factValue(r, 'geprüft'), '14:35', 'built_at belegt, dass der Lauf durch ist');
});

test('ohne whole_clip zählt der beste Wert des Auslöse-Bildes — und sagt das', () => {
  // Zwei verschiedene Läufe. Der Auslöse-Wert als „Live-Wert" zu
  // etikettieren wäre die eine Zahl, die hier lügen könnte.
  const r = clipReadiness(TRIGGER_ITEM, EMPTY_SIDECAR);
  assert.equal(r.gate.bestFrom, 'trigger');
  assert.equal(factValue(r, 'bester Auslöse-Wert'), '57 %');
});

test('ein Sidecar ohne gates-Block erfindet keine Schwelle', () => {
  // Schema 3 und älter kennt den Block nicht. Dann bleibt der Satz —
  // aber keine Zahl, die es nie gab.
  const r = clipReadiness(TRIGGER_ITEM, { schema: 3, built_at: '2026-08-30T14:35:02', tracks: [] });
  assert.equal(r.gate.threshold, null);
  assert.equal(factValue(r, 'Schwelle'), undefined);
  assert.equal(factValue(r, 'geprüft'), '14:35');
});

test('nichts gefunden bietet keinen Nachbau an — solange nichts widerspricht', () => {
  // Derselbe Lauf mit denselben Gates fände dasselbe Nichts. Die Gates
  // sind das Handlungsfähige daran, nicht ein zweiter Durchlauf.
  //
  // TRIGGER_ITEM widerspricht allerdings: sein Vogel liegt mit 57 % über
  // der Schwelle von 50 %, die der Sidecar selbst angibt. Genau dann ist
  // ein zweiter Lauf das Richtige, und dieser Test hält beide Seiten
  // fest, damit die Ausnahme nicht zur Regel wird.
  const sub = { video_relpath: 'a/b.mp4', detections: [] };
  assert.equal(clipReadiness(sub, EMPTY_SIDECAR).rebuildable, false);
  assert.equal(clipReadiness(TRIGGER_ITEM, EMPTY_SIDECAR).rebuildable, true);
});

test('die grobe Spur beziffert, was an ihr grob ist', () => {
  const r = clipReadiness(TRIGGER_ITEM, null);
  assert.equal(factValue(r, 'Kästen'), '2');
  assert.equal(factValue(r, 'sichtbar'), 'nur pausiert');
  assert.equal(factValue(r, 'bester Wert'), '57 %');
  assert.equal(r.rebuildable, true);
});

test('der laufende Abruf ist sichtbar, der fertige Clip stumm', () => {
  // Die eine Stelle, an der „kein Banner" die richtige Antwort ist —
  // und die eine, an der es vorher fälschlich dieselbe war.
  assert.equal(clipReadiness(TRIGGER_ITEM, SIDECAR).note, null);
  assert.ok(clipReadiness(TRIGGER_ITEM, undefined).note);
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
