// ─── vplayer/_tests/back-gesture.test.js ───────────────────────────────────
// „Zudem will ich aus dem player mit der iphone typischen am bildschirm
// seitlich zurück-wisch-bewegung raus gehen können."
//
// Only from the EDGE. Anywhere else on the picture a horizontal drag
// already means prev/next, and a gesture that stole those would be a
// worse bug than the one it fixed.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installBackGesture, isBackSwipe } from '../_back-gesture.js';

test('a firm drag from the left edge is "back"', () => {
  assert.equal(isBackSwipe(8, 90, 10), true);
  assert.equal(isBackSwipe(0, 64, 0), true);
});

test('the same drag from the middle of the picture is not', () => {
  // That one belongs to prev/next — see mediaview/keyboard.js.
  assert.equal(isBackSwipe(180, 120, 5), false);
  assert.equal(isBackSwipe(25, 120, 5), false);
});

test('a short tug is not a gesture', () => {
  assert.equal(isBackSwipe(5, 30, 2), false);
});

test('a leftward drag from the left edge is not "back"', () => {
  assert.equal(isBackSwipe(5, -90, 4), false);
});

test('a diagonal is someone scrolling, not going back', () => {
  assert.equal(isBackSwipe(5, 80, 70), false);
  assert.equal(isBackSwipe(5, 80, 200), false);
});

// ── Blättern: der Verlaufseintrag wird übergeben, nicht abgeräumt ─────────
// „drück dann auf den rechten Pfeil … springt es zurück in die Übersicht."
// Der alte Player räumte seinen Eintrag mit history.back() ab — asynchron.
// Das popstate kam erst an, als der neue Player schon lauschte, und der
// schloss sich darauf. Die Umgebung hier spielt genau diese Reihenfolge
// nach: back() stellt ein popstate in eine Warteschlange, flush() liefert.

function fakeHistory() {
  const listeners = new Set();
  const queued = [];
  const h = {
    depth: 0,
    pushState() {
      h.depth += 1;
    },
    back() {
      h.depth -= 1;
      queued.push('popstate');
    },
  };
  globalThis.history = h;
  globalThis.location = { href: 'http://cam.lan/' };
  globalThis.addEventListener = (ev, fn) => ev === 'popstate' && listeners.add(fn);
  globalThis.removeEventListener = (ev, fn) => ev === 'popstate' && listeners.delete(fn);
  return {
    h,
    flush() {
      while (queued.length) {
        queued.shift();
        for (const fn of [...listeners]) fn();
      }
    },
  };
}

test('replacing a player hands its history entry to the next one', () => {
  const env = fakeHistory();
  let firstClosed = 0;
  let secondClosed = 0;
  const first = installBackGesture(null, () => firstClosed++);
  assert.equal(env.h.depth, 1);

  // Weiter-Pfeil: der alte baut mit keepEntry ab, der neue übernimmt.
  const handover = first({ keepEntry: true });
  assert.equal(handover, true);
  installBackGesture(null, () => secondClosed++, { adopt: true });
  env.flush();

  assert.equal(env.h.depth, 1, 'ein Player auf dem Schirm, ein Eintrag im Verlauf');
  assert.equal(secondClosed, 0, 'der neue Player darf sich nicht selbst schließen');
  assert.equal(firstClosed, 0);
});

test('the OLD way — pop, then push — closes the new player (the bug)', () => {
  // Festgehalten, damit niemand „vereinfacht" und den Fehler zurückholt.
  const env = fakeHistory();
  let secondClosed = 0;
  const first = installBackGesture(null, () => {});
  first();
  installBackGesture(null, () => secondClosed++);
  env.flush();
  assert.equal(secondClosed, 1);
});

test('the back gesture on an adopted entry still closes the player', () => {
  const env = fakeHistory();
  let closed = 0;
  const first = installBackGesture(null, () => {});
  first({ keepEntry: true });
  installBackGesture(null, () => closed++, { adopt: true });
  env.h.back();
  env.flush();
  assert.equal(closed, 1);
  assert.equal(env.h.depth, 0);
});

test('a real close still takes the entry off the stack', () => {
  const env = fakeHistory();
  const teardown = installBackGesture(null, () => {});
  assert.equal(teardown(), false);
  assert.equal(env.h.depth, 0);
});
