// ─── vplayer/_tests/density.test.js ────────────────────────────────────────
// Die Dichteregel des Bildes — gepinnt als REGEL, nicht als Pixelstand.
//
// Der Defekt: auf 375 px ist das Bild ~211 px hoch, und Kästen,
// Namensschilder, Spur-Lanes, Vor-/Nachlaufband und Transportsteuerung
// haben es gleichzeitig bemalt. Auf 1440 px sah alles richtig aus, und
// genau daran hat es vier Releases überlebt.
//
// Was hier festgenagelt wird, sind zwei Sätze:
//
//   1. Ein Schild, das breiter ist als sein eigener Kasten, ist schlechter
//      als gar kein Schild. Es wird gekürzt, und wenn nichts mehr passt,
//      weggelassen.
//   2. Unterhalb einer messbaren Restbildhöhe liegt der Zeitstreifen nicht
//      mehr AUF dem Bild.
//
// KEINE PIXELZAHLEN AUS DEM BROWSER. Jede Behauptung unten ist in CSS-px
// formuliert und kommt ohne DOM aus — die Regel selbst ist der Vertrag,
// die Screenshots im Harness sind der Beweis, dass sie greift.
//
// VOR ALLEM: keine Breakpoint-Liste. Die Tests unten reichen NIE eine
// Viewport-Breite hinein. Dieselbe Enge entsteht in einem kurzen
// Desktop-Fenster bei 1440 px, und eine Regel, die das nicht sieht,
// löst das Problem nur auf dem Telefon.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  fitPlateText,
  plateTiers,
  plateWidthPx,
  mountStripHeight,
  VP_PLATE_H_PX,
  VP_PLATE_MIN_PICTURE_PX,
} from '../_density.js';
import { buildBoxSvg } from '../_overlay-svg.js';

/** Eine maskierte Katze mit Nummer — der längste reale Schildtext. */
const CAT = { status: 'masked', score: 0.52, label: 'cat', track_num: 2 };
/** Ein bestätigter Vogel: kein Marker, kein „gefiltert"-Anhang. */
const BIRD = { status: 'confirmed', score: 0.71, label: 'bird', track_num: 1 };

// ── Die Leiter ────────────────────────────────────────────────────────

test('die Leiter wird von Stufe zu Stufe kürzer und endet bei der Nummer', () => {
  const tiers = plateTiers(CAT, 'masked');
  assert.ok(tiers.length >= 2, 'ohne Stufen gibt es nichts zu kürzen');
  for (let i = 1; i < tiers.length; i++) {
    assert.ok(
      tiers[i].length < tiers[i - 1].length,
      `Stufe ${i} („${tiers[i]}") ist nicht kürzer als „${tiers[i - 1]}"`,
    );
  }
  assert.equal(tiers[tiers.length - 1], '#2', 'die letzte Sprosse ist die reine Spurnummer');
});

test('keine Stufe ist leer — leer heißt „kein Schild", nicht „eine Sprosse"', () => {
  for (const det of [CAT, BIRD, { score: 0.4 }, {}]) {
    for (const rung of plateTiers(det, 'confirmed')) assert.notEqual(rung, '');
  }
});

test('eine Erkennung ohne Spurnummer endet beim Statusmarker, nicht bei „#undefined"', () => {
  const tiers = plateTiers({ status: 'masked', score: 0.3, label: 'bird' }, 'masked');
  assert.equal(tiers[tiers.length - 1], '⊘');
  assert.equal(
    tiers.some((t) => t.includes('undefined') || t.includes('#N')),
    false,
  );
});

// ── Die eigentliche Regel ─────────────────────────────────────────────

test('ein Schild, das breiter wäre als sein Kasten, wird gekürzt', () => {
  // 61 CSS-px Kasten — die Katze aus dem Fixture auf einem 375-px-Bild.
  const label = fitPlateText(CAT, 'masked', { boxW: 61, boxH: 50, pictureH: 211 });
  assert.ok(label, 'ganz weglassen wäre hier zu viel — „#2" passt');
  assert.ok(
    plateWidthPx(label) <= 61,
    `„${label}" misst ${plateWidthPx(label)} px auf einem 61-px-Kasten`,
  );
  assert.ok(
    plateWidthPx(plateTiers(CAT, 'masked')[0]) > 61,
    'der Test wäre wertlos, wenn schon die volle Form passte',
  );
});

test('derselbe Kasten auf einem breiteren Bild behält mehr Text', () => {
  // KEINE Breakpoints: es ist derselbe Kasten in derselben Quelle, nur
  // größer auf dem Schirm. Genau das ist der Unterschied zwischen 375 px
  // und einem Desktopfenster — und zwischen einem hohen und einem
  // flachen Desktopfenster.
  const narrow = fitPlateText(CAT, 'masked', { boxW: 61, boxH: 50, pictureH: 211 });
  const wide = fitPlateText(CAT, 'masked', { boxW: 240, boxH: 130, pictureH: 520 });
  assert.ok(wide.length > narrow.length, `„${wide}" muss mehr sagen als „${narrow}"`);
});

test('passt nicht einmal die Nummer, bleibt der Kasten ohne Schild', () => {
  // Ein Schild, das über den Kasten hinausragt, verdeckt das Motiv
  // daneben. Kein Schild verdeckt nichts.
  assert.equal(fitPlateText(CAT, 'masked', { boxW: 12, boxH: 40, pictureH: 300 }), '');
});

test('ein Kasten, der flacher ist als sein eigenes Schild, kriegt nur die Nummer', () => {
  const tall = fitPlateText(BIRD, 'confirmed', { boxW: 400, boxH: 120, pictureH: 400 });
  const flat = fitPlateText(BIRD, 'confirmed', {
    boxW: 400,
    boxH: VP_PLATE_H_PX - 4,
    pictureH: 400,
  });
  assert.equal(tall, '#1 · Vogel · 71 %', 'genug Platz — volle Form');
  assert.equal(flat, '#1', 'ein Schild größer als sein Kasten ist Chrom, kein Etikett');
});

test('unter der Mindestbildhöhe wird gar kein Schild mehr gemalt', () => {
  const geom = { boxW: 400, boxH: 200 };
  assert.equal(fitPlateText(BIRD, 'confirmed', { ...geom, pictureH: 400 }), '#1 · Vogel · 71 %');
  assert.equal(
    fitPlateText(BIRD, 'confirmed', { ...geom, pictureH: VP_PLATE_MIN_PICTURE_PX - 1 }),
    '',
  );
});

test('ungemessene Geometrie kürzt nichts — sonst gäbe es Stummel ohne Grund', () => {
  // Ein Aufrufer, der den Schirm nicht vermessen hat, darf nicht
  // stillschweigend ein Kürzel bekommen.
  assert.equal(fitPlateText(BIRD, 'confirmed', {}), '#1 · Vogel · 71 %');
  assert.equal(
    fitPlateText(BIRD, 'confirmed', { boxW: 0, boxH: 0, pictureH: 0 }),
    '#1 · Vogel · 71 %',
  );
});

// ── Die Regel im Renderer, nicht nur in der reinen Funktion ───────────

test('der Renderer malt die gekürzte Form, nicht die volle', () => {
  // Kasten 90 Quelleinheiten breit, k=1.7 → 53 CSS-px. Das ist der
  // Vogel des Fixtures auf einem 375-px-Bild.
  const svg = buildBoxSvg(
    { ...BIRD, bbox: [200, 150, 90, 68] },
    { k: 1.7, frameW: 640, frameH: 360 },
  );
  assert.ok(svg.includes('>#1<'), 'nur die Nummer passt auf 53 px');
  assert.equal(svg.includes('Vogel'), false, 'die volle Form darf nicht durchrutschen');
});

test('das Schild weicht unter den Kasten aus, wenn oben die Schalter stehen', () => {
  // Eine Leiste über die ganze Breite: seitlich ausweichen hilft nicht,
  // also muss das Schild nach unten.
  const det = { ...BIRD, bbox: [200, 60, 400, 200] };
  const opts = { k: 1, frameW: 640, frameH: 360 };
  const plateY = (svg) => Number(/<rect [^>]*y="([-\d.]+)"[^>]*fill="rgba\(8,12,18/.exec(svg)[1]);
  const free = plateY(buildBoxSvg(det, opts));
  const dodged = plateY(buildBoxSvg(det, { ...opts, chrome: [{ x: 0, y: 0, w: 640, h: 44 }] }));
  assert.ok(free < 60, 'ohne Chrom sitzt das Schild über dem Kasten');
  assert.ok(dodged > 60, 'unter der Leiste ist es unlesbar — also unter die Kastenoberkante');
});

test('steht nur EIN Knopf im Weg, rückt das Schild an die andere Kastenecke', () => {
  // Der Fall der Katze links unten: der Zurück-Pfeil deckt die linke
  // obere Ecke, die rechte ist frei. Wegwerfen wäre hier Verschwendung.
  const det = { ...BIRD, bbox: [40, 120, 200, 90] };
  const opts = { k: 1, frameW: 640, frameH: 360 };
  const plateX = (svg) => Number(/<rect x="([-\d.]+)"[^>]*fill="rgba\(8,12,18/.exec(svg)[1]);
  const free = plateX(buildBoxSvg(det, opts));
  const shifted = plateX(buildBoxSvg(det, { ...opts, chrome: [{ x: 10, y: 90, w: 60, h: 80 }] }));
  assert.equal(free, 40, 'ohne Chrom bündig mit der linken Kastenkante');
  assert.ok(shifted > free, 'mit Chrom links rückt es an die rechte Kante');
  assert.ok(shifted + 26 <= 240 + 1, 'und bleibt dabei an seinem eigenen Kasten');
});

test('bleibt beides unter dem Chrom, wird das Schild ganz weggelassen', () => {
  // Ein Kasten, der mitten unter der Play-Scheibe sitzt: über ihm und
  // unter seiner Oberkante ist dieselbe Taste. Ein Schild dort ist ein
  // Schmierer auf dem Knopf, kein Etikett.
  const svg = buildBoxSvg(
    { ...BIRD, bbox: [150, 90, 90, 60] },
    { k: 1, frameW: 640, frameH: 360, chrome: [{ x: 120, y: 60, w: 160, h: 120 }] },
  );
  assert.ok(svg.includes('<rect'), 'der Kasten selbst bleibt — die Geometrie ist die Information');
  assert.equal(svg.includes('fill="rgba(8,12,18'), false, 'aber keine Plakette darunter');
});

// ── Der Zeitstreifen ──────────────────────────────────────────────────
//
// Hier stand eine gemessene Umschaltung: der Streifen durfte auf dem
// Bild liegen, solange er genug Bild uebrig liess. Sie funktionierte,
// und sie ist trotzdem weg — der Betreiber hat die Frage durch Hinsehen
// entschieden: "der play button in der abspiel timeline es soll genau so
// wie bei dir im bild aussehen!". Diese Kameras brennen ihre eigene Uhr
// in den unteren Bildrand, also stritten Schiene, Zeitangabe und
// 01/09/2026 15:46:02 um dieselben zwanzig Pixel — auf einem 1440-px-
// Fenster, wo rechnerisch reichlich Platz war. Platz war nie das
// Problem, das Bildmaterial war es.
//
// Geblieben ist die MESSUNG: die Hoehe des Streifens wird veroeffent-
// licht, damit die Bedienelemente auf dem Bild sich weiter auf das BILD
// zentrieren und nicht auf Bild-plus-Streifen.

/** Eine Buehne mit einem Streifen bekannter Hoehe. */
function _stubStage(stripH) {
  const props = {};
  return {
    style: {
      props,
      setProperty: (k, v) => {
        props[k] = v;
      },
      getPropertyValue: (k) => props[k] || '',
      removeProperty: (k) => {
        delete props[k];
      },
    },
    querySelector: () => (stripH == null ? null : { offsetHeight: stripH }),
  };
}

test('die Streifenhoehe wird an die Buehne gemeldet', () => {
  const stage = _stubStage(96);
  const h = mountStripHeight(stage);
  assert.equal(h.measure(), 96);
  assert.equal(stage.style.props['--vp-strip-h'], '96px');
});

test('ohne Streifen wird 0 gemeldet statt geraten', () => {
  const stage = _stubStage(null);
  assert.equal(mountStripHeight(stage).measure(), 0);
});

test('der Abbau raeumt die Eigenschaft wieder ab', () => {
  const stage = _stubStage(96);
  const h = mountStripHeight(stage);
  h.measure();
  h.teardown();
  assert.equal(stage.style.props['--vp-strip-h'], undefined);
});
