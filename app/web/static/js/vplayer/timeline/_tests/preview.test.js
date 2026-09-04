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

test('ein Zug während der Wiedergabe pausiert und läuft danach weiter', () => {
  const events = [];
  const { el } = harness({
    isPlaying: () => true,
    onPause: () => events.push('pause'),
    onResume: () => events.push('resume'),
  });
  down(el, 120);
  up(el, 160);
  assert.deepEqual(events, ['pause', 'resume']);
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
