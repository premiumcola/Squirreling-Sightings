// ─── vplayer/_tests/overlay-paint.test.js ──────────────────────────────────
// Was auf dem Bild landet, wenn die Spur gerade läuft.
//
// Der Defekt, den diese Datei festnagelt, war kein Rechenfehler: der
// Player hat die drei Overlay-Ebenen angelegt und für eine Aufnahme NIE
// hineingemalt. Vier Schalter standen über drei dauerhaft leeren
// Ebenen — „die buttons zur anwahl … haben keine funktion … bbox oder
// zones seh ich alles nicht". Ein Schalter kann nichts zeigen oder
// verbergen, was niemand zeichnet.
//
// Gepinnt wird deshalb genau das, was `_samplesAt` entscheidet: WELCHE
// Spur zum Zeitpunkt t überhaupt auf dem Bild ist, WELCHE Farbe sie
// trägt und WELCHE davon die Maske geschluckt hat. Der Rest der Datei
// fasst ein DOM an und gehört in den Screenshot-Harness, nicht hierhin.

import { test } from 'node:test';
import assert from 'node:assert/strict';

// Kein DOM-Stub nötig, und das ist der Punkt. Die Interpolation und die
// Dreistufung lagen in bbox-overlay/renderer.js, das beim Laden echtes
// DOM verdrahtet — dieser Test war ohne Browser nicht schreibbar. Sie
// liegen jetzt in core/track-sampling.js, und _samplesAt kommt ohne
// window, document oder localStorage aus.
import { _samplesAt } from '../_overlay-paint.js';

const SRC = { w: 640, h: 360 };

// Zwei Samples, dazwischen wird interpoliert. `source: 'detect'` ist
// wichtig: _interpolateTrackAt schneidet die Spur beim letzten echten
// Detect ab, ein reiner Vorhersage-Schwanz zählt nicht.
const BIRD = {
  _num: 1,
  color: '#22d3ee',
  label: 'bird',
  best_score: 0.71,
  samples: [
    { t: 1.0, bbox: { x1: 200, y1: 150, x2: 290, y2: 218 }, score: 0.63, source: 'detect' },
    { t: 3.0, bbox: { x1: 240, y1: 140, x2: 330, y2: 210 }, score: 0.71, source: 'detect' },
  ],
};

// Steht mit den Füßen (Unterkante, Mitte) bei x=100, y=300.
const CAT = {
  _num: 2,
  color: '#34d399',
  label: 'cat',
  best_score: 0.58,
  samples: [{ t: 2.0, bbox: { x1: 60, y1: 200, x2: 140, y2: 300 }, score: 0.52, source: 'detect' }],
};

const TRACKS = { tracks: [BIRD, CAT] };

// Rechteck um die Katzenfüße, in derselben Quellauflösung wie der Clip.
const FOOT_MASK = [
  {
    source_w: 640,
    source_h: 360,
    points: [
      { x: 20, y: 250 },
      { x: 170, y: 250 },
      { x: 170, y: 345 },
      { x: 20, y: 345 },
    ],
  },
];

test('vor der ersten Aufnahme der Spur ist nichts zu malen', () => {
  // Genau das war der Zustand, in dem der erste Screenshot entstand:
  // t = 0, beide Spuren noch nicht da — und leere Ebenen sehen exakt
  // aus wie ein Overlay, das nie zeichnet.
  assert.deepEqual(_samplesAt(TRACKS, 0, SRC, [], 0.4), []);
});

test('mitten in der Spur kommt sie mit Kasten zurück', () => {
  const out = _samplesAt(TRACKS, 2.0, SRC, [], 0.4);
  const bird = out.find((s) => s.trackNum === 1);
  assert.ok(bird, 'die Vogelspur läuft bei t=2 und muss gemalt werden');
  assert.ok(bird.raw.bbox, 'ohne Kasten gibt es nichts zu zeichnen');
});

test('die Farbe kommt aus dem Sidecar, nicht aus einer zweiten Palette', () => {
  // Lane, Objektzeile und Kasten sind dasselbe Subjekt. Sie stimmen nur
  // überein, solange alle drei `track.color` lesen — eine eigene
  // Farbwahl hier wäre genau die Abweichung, die niemand bemerkt.
  const out = _samplesAt(TRACKS, 2.0, SRC, [], 0.4);
  assert.equal(out.find((s) => s.trackNum === 1).colour, '#22d3ee');
  assert.equal(out.find((s) => s.trackNum === 2).colour, '#34d399');
});

test('eine Spur mit den Füßen in der Maske wird als maskiert gemeldet', () => {
  const out = _samplesAt(TRACKS, 2.0, SRC, FOOT_MASK, 0.4);
  assert.equal(out.find((s) => s.trackNum === 2).masked, true);
  assert.equal(out.find((s) => s.trackNum === 1).masked, false);
});

test('maskiert heißt grau gemalt, nicht weggelassen', () => {
  // „Warum wurde hier nichts erkannt" ist die Frage, für die das Overlay
  // da ist. Ein Kasten, den die Maske verschluckt hat, ist die Antwort —
  // er verschwindet nicht, er wird als gefiltert gezeichnet.
  const out = _samplesAt(TRACKS, 2.0, SRC, FOOT_MASK, 0.4);
  assert.equal(out.length, 2);
});

test('der Status ist die Dreistufung, keine Konstante', () => {
  // best_score 0.58 über der Schwelle, aktueller Wert 0.52 darüber →
  // bestätigt. Dieselbe Spur gegen eine höhere Schwelle → schwach oder
  // Ghost. Wenn hier immer dasselbe herauskäme, wäre die gestrichelte
  // Darstellung reine Dekoration.
  const low = _samplesAt(TRACKS, 2.0, SRC, [], 0.4).find((s) => s.trackNum === 2);
  const high = _samplesAt(TRACKS, 2.0, SRC, [], 0.9).find((s) => s.trackNum === 2);
  assert.equal(low.raw.status, 'confirmed');
  assert.notEqual(high.raw.status, 'confirmed');
});

test('die Spurnummer reist mit — sie verbindet Kasten, Lane und Zeile', () => {
  const out = _samplesAt(TRACKS, 2.0, SRC, [], 0.4);
  assert.deepEqual(
    out.map((s) => s.raw.track_num).sort(),
    [1, 2],
    'ohne track_num trägt der Kasten kein #N und niemand kann ihn der Zeile zuordnen',
  );
});

test('ohne Spuren ist die Liste leer statt undefiniert', () => {
  assert.deepEqual(_samplesAt(null, 2.0, SRC, [], 0.4), []);
  assert.deepEqual(_samplesAt({ tracks: [] }, 2.0, SRC, [], 0.4), []);
});
