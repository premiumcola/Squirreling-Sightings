// ─── weather/_tests/chart-annotations.test.js ───────────────────────────
// weather/_chart-annotations.js — the data-anchored chart-marker state,
// geometry, hit-testing and rendering behind the "Kurven markieren"
// flow. The pointer-mode wiring that CALLS into handleChartTap lives in
// stats-chart/_hover.js and is covered separately in
// test_weather_chart_brush.py (same Python node-harness the rest of
// _hover.js's drag/hover coverage already uses); this file exercises
// _chart-annotations.js's own contract directly.
//
// Only handleChartTap's "no existing marker → open the phase picker"
// branch touches `document` (it creates the picker element) — a
// minimal local stub, same pattern weather/_tests/manual-events-delete
// .test.js already uses for its own module.
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

globalThis.document = {
  createElement() {
    const listeners = {};
    return {
      className: '',
      innerHTML: '',
      style: {},
      offsetWidth: 100,
      offsetHeight: 60,
      contains: () => false,
      remove() {},
      addEventListener(type, fn) {
        (listeners[type] = listeners[type] || []).push(fn);
      },
      _fire(type, ev) {
        (listeners[type] || []).forEach((fn) => fn(ev));
      },
    };
  },
  addEventListener() {},
  removeEventListener() {},
};

const {
  ANNOTATION_PHASES,
  annotationScreenPos,
  annotationsPayload,
  buildAnnotationMarkersSvg,
  chartAnnotations,
  handleChartTap,
  isMarkModeActive,
  nearestCurveAt,
  removeAnnotation,
  resetChartAnnotations,
  setMarkModeActive,
} = await import('../_chart-annotations.js');

// Two samples 5 min apart — precipitation rises 0→10 (its own y goes
// top→top, i.e. norm 0→1), visibility falls 8000→3000 (norm 1→0) — the
// two curves end up at OPPOSITE ends of the plot at the second sample,
// which is what makes "nearest curve to a click" unambiguous to assert.
function twoSamples() {
  return [
    { ts: '2026-08-29T14:00:00', values: { precipitation: 0, visibility: 8000 } },
    { ts: '2026-08-29T14:05:00', values: { precipitation: 10, visibility: 3000 } },
  ];
}

function geoFor(samples, fields, over = {}) {
  const tFirst = new Date(samples[0].ts).getTime();
  const tLast = new Date(samples[samples.length - 1].ts).getTime();
  return {
    samples,
    fields,
    pad: { l: 0, t: 0, b: 0 },
    cw: 100,
    ch: 100,
    tFirst,
    tSpan: tLast - tFirst,
    wrap: null,
    svg: null,
    ...over,
  };
}

function fakePickButton(phase) {
  const self = { dataset: { phase } };
  self.closest = (sel) => (sel === '.ws-chart-annot-pick' ? self : null);
  return self;
}

function fakeWrapWithPicker() {
  let mounted = null;
  return {
    appendChild(el) {
      mounted = el;
    },
    getBoundingClientRect() {
      return { left: 0, top: 0, width: 300, height: 200 };
    },
    querySelector(sel) {
      return sel === '.ws-chart-annot-picker' ? mounted : null;
    },
  };
}

beforeEach(() => resetChartAnnotations());

// ── geometry: which curve a click resolves to ────────────────────────────

test('nearestCurveAt picks the curve whose real value sits closest to the click', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['precipitation', 'visibility']);
  // At idx 1: precipitation's y is 0 (top, norm=1), visibility's y is
  // 100 (bottom, norm=0) — a click near the bottom must resolve to
  // visibility, near the top to precipitation.
  assert.equal(nearestCurveAt(geo.samples, geo.fields, 1, 95, geo.pad, geo.ch), 'visibility');
  assert.equal(nearestCurveAt(geo.samples, geo.fields, 1, 5, geo.pad, geo.ch), 'precipitation');
});

test('nearestCurveAt ignores a field with no finite value at that sample', () => {
  const samples = [
    { ts: '2026-08-29T14:00:00', values: { precipitation: 0 } },
    { ts: '2026-08-29T14:05:00', values: { precipitation: 10 } },
  ];
  const geo = geoFor(samples, ['precipitation', 'visibility']);
  assert.equal(nearestCurveAt(geo.samples, geo.fields, 1, 50, geo.pad, geo.ch), 'precipitation');
});

test('nearestCurveAt returns null when nothing in `fields` has a real range', () => {
  const single = [{ ts: '2026-08-29T14:00:00', values: { precipitation: 5 } }];
  const geo = geoFor(single, ['precipitation']);
  assert.equal(nearestCurveAt(geo.samples, geo.fields, 0, 50, geo.pad, geo.ch), null);
});

// ── geometry: where a placed marker currently sits on screen ────────────

test('annotationScreenPos places a marker exactly where its curve is drawn', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['precipitation', 'visibility']);
  const marker = { curve: 'visibility', ts: samples[1].ts, phase: 'kern' };
  const pos = annotationScreenPos(marker, geo);
  assert.ok(pos);
  assert.equal(pos.x, 100); // second (last) sample → x = pad.l + 1 * cw
  assert.equal(pos.y, 100); // visibility's own norm=0 at that sample → y = pad.t + ch
});

test('annotationScreenPos is null once its curve is hidden (legend toggle)', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['precipitation']); // visibility no longer visible
  const marker = { curve: 'visibility', ts: samples[1].ts, phase: 'kern' };
  assert.equal(annotationScreenPos(marker, geo), null);
});

test('annotationScreenPos is null once its sample has fallen out of the (zoomed) window', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['precipitation', 'visibility']);
  const marker = { curve: 'precipitation', ts: '2099-01-01T00:00:00', phase: 'aufbau' };
  assert.equal(annotationScreenPos(marker, geo), null);
});

// ── handleChartTap: add via the phase picker, remove via a second tap ───

test('a tap with no marker nearby opens the phase picker; picking a phase adds the marker', () => {
  const samples = twoSamples();
  const wrap = fakeWrapWithPicker();
  const geo = geoFor(samples, ['precipitation', 'visibility'], { wrap });
  let changes = 0;
  handleChartTap(geo, 1, 80, 95, () => changes++);
  assert.equal(changes, 0, 'nothing changes until a phase is actually picked');
  const picker = wrap.querySelector('.ws-chart-annot-picker');
  assert.ok(picker, 'the phase picker must be mounted on the wrap');
  picker._fire('click', { target: fakePickButton('kern') });
  assert.equal(changes, 1);
  assert.deepEqual(annotationsPayload(), [
    { curve: 'visibility', ts: samples[1].ts, phase: 'kern' },
  ]);
});

test('re-marking the same (curve, ts) replaces the phase instead of duplicating it', () => {
  const samples = twoSamples();
  const wrap = fakeWrapWithPicker();
  const geo = geoFor(samples, ['precipitation', 'visibility'], { wrap });
  handleChartTap(geo, 1, 80, 95, () => {});
  wrap.querySelector('.ws-chart-annot-picker')._fire('click', { target: fakePickButton('aufbau') });
  handleChartTap(geo, 1, 80, 95, () => {});
  wrap.querySelector('.ws-chart-annot-picker')._fire('click', { target: fakePickButton('kern') });
  assert.equal(chartAnnotations().length, 1);
  assert.equal(chartAnnotations()[0].phase, 'kern');
});

test('a tap ON an existing marker removes it instead of opening the picker', () => {
  const samples = twoSamples();
  const wrap = fakeWrapWithPicker();
  const geo = geoFor(samples, ['precipitation', 'visibility'], { wrap });
  handleChartTap(geo, 1, 80, 95, () => {});
  wrap.querySelector('.ws-chart-annot-picker')._fire('click', { target: fakePickButton('kern') });
  assert.equal(chartAnnotations().length, 1);
  // The marker's real screen pos is (100, 100) — see the
  // annotationScreenPos test above; tapping within the hit radius of it
  // must remove it, not place a second one.
  let changes = 0;
  handleChartTap(geo, 1, 100, 100, () => changes++);
  assert.equal(changes, 1);
  assert.deepEqual(annotationsPayload(), []);
});

test('removeAnnotation on a marker that was never placed is a silent no-op', () => {
  removeAnnotation('precipitation', '2026-08-29T14:00:00');
  assert.deepEqual(chartAnnotations(), []);
});

// ── mode + reset state ───────────────────────────────────────────────────

test('setMarkModeActive/isMarkModeActive round-trip', () => {
  assert.equal(isMarkModeActive(), false);
  setMarkModeActive(true);
  assert.equal(isMarkModeActive(), true);
});

test('resetChartAnnotations clears both the marker set and mark mode', () => {
  setMarkModeActive(true);
  const samples = twoSamples();
  const wrap = fakeWrapWithPicker();
  const geo = geoFor(samples, ['precipitation', 'visibility'], { wrap });
  handleChartTap(geo, 1, 80, 95, () => {});
  wrap.querySelector('.ws-chart-annot-picker')._fire('click', { target: fakePickButton('kern') });
  assert.equal(chartAnnotations().length, 1);
  resetChartAnnotations();
  assert.equal(isMarkModeActive(), false);
  assert.deepEqual(chartAnnotations(), []);
});

// ── rendering: one function, live (interactive) vs read-only ────────────

test('buildAnnotationMarkersSvg draws one glyph per placeable marker, in its curve colour', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['precipitation', 'visibility']);
  const svg = buildAnnotationMarkersSvg(
    [{ curve: 'visibility', ts: samples[1].ts, phase: 'kern' }],
    geo,
    { palette: { visibility: '#94a3b8' } },
  );
  assert.match(svg, /class="ws-chart-annot-layer"/);
  assert.match(svg, /#94a3b8/);
});

test('buildAnnotationMarkersSvg silently skips a marker with no current screen position', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['precipitation']); // visibility hidden
  const svg = buildAnnotationMarkersSvg(
    [{ curve: 'visibility', ts: samples[1].ts, phase: 'kern' }],
    geo,
  );
  assert.doesNotMatch(svg, /<circle/);
});

test('the read-only render (interactive:false) carries no removable "×"', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['visibility']);
  const svg = buildAnnotationMarkersSvg(
    [{ curve: 'visibility', ts: samples[1].ts, phase: 'kern' }],
    geo,
    { interactive: false },
  );
  assert.doesNotMatch(svg, />×</);
});

test('the live editing render (interactive:true) carries a removable "×"', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['visibility']);
  const svg = buildAnnotationMarkersSvg(
    [{ curve: 'visibility', ts: samples[1].ts, phase: 'kern' }],
    geo,
    { interactive: true },
  );
  assert.match(svg, />×</);
});

test('buildAnnotationMarkersSvg returns an empty string for an empty list', () => {
  assert.equal(buildAnnotationMarkersSvg([], geoFor(twoSamples(), ['precipitation'])), '');
});

test('the phase vocabulary is exactly aufbau/kern/abbau, in that order', () => {
  assert.deepEqual(ANNOTATION_PHASES, ['aufbau', 'kern', 'abbau']);
});

// ── ranges ──────────────────────────────────────────────────────────────
// A drag along a curve marks a STRETCH of it, not one sample. The gesture
// used to be discarded outright as an accidental pan, which is why the
// thing the operator reached for did nothing at all.

test('a drag marks a range and the payload carries its end', () => {
  const samples = twoSamples();
  const wrap = fakeWrapWithPicker();
  const geo = geoFor(samples, ['precipitation'], { wrap });
  handleChartTap(geo, 0, 80, 95, () => {}, 1);
  wrap.querySelector('.ws-chart-annot-picker')._fire('click', { target: fakePickButton('kern') });
  const [only] = annotationsPayload();
  assert.equal(only.ts, samples[0].ts);
  assert.equal(only.ts_end, samples[1].ts);
});

test('a tap still produces exactly the three keys it always had', () => {
  const samples = twoSamples();
  const wrap = fakeWrapWithPicker();
  const geo = geoFor(samples, ['precipitation'], { wrap });
  handleChartTap(geo, 0, 80, 95, () => {});
  wrap.querySelector('.ws-chart-annot-picker')._fire('click', { target: fakePickButton('kern') });
  const [only] = annotationsPayload();
  assert.deepEqual(Object.keys(only).sort(), ['curve', 'phase', 'ts']);
});

test('a range renders a hatched band in its own curve colour', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['precipitation']);
  const svg = buildAnnotationMarkersSvg(
    [{ curve: 'precipitation', ts: samples[0].ts, tsEnd: samples[1].ts, phase: 'kern' }],
    geo,
    { palette: { precipitation: '#38bdf8' } },
  );
  assert.match(svg, /<pattern/, 'a band is hatched, not a flat block');
  assert.match(svg, /stroke="#38bdf8"/, 'the hatching takes the curve colour');
  assert.match(svg, /class="ws-chart-annot-band"/);
});

test('a zero-width range draws no band, only its glyph', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['precipitation']);
  const svg = buildAnnotationMarkersSvg(
    [{ curve: 'precipitation', ts: samples[0].ts, tsEnd: samples[0].ts, phase: 'kern' }],
    geo,
    { palette: { precipitation: '#38bdf8' } },
  );
  assert.doesNotMatch(svg, /<pattern/);
});

test('a stored record using the wire key ts_end still renders its band', () => {
  const samples = twoSamples();
  const geo = geoFor(samples, ['precipitation']);
  const svg = buildAnnotationMarkersSvg(
    [{ curve: 'precipitation', ts: samples[0].ts, ts_end: samples[1].ts, phase: 'kern' }],
    geo,
    { palette: { precipitation: '#38bdf8' } },
  );
  assert.match(svg, /class="ws-chart-annot-band"/);
});
