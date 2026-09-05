// Ein gebogener Rand muss auf beiden Seiten derselbe Rand sein.
//
// Zonen und Masken duerfen `curves` tragen — je Segment einen
// quadratischen Bezier-Kontrollpunkt. Die PIPELINE tastet die Kurve ab,
// bevor sie eine Erkennung gegen die Form prueft
// (app/app/mask_zones.py::flatten_poly_points). Auf der Anzeigeseite las
// jeder Leser nur `points`, also wurde eine gebogene Maske als GERADES
// Vieleck gezeichnet — und die spielereigene Pruefung „liegt dieser
// Kasten in einer Maske" fragte nach einem anderen Vieleck als dem, das
// die Erkennung tatsaechlich gefiltert hat.
//
// Das Overlay erklaert, warum etwas ausgeschlossen wurde. Eine Maske in
// der falschen Form erklaert die falsche Sache.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  POLY_CURVE_SAMPLES,
  flattenPolyPoints,
  normalizePolygon,
} from '../polygon-source.js';

const CAM = { main_w: 1920, main_h: 1080 };

test('eine gerade Form bleibt unveraendert', () => {
  const pts = [
    { x: 0, y: 0 },
    { x: 10, y: 0 },
    { x: 10, y: 10 },
  ];
  assert.deepEqual(flattenPolyPoints({ points: pts }), pts);
  assert.deepEqual(flattenPolyPoints({ points: pts, curves: [null, null, null] }), pts);
});

test('die alte blanke Liste ist bereits flach', () => {
  const pts = [{ x: 1, y: 2 }];
  assert.equal(flattenPolyPoints(pts), pts);
});

test('ein gebogenes Segment bekommt Zwischenpunkte', () => {
  const poly = {
    points: [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
    ],
    curves: [{ x: 50, y: 100 }, null],
  };
  const out = flattenPolyPoints(poly);
  // Zwei Eckpunkte plus die Abtastung EINES gebogenen Segments.
  assert.equal(out.length, 2 + POLY_CURVE_SAMPLES);
  // Der Scheitel der Kurve muss deutlich von der Sehne abweichen —
  // sonst waere die Abtastung wirkungslos und der Test tautologisch.
  const maxY = Math.max(...out.map((p) => p.y));
  assert.ok(maxY > 25, `die Kurve beult nicht aus: ${maxY}`);
});

test('die Bezier-Formel ist dieselbe wie auf der Python-Seite', () => {
  // B(t) = (1-t)^2*p0 + 2(1-t)t*cp + t^2*p1, gleiche Schrittweite
  // t = k/(samples+1). Ein Punkt reicht als Beleg, wenn er exakt sitzt.
  const poly = {
    points: [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
    ],
    curves: [{ x: 50, y: 100 }, null],
  };
  const out = flattenPolyPoints(poly, 1);
  // k=1, samples=1 → t = 0.5 → x = 50, y = 0.25*0 + 0.5*100 + 0.25*0 = 50
  assert.deepEqual(out[1], { x: 50, y: 50 });
});

test('normalizePolygon liefert die Punkte bereits abgeflacht', () => {
  // DER PUNKT: der Zeichner und die Masken-Pruefung bekommen beide die
  // Kurve, ohne dass einer von beiden von `curves` wissen muss.
  const poly = {
    points: [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
    ],
    curves: [{ x: 50, y: 100 }, null],
    source_w: 1920,
    source_h: 1080,
  };
  const out = normalizePolygon(poly, CAM);
  assert.equal(out.points.length, 2 + POLY_CURVE_SAMPLES);
  assert.equal(out.source_w, 1920);
});

test('normalizePolygon laesst eine gerade Form in Ruhe', () => {
  const poly = { points: [{ x: 1, y: 1 }, { x: 2, y: 2 }, { x: 3, y: 1 }] };
  assert.deepEqual(normalizePolygon(poly, CAM).points, poly.points);
});

test('kaputte Eingaben sind kein Absturz', () => {
  assert.deepEqual(flattenPolyPoints(null), []);
  assert.deepEqual(flattenPolyPoints({}), []);
  assert.deepEqual(flattenPolyPoints({ points: [{ x: 0, y: 0 }] }), [{ x: 0, y: 0 }]);
  // Ein Kontrollpunkt ohne Zahlen wird uebersprungen, nicht geraten.
  const poly = { points: [{ x: 0, y: 0 }, { x: 10, y: 0 }], curves: [{ x: 'a' }, null] };
  assert.equal(flattenPolyPoints(poly).length, 2);
});
