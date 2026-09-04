// Scrubbing has to be usable, and it was not.
//
// „Ich kann den Button auch total nur extrem buggy hin- und herschieben.
// Der schiebt irgendwie, es dauert fünf Sekunden, bis ich überhaupt den
// Play Button hin- und herschieben kann mit der Maus. … Also mit flüssig
// und angenehm im Video bisschen hin- und herskippen … überhaupt noch
// nicht gegeben."
//
// Cause: attachScrub called onSeek on EVERY pointermove, and each of
// those set video.currentTime on an inter-coded MP4. The seeks queued
// and the picture arrived seconds behind the finger.
//
// Fix: the drag moves the marker and a sprite-sheet thumbnail; the video
// is seeked exactly once, on release. These tests pin both halves.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { attachScrub, pctFromRect, timeFromRect } from '../_scrub.js';
import { bubbleWidth, clampLeft, tileIndexAt, tileStyle } from '../_preview.js';

/** Minimal element that records listeners and answers pointer capture. */
function stubEl() {
  const on = {};
  const captured = new Set();
  return {
    on,
    addEventListener: (ev, fn) => {
      on[ev] = fn;
    },
    removeEventListener: (ev) => {
      delete on[ev];
    },
    setPointerCapture: (id) => captured.add(id),
    releasePointerCapture: (id) => captured.delete(id),
    hasPointerCapture: (id) => captured.has(id),
  };
}

/** A 200 px rail starting at x=100, over a 10 s clip. */
function harness(extra = {}) {
  const el = stubEl();
  const seeks = [];
  const previews = [];
  attachScrub(el, {
    getRect: () => ({ left: 100, width: 200 }),
    getDuration: () => 10,
    onSeek: (t) => seeks.push(t),
    onPreview: (t, x, phase) => previews.push({ t, x, phase }),
    ...extra,
  });
  return { el, seeks, previews };
}

const down = (el, x) => el.on.pointerdown({ clientX: x, pointerId: 1, preventDefault() {} });
const move = (el, x) => el.on.pointermove({ clientX: x, pointerId: 1 });
const up = (el, x) => el.on.pointerup({ clientX: x, pointerId: 1 });

// ── the drag does not decode video ───────────────────────────────────

test('ein Zug über die Schiene löst GENAU EINEN Sprung aus', () => {
  const { el, seeks } = harness();
  down(el, 100);
  for (let x = 100; x <= 300; x += 4) move(el, x);
  up(el, 300);
  assert.equal(seeks.length, 1, `${seeks.length} Sprünge — jeder davon dekodiert das Video neu`);
  assert.equal(seeks[0], 10);
});

test('jede Zwischenposition erreicht dagegen die Vorschau', () => {
  const { el, previews } = harness();
  down(el, 100);
  move(el, 150);
  move(el, 200);
  up(el, 200);
  const moves = previews.filter((p) => p.phase === 'move');
  assert.equal(moves.length, 2, 'die Vorschau muss dem Finger folgen, nicht der Dekoder');
});

test('die Vorschau bekommt Start, Bewegung und Ende als eigene Phasen', () => {
  const { el, previews } = harness();
  down(el, 120);
  move(el, 160);
  up(el, 160);
  assert.deepEqual(
    previews.map((p) => p.phase),
    ['start', 'move', 'end'],
  );
});

test('ein Klick ohne Bewegung springt trotzdem — einmal', () => {
  const { el, seeks } = harness();
  down(el, 200);
  up(el, 200);
  assert.deepEqual(seeks, [5]);
});

test('die x-Angabe der Vorschau ist schienenrelativ, nicht fensterrelativ', () => {
  // Sonst sitzt die Blase bei einem zentrierten Player weit rechts
  // ausserhalb der Schiene, an der sie geklemmt werden soll.
  const { el, previews } = harness();
  down(el, 150);
  assert.equal(previews[0].x, 50);
});

// ── the pause/resume contract survived the rewrite ───────────────────

test('ein Zug pausiert - und bleibt pausiert', () => {
  // Vorher lief das Video nach dem Loslassen weiter. Damit war die Pause
  // unsichtbar: das Bild sprang an die neue Stelle und lief sofort davon,
  // bevor man draufschauen konnte.
  const events = [];
  const { el } = harness({
    isPlaying: () => true,
    onPause: () => events.push('pause'),
    onResume: () => events.push('resume'),
  });
  down(el, 120);
  up(el, 160);
  assert.deepEqual(events, ['pause'], 'nach dem Zug darf nichts von selbst weiterlaufen');
});

test('ein Druck auf den laufenden Regler pausiert wirklich', () => {
  // DER FEHLER, den dieser Test festhaelt: onDown pausiert bereits, und
  // ein Umschalter, der danach den VIDEO-Zustand liest, sieht "pausiert"
  // und startet neu - der Knopf hob seine eigene Pause auf und wirkte
  // tot.
  const events = [];
  let taps = null;
  const { el } = harness({
    isPlaying: () => true,
    onPause: () => events.push('pause'),
    onTap: (wasPlaying) => {
      taps = wasPlaying;
    },
  });
  down(el, 150);
  up(el, 150);
  assert.deepEqual(events, ['pause']);
  assert.equal(taps, true, 'der Umschalter muss erfahren, dass vorher gespielt wurde');
});

test('ein Druck auf den pausierten Regler meldet false', () => {
  let taps = null;
  const { el } = harness({ isPlaying: () => false, onTap: (w) => (taps = w) });
  down(el, 150);
  up(el, 150);
  assert.equal(taps, false, 'sonst startet ein Druck im Stillstand die Wiedergabe nie');
});

test('ein Zug im pausierten Zustand startet die Wiedergabe nicht', () => {
  const events = [];
  const { el } = harness({
    isPlaying: () => false,
    onPause: () => events.push('pause'),
    onResume: () => events.push('resume'),
  });
  down(el, 120);
  up(el, 160);
  assert.deepEqual(events, []);
});

test('ohne Dauer wird nichts gesprungen und nichts vorgeschaut', () => {
  const el = stubEl();
  const seeks = [];
  attachScrub(el, {
    getRect: () => ({ left: 0, width: 200 }),
    getDuration: () => 0,
    onSeek: (t) => seeks.push(t),
  });
  down(el, 100);
  up(el, 100);
  assert.deepEqual(seeks, []);
});

// ── the pure geometry the bubble is built from ───────────────────────

test('die Kachel folgt der Zeit über das Intervall des Streifens', () => {
  const geo = { count: 20, interval_s: 0.5 };
  assert.equal(tileIndexAt(0, geo, 10), 0);
  assert.equal(tileIndexAt(2.4, geo, 10), 4);
  assert.equal(tileIndexAt(9.9, geo, 10), 19);
});

test('die letzte Kachel ist die Obergrenze', () => {
  // Ein Streifen mit geweiteter Schrittweite deckt etwas mehr ab als der
  // Clip lang ist; ein Zug ans Ende landet sonst hinter dem Blatt.
  const geo = { count: 8, interval_s: 1 };
  assert.equal(tileIndexAt(99, geo, 8), 7);
  assert.equal(tileIndexAt(-3, geo, 8), 0);
});

test('ohne interval_s rechnet die Kachel aus Dauer und Anzahl', () => {
  // Ein Blatt, das vor diesem Feld geschrieben wurde, bleibt benutzbar.
  assert.equal(tileIndexAt(5, { count: 10 }, 10), 5);
});

test('eine Kachel füllt das Fenster genau', () => {
  const geo = { cols: 4, rows: 3, count: 12, tile_w: 240, tile_h: 135 };
  const st = tileStyle(5, geo, 200); // Spalte 1, Zeile 1
  assert.equal(st.width, '200px');
  assert.equal(st.height, '113px');
  assert.equal(st.backgroundSize, '800px 338px');
  assert.equal(st.backgroundPosition, '-200px -113px');
});

test('die erste Kachel steht im Ursprung', () => {
  const geo = { cols: 4, rows: 3, count: 12, tile_w: 240, tile_h: 135 };
  assert.equal(tileStyle(0, geo, 200).backgroundPosition, '-0px -0px');
});

test('die Blase verlässt die Schiene an keinem Ende', () => {
  assert.equal(clampLeft(0, 400, 200), 0, 'am linken Rand');
  assert.equal(clampLeft(400, 400, 200), 200, 'am rechten Rand');
  assert.equal(clampLeft(200, 400, 200), 100, 'in der Mitte zentriert');
});

test('die Blase ist gross, aber nie breiter als die Schiene', () => {
  // „bitte thumb größer im verhältnis!" — 200 px, wo Platz ist.
  assert.equal(bubbleWidth(1200), 200, 'am PC der volle Wunschwert');
  assert.ok(bubbleWidth(359) < 359, 'auf einem 375-px-Telefon passt sie hinein');
  assert.ok(bubbleWidth(359) >= 200 === false || bubbleWidth(359) === 200);
  // Und eine Untergrenze, damit sie nicht zur Briefmarke wird: unter
  // ~136 px Schiene ist die Blase breiter als ihre Schiene, was clampLeft
  // links anschlägt. Das ist bewusst — ein Vorschaubild von 60 px zeigt
  // keinen Vogel mehr, und so schmal wird keine echte Schiene.
  assert.equal(bubbleWidth(60), 120, 'die Untergrenze gilt');
});

// ── the fractions the whole thing rests on ───────────────────────────

test('eine Position ausserhalb der Schiene wird geklemmt', () => {
  assert.equal(pctFromRect(50, { left: 100, width: 200 }), 0);
  assert.equal(pctFromRect(999, { left: 100, width: 200 }), 1);
});

test('eine Schiene ohne Breite löst nicht alles auf den linken Rand auf', () => {
  assert.equal(pctFromRect(150, { left: 100, width: 0 }), null);
  assert.equal(timeFromRect(150, { left: 100, width: 0 }, 10), null);
});

// ── der Griff ist zugleich der Play-Knopf ─────────────────────────────
//
// „Timeline button mit play in gross fehlt noch" — der Zeiger markiert
// nicht nur die Stelle, er startet und stoppt auch. Damit muss ein Druck
// ohne Bewegung etwas anderes bedeuten als ein Zug.

test('ein Druck ohne Bewegung schaltet um, statt auf sich selbst zu springen', () => {
  const taps = [];
  const el = stubEl();
  const seeks = [];
  attachScrub(el, {
    getRect: () => ({ left: 100, width: 200 }),
    getDuration: () => 10,
    onSeek: (t) => seeks.push(t),
    onTap: () => taps.push(1),
  });
  down(el, 180);
  up(el, 180);
  assert.equal(taps.length, 1, 'der Druck hat nicht umgeschaltet');
  assert.deepEqual(seeks, [], 'und er darf nicht zusätzlich springen');
});

test('ein Wackeln von zwei Pixeln bleibt ein Druck', () => {
  const taps = [];
  const el = stubEl();
  attachScrub(el, {
    getRect: () => ({ left: 100, width: 200 }),
    getDuration: () => 10,
    onSeek: () => {},
    onTap: () => taps.push(1),
  });
  down(el, 180);
  move(el, 182);
  up(el, 182);
  assert.equal(taps.length, 1, 'eine Hand hält nie ganz still');
});

test('ein echter Zug springt und schaltet NICHT um', () => {
  const taps = [];
  const el = stubEl();
  const seeks = [];
  attachScrub(el, {
    getRect: () => ({ left: 100, width: 200 }),
    getDuration: () => 10,
    onSeek: (t) => seeks.push(t),
    onTap: () => taps.push(1),
  });
  down(el, 120);
  move(el, 200);
  up(el, 200);
  assert.deepEqual(taps, []);
  assert.deepEqual(seeks, [5]);
});

test('ohne onTap springt ein Druck weiterhin — die Schiene ist kein Knopf', () => {
  const { el, seeks } = harness();
  down(el, 200);
  up(el, 200);
  assert.deepEqual(seeks, [5]);
});

test('das Umschalten überstimmt das Fortsetzen des Zuges', () => {
  // Sonst pausiert der Druck (weil gespielt wurde), schaltet um — und
  // der resume des Zuges startet gleich wieder. Der Knopf täte nichts.
  const events = [];
  const el = stubEl();
  attachScrub(el, {
    getRect: () => ({ left: 100, width: 200 }),
    getDuration: () => 10,
    onSeek: () => {},
    onTap: () => events.push('toggle'),
    isPlaying: () => true,
    onPause: () => events.push('pause'),
    onResume: () => events.push('resume'),
  });
  down(el, 180);
  up(el, 180);
  assert.deepEqual(events, ['pause', 'toggle'], 'kein resume nach dem Umschalten');
});

// ── die Vorschau flackert nicht bei einem Druck ───────────────────────
//
// „wenn ich nur kurz drauf drücke, darf das Thumbnail noch nicht
// angezeigt werden. Es gibt 'n komischen Flackereffekt." Ein Druck auf
// den Griff ist ein Play/Pause-Druck und lief trotzdem durch show().

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const PREVIEW_SRC = readFileSync(fileURLToPath(new URL('../_preview.js', import.meta.url)), 'utf8');
const TL_CSS = readFileSync(
  fileURLToPath(new URL('../../../../css/36b-vplayer-timeline.css', import.meta.url)),
  'utf8',
);

test('es gibt eine Haltezeit, bevor die Vorschau erscheint', () => {
  const m = PREVIEW_SRC.match(/const HOLD_MS = (\d+)/);
  assert.ok(m, 'keine Haltezeit definiert');
  const ms = Number(m[1]);
  assert.ok(ms >= 200, `${ms} ms ist kurz genug, dass ein Druck sie noch auslöst`);
  assert.ok(ms <= 400, `${ms} ms fühlt sich wie Warten an`);
});

test('show() zeigt nichts sofort, sondern stellt den Wecker', () => {
  const fn = PREVIEW_SRC.slice(PREVIEW_SRC.indexOf('    show: (x, t) =>'));
  const body = fn.slice(0, fn.indexOf('    moveTo:'));
  assert.match(body, /setTimeout\(reveal, HOLD_MS\)/);
  assert.equal(/shown = true/.test(body), false, 'show() darf nicht selbst sichtbar schalten');
});

test('ein echter Zug zeigt sie sofort, ohne die Haltezeit abzuwarten', () => {
  const m = PREVIEW_SRC.match(/const REVEAL_DRAG_PX = (\d+)/);
  assert.ok(m, 'kein Schwellwert für „schon am Ziehen"');
  // Über der 4-px-Toleranz, mit der _scrub.js Druck von Zug trennt —
  // sonst zeigt genau das Wackeln die Vorschau, das noch ein Druck ist.
  assert.ok(Number(m[1]) > 4);
  const fn = PREVIEW_SRC.slice(PREVIEW_SRC.indexOf('    moveTo: (x, t) =>'));
  assert.match(fn.slice(0, 400), /REVEAL_DRAG_PX\) reveal\(\)/);
});

test('die Ausblendzeit im Code und in der CSS sind dieselbe Zahl', () => {
  // hide() nimmt das Element erst nach FADE_MS aus dem Layout. Läuft die
  // CSS länger, wird die Blende mittendrin abgeschnitten.
  const js = Number(PREVIEW_SRC.match(/const FADE_MS = (\d+)/)[1]);
  const rule = TL_CSS.slice(TL_CSS.indexOf('.vp-scrub-preview {'));
  const css = Number(rule.slice(0, rule.indexOf('}')).match(/opacity (\d+)ms/)[1]);
  assert.equal(js, css, `JS wartet ${js} ms, die CSS blendet ${css} ms`);
});

test('die Blende hat einen eigenen Zustand statt hidden umzuschalten', () => {
  // `hidden` lässt sich nicht animieren; ohne eine Klasse springt sie.
  assert.match(TL_CSS, /\.vp-scrub-preview\.is-on/);
  assert.match(PREVIEW_SRC, /classList\.add\('is-on'\)/);
  assert.match(PREVIEW_SRC, /classList\.remove\('is-on'\)/);
});
