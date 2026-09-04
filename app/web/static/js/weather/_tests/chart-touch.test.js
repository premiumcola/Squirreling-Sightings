// The weather chart has to be readable with a finger on it.
//
// „Bitte lass es nicht zu dass ich das markiere und zeige die werte am
// ios neben dem finger an sonst sieht man nie was weil der finger es
// verdeckt!"
//
// Two separate defects in one gesture. Dragging across the plot on iOS
// started a TEXT SELECTION — the axis labels and the legend are real
// text in the SVG — and the system callout ("Kopieren | Nachschlagen |
// Übersetzen") landed across the chart mid-drag. And the readout was
// placed 12 px right / 6 px below-ish the pointer, which is fine under a
// mouse arrow and completely under a fingertip.
//
// Source-text tests: the placement is a private function inside a module
// that binds DOM at import, and what matters is the contract, not the
// arithmetic — that touch gets its own offset at all, and that the
// offset actually clears a finger.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const HOVER = readFileSync(
  fileURLToPath(new URL('../stats-chart/_hover.js', import.meta.url)),
  'utf8',
);
const CSS = readFileSync(
  fileURLToPath(new URL('../../../css/23-weather-3.css', import.meta.url)),
  'utf8',
);

/** The `.ws-stats-chart-wrap` declaration block. */
function wrapRule() {
  const i = CSS.indexOf('.ws-stats-chart-wrap {');
  assert.ok(i >= 0, 'the chart wrapper rule is gone');
  return CSS.slice(i, CSS.indexOf('}', i));
}

// ── nothing on the chart is text to select ───────────────────────────

test('das Diagramm lässt sich nicht markieren', () => {
  const rule = wrapRule();
  assert.match(rule, /(^|\s)user-select:\s*none/m);
  assert.match(rule, /-webkit-user-select:\s*none/);
});

test('und iOS wirft keine Auswahl-Sprechblase darüber', () => {
  // user-select alone still lets the long-press begin; this is the
  // property that suppresses the callout itself.
  assert.match(wrapRule(), /-webkit-touch-callout:\s*none/);
});

test('ein Fingerdruck unterdrückt zusätzlich die Standardgeste', () => {
  const down = HOVER.slice(HOVER.indexOf("addEventListener('pointerdown'"));
  const body = down.slice(0, down.indexOf('});') + 3);
  assert.match(body, /pointerType === 'touch'/);
  assert.match(body, /preventDefault\(\)/);
});

// ── the values are not under the hand ────────────────────────────────

test('Maus und Finger bekommen verschiedene Abstände', () => {
  assert.match(HOVER, /_TIP_OFFSET\s*=/);
  const block = HOVER.slice(HOVER.indexOf('const _TIP_OFFSET'));
  assert.match(block.slice(0, 200), /mouse:/);
  assert.match(block.slice(0, 200), /touch:/);
});

test('der Finger-Abstand ist grösser als eine Fingerkuppe', () => {
  // Eine Fingerkuppe misst rund 45 px. Ein Kasten, der 20 px über dem
  // Berührpunkt sitzt, liegt immer noch unter der Hand.
  const m = HOVER.match(/touch:\s*\{\s*x:\s*(-?\d+),\s*y:\s*(-?\d+)/);
  assert.ok(m, 'kein Touch-Abstand gefunden');
  assert.ok(
    Math.abs(Number(m[2])) >= 45,
    `der Kasten steht nur ${m[2]} px vom Finger ab — das verdeckt ihn weiter`,
  );
});

test('der Kasten weicht nach oben aus, nicht nach unten', () => {
  const m = HOVER.match(/touch:\s*\{\s*x:\s*(-?\d+),\s*y:\s*(-?\d+)/);
  assert.ok(Number(m[2]) < 0, 'unterhalb des Fingers liegt die Hand');
});

test('die Platzierung kennt den Zeigertyp überhaupt', () => {
  const fn = HOVER.slice(HOVER.indexOf('function _placeTip'));
  const body = fn.slice(0, fn.indexOf('\n}'));
  assert.match(body, /pointerType/, 'sonst gilt der Mausabstand auch für den Finger');
});

test('der Kasten bleibt im Diagramm geklemmt', () => {
  // Sonst schiebt ihn der neue negative Abstand am linken Rand hinaus.
  const fn = HOVER.slice(HOVER.indexOf('function _placeTip'));
  const body = fn.slice(0, fn.indexOf('\n}'));
  assert.match(body, /Math\.max\(4/);
  assert.match(body, /Math\.min\(/);
});
