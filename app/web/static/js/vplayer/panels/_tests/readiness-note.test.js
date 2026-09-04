// ─── vplayer/panels/_tests/readiness-note.test.js ──────────────────────────
// Sechs Zustände, sechs Gesichter — und ein gesunder Clip ohne Banner.
//
// Der Defekt, den diese Datei festnagelt, ist nicht „ein Zustand rendert
// falsch", sondern „alle rendern gleich": Die Zustände teilten sich zwei
// Banner-Stile und unterschieden sich nur im Satz. Ein Zustand, der bloß
// eine andere Farbe hat, ist beschriftet, nicht gestaltet. Der letzte
// Test hier ist deshalb der eigentliche: PAARWEISE verschieden, nicht
// „jeder rendert irgendwas".
//
// Das Setup muss als ERSTES stehen — siehe seinen eigenen Kopf.
import './_setup.js';

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { clipReadiness } from '../../_model/readiness.js';
import { renderReadinessNote } from '../_readiness-note.js';

/** Ein Host, mit dem der Mount zufrieden ist — ohne DOM dahinter. */
function fakeHost() {
  return {
    innerHTML: '',
    addEventListener() {},
    removeEventListener() {},
    querySelector() {
      return null;
    },
  };
}

/** Das gerenderte Banner für einen Clip + Sidecar-Zustand. */
function render(item, tracks) {
  const host = fakeHost();
  const note = renderReadinessNote(host, { item }, {});
  note.update(clipReadiness(item, tracks), item);
  const html = host.innerHTML;
  note.teardown();
  return html;
}

const TRIGGER_DETS = [
  { label: 'cat', score: 0.44, bbox: { x1: 96, y1: 188, x2: 214, y2: 286 } },
  { label: 'bird', score: 0.31, bbox: { x1: 372, y1: 128, x2: 442, y2: 186 } },
];

/** Wie _ffmpeg_clip.py den Stub schreibt, plus was _visible.py beim Lesen
 *  ergänzt (annotate_stage → stage_age_s, stage_stalled). */
const ENCODING = {
  event_id: 'e_enc',
  camera_id: 'cam_a',
  status: 'processing',
  stage: 'encoding',
  stage_since: '2026-09-04T14:12:49',
  stage_age_s: 42,
  stage_stalled: false,
  video_relpath: null,
  detections: TRIGGER_DETS,
};

const STALLED = { ...ENCODING, event_id: 'e_stall', stage_age_s: 512, stage_stalled: true };

const READY_ITEM = { event_id: 'e_ok', camera_id: 'cam_a', video_relpath: 'a/b.mp4' };

const COARSE_ITEM = { ...READY_ITEM, event_id: 'e_coarse', detections: TRIGGER_DETS };

const FAILED_ITEM = {
  event_id: 'e_fail',
  camera_id: 'cam_a',
  status: 'error',
  stage: 'failed',
  video_relpath: null,
  detections: [],
  encode_error: 'Ein Neustart hat die Verarbeitung unterbrochen.',
};

const SIDECAR = {
  schema: 4,
  built_at: '2026-08-30T14:35:02',
  gates: { min_confidence: 0.5, raw_floor: 0.2, miss_grace_s: 2 },
  tracks: [
    { _num: 1, label: 'bird', samples: [{ f: 1, t: 1, bbox: { x1: 1, y1: 1, x2: 9, y2: 9 } }] },
  ],
};

const EMPTY_SIDECAR = { ...SIDECAR, tracks: [] };

const EMPTY_ITEM = {
  ...READY_ITEM,
  event_id: 'e_empty',
  whole_clip: { detections: [{ label: 'bird', score: 0.33 }], frames: 120 },
};

test('ein gesunder Clip trägt gar kein Banner', () => {
  // Das ist das sechste Gesicht: die Abwesenheit. Eine Statuszeile über
  // einem Bild, dem nichts fehlt, ist Chrome ohne Aussage.
  assert.equal(render(READY_ITEM, SIDECAR), '');
});

test('wird umgewandelt: Phase, Kette und die Sekunden darin', () => {
  const html = render(ENCODING, null);
  assert.match(html, /is-building/);
  assert.match(html, /wird umgewandelt/, 'die Phase, nicht „wird verarbeitet"');
  assert.match(
    html,
    /vp-rn-clock">42 s</,
    'seit wann — die ganze Auskunft eines Spinners fehlt hier',
  );
  assert.match(html, /vp-rn-steps/, 'die Kette: drei Schritte, der zweite aktiv');
  assert.match(html, /class="is-done"><\/i><i class="is-now"/);
  assert.doesNotMatch(
    html,
    /data-act="reindex"/,
    'für einen Clip ohne Video gibt es nichts nachzubauen',
  );
});

test('hängt: dieselbe Kette, angehalten', () => {
  const html = render(STALLED, null);
  assert.match(html, /is-stalled/);
  assert.match(html, /hängt/);
  assert.match(html, /8 min/, 'die Dauer ist der Beleg, dass nichts mehr passiert');
  assert.match(html, /is-halted/, 'die restlichen Schritte laufen nicht weiter');
});

test('der Abruf läuft: sichtbar, und nicht wie „fertig" aussehend', () => {
  // Genau dieser Zustand rendert vorher NICHTS und war damit von einem
  // gesunden Clip nicht zu unterscheiden.
  const html = render(READY_ITEM, undefined);
  assert.notEqual(html, '');
  assert.match(html, /is-pending/);
  assert.match(
    html,
    /vp-rn-shimmer/,
    'ein unbestimmter Balken — kein Fortschritt, den es nicht gibt',
  );
});

test('nichts gefunden nennt die Schwelle und den besten Wert', () => {
  const html = render(EMPTY_ITEM, EMPTY_SIDECAR);
  assert.match(html, /is-empty/);
  assert.match(html, /50 %<\/b><span>Schwelle/, 'gates.min_confidence aus dem Sidecar');
  assert.match(html, /33 %<\/b><span>bester Live-Wert/, 'was der beste abgelehnte Kandidat hatte');
  assert.match(html, /14:35<\/b><span>geprüft/, 'built_at — der Beleg, dass der Lauf fertig ist');
  assert.match(html, /style="width:33%"/, 'der Balken steht vor der Marke …');
  assert.match(html, /style="left:50%"/, '… und die Marke ist die Schwelle');
  assert.doesNotMatch(
    html,
    /data-act="reindex"/,
    'derselbe Lauf mit denselben Gates fände dasselbe Nichts',
  );
});

test('grobe Spur sagt, was an ihr grob ist', () => {
  const html = render(COARSE_ITEM, null);
  assert.match(html, /is-coarse/);
  assert.match(html, /Auslöse-Bild/);
  assert.match(html, /2<\/b><span>Kästen/);
  assert.match(
    html,
    /nur pausiert<\/b><span>sichtbar/,
    'die Regel aus triggerBoxVisible, ausgesprochen',
  );
  assert.match(html, /data-act="reindex"/, 'hier lohnt der Nachbau — es gibt ein Video');
});

test('keine Quelle nennt den Grund und verschweigt den Knopf', () => {
  const html = render(FAILED_ITEM, null);
  assert.match(html, /is-missing/);
  assert.match(html, /fehlgeschlagen/);
  assert.match(html, /Ein Neustart hat die Verarbeitung unterbrochen/, 'encode_error, wörtlich');
  // /api/tracking/reindex/<id> antwortet ohne Video mit 404. Ein Knopf,
  // der nur scheitern kann, ist schlimmer als keiner.
  assert.doesNotMatch(html, /data-act="reindex"/);
});

test('die sechs Gesichter sind paarweise verschieden', () => {
  const faces = {
    ready: render(READY_ITEM, SIDECAR),
    building: render(ENCODING, null),
    pending: render(READY_ITEM, undefined),
    empty: render(EMPTY_ITEM, EMPTY_SIDECAR),
    coarse: render(COARSE_ITEM, null),
    missing: render(FAILED_ITEM, null),
  };
  const names = Object.keys(faces);
  for (const a of names) {
    for (const b of names) {
      if (a >= b) continue;
      assert.notEqual(faces[a], faces[b], `${a} und ${b} rendern identisch`);
    }
  }
});
