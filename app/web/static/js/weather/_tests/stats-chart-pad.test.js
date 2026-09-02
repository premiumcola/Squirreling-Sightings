// Node tests for stats-chart/_pad.js — the per-render plot padding.
//
// The defect these pin down: a frozen { l: 42, r: 72 } spent 114 px of a
// 327 px phone wrapper on two rails, one of which (the left, in the
// panel's default all-lines mode) drew nothing at all.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  statsChartPad,
  approxTextWidth,
  axisTickLabels,
  clampTickLabelX,
  padToAttr,
  padFromAttr,
  PAD_T,
  PAD_B,
  PAD_FALLBACK,
} from '../stats-chart/_pad.js';

const PHONE = 327; // #weatherStatsChartWrap inside a 375 px viewport
const DESKTOP = 1300;

test('a rail with nothing to draw collapses to the x-tick overhang', () => {
  const pad = statsChartPad({ width: PHONE, yLabels: [], edgeLabels: [] });
  assert.equal(pad.l, 16);
  assert.equal(pad.r, 16);
  // The whole point: far more plot than the 213 px the old constant left.
  assert.ok(PHONE - pad.l - pad.r > 280, `plot was ${PHONE - pad.l - pad.r}`);
});

test('the rails never collapse below half an x-tick label', () => {
  // buildXTicks centres "12:00" ON pad.l and on pad.l + cw, so a zero
  // rail would clip the first and last time label.
  const pad = statsChartPad({ width: 120, yLabels: [], edgeLabels: [] });
  assert.ok(pad.l >= 16 && pad.r >= 16);
});

test('vertical padding is untouched by width', () => {
  for (const width of [120, PHONE, DESKTOP]) {
    const pad = statsChartPad({ width });
    assert.equal(pad.t, PAD_T);
    assert.equal(pad.b, PAD_B);
  }
});

test('the left rail grows to fit the y labels actually rendered', () => {
  const narrow = statsChartPad({ width: DESKTOP, yLabels: ['0', '5', '10'] });
  const wide = statsChartPad({ width: DESKTOP, yLabels: ['0 m', '12000 m', '24000 m'] });
  assert.ok(wide.l > narrow.l);
  // "24000 m" is ~42 px at 11 px — the OLD constant's 42 px rail minus
  // its own 6 px text offset left it starting off-canvas.
  assert.ok(wide.l > 42, `wide rail was ${wide.l}, must clear the old clip`);
});

test('the right rail fits the widest threshold label', () => {
  const pad = statsChartPad({ width: DESKTOP, edgeLabels: ['6 mm/h', '▲ 60 km/h'] });
  assert.ok(pad.r >= approxTextWidth('▲ 60 km/h', 10));
  assert.ok(pad.r < 72, 'and still asks for less than the old blanket 72 px');
});

test('on a phone the two rails are capped, on a desktop they are not', () => {
  const labels = { yLabels: ['24000 m'], edgeLabels: ['▲ 1000 J/kg', '3000 m'] };
  const phone = statsChartPad({ width: PHONE, ...labels });
  const desktop = statsChartPad({ width: DESKTOP, ...labels });
  assert.ok(phone.l + phone.r <= Math.round(PHONE * 0.34) + 1);
  // Same labels, more room: the desktop is free to grant them in full.
  assert.ok(desktop.l >= phone.l && desktop.r >= phone.r);
  assert.ok(desktop.l + desktop.r > phone.l + phone.r);
});

test('a capped rail still never drops under the tick floor', () => {
  const pad = statsChartPad({
    width: 90,
    yLabels: ['24000 m'],
    edgeLabels: ['▲ 1000 J/kg'],
  });
  assert.ok(pad.l >= 16 && pad.r >= 16);
});

test('missing or degenerate width does not produce a negative rail', () => {
  for (const width of [undefined, 0, -5, NaN]) {
    const pad = statsChartPad({ width, yLabels: ['24000 m'] });
    assert.ok(pad.l >= 16 && pad.r >= 16, `width ${width} -> ${JSON.stringify(pad)}`);
  }
  assert.deepEqual(statsChartPad(), { l: 16, r: 16, t: PAD_T, b: PAD_B });
});

test('axisTickLabels mirrors what buildValueAxis will draw', () => {
  const labels = axisTickLabels(0, 20, 'mm/h');
  assert.ok(labels.length > 1);
  for (const l of labels) assert.match(l, / mm\/h$/);
  // No unit configured -> bare numbers, no trailing space.
  assert.deepEqual(
    axisTickLabels(0, 1, '').map((s) => s.trim()),
    axisTickLabels(0, 1, ''),
  );
  // A non-finite range labels nothing rather than throwing.
  assert.deepEqual(axisTickLabels(NaN, 5, 'm'), []);
});

test('approxTextWidth scales with length and font size', () => {
  assert.ok(approxTextWidth('24000 m', 11) > approxTextWidth('0', 11));
  assert.ok(approxTextWidth('60 km/h', 11) > approxTextWidth('60 km/h', 10));
  assert.equal(approxTextWidth('', 11), 0);
  assert.equal(approxTextWidth(null, 11), 0);
});

test('approxTextWidth matches what the browser actually renders', () => {
  // getBBox() on the real chart, dark theme, app font — see the
  // calibration note in _pad.js. Within 12 % is enough for a rail, and
  // the estimate must never come in UNDER the real width.
  for (const [s, font, real] of [
    ['00:00', 11, 32.0],
    ['▲ 60 km/h', 10, 52.0],
    ['3000 m', 10, 38.4],
    ['6 mm/h', 10, 38.7],
  ]) {
    const est = approxTextWidth(s, font);
    assert.ok(est >= real - 0.5, `"${s}" estimated ${est.toFixed(1)} < real ${real}`);
    assert.ok(est <= real * 1.15, `"${s}" over-estimated ${est.toFixed(1)} vs ${real}`);
  }
});

test('a first/last tick label is nudged back inside the viewBox', () => {
  // "00:00" is 32 px, so centred on a 16 px rail it starts at exactly 0
  // and the wrapper's 10 px radius eats the first glyph.
  assert.ok(clampTickLabelX(16, '00:00', 11, 327) > 16);
  assert.ok(clampTickLabelX(311, '00:00', 11, 327) < 311);
  // A label with room is left exactly where its tick is.
  assert.equal(clampTickLabelX(160, '12:00', 11, 327), 160);
});

test('the clamp gives up rather than mangling a hopeless box', () => {
  // Narrower than the label itself: no position is inside, so leave it.
  assert.equal(clampTickLabelX(5, '31. Aug', 11, 10), 5);
});

test('the pad round-trips through the svg attribute', () => {
  const pad = statsChartPad({ width: PHONE, yLabels: ['24000 m'], edgeLabels: ['▲ 60 km/h'] });
  assert.deepEqual(padFromAttr(padToAttr(pad)), pad);
});

test('a missing or malformed pad attribute reads back as null', () => {
  for (const bad of [null, undefined, '', '1,2,3', 'a,b,c,d', '1,2,3,4,5']) {
    assert.equal(padFromAttr(bad), null, `${bad} should not parse`);
  }
  // …which is what lets statsChartPadOf fall back to a usable shape.
  assert.deepEqual(Object.keys(PAD_FALLBACK).sort(), ['b', 'l', 'r', 't']);
});
