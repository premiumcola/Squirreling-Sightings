// ─── weather/_tests/hover-tooltip-units.test.js ────────────────────────
// HYG · the chart tooltip must read its units from the chart it is
// drawn on, not from whichever panel happened to load data last.
//
// stats-chart/_hover_tip.js took the row LABELS from the payload it was
// handed (`c.labels = data?.labels_de`) but the UNITS from
// `_wsFmtVal`, which reads the Wetterdaten panel's module-global
// `_wsStatsState.data.units`. Two sources for one thing.
//
// storms/_detail.js builds its payload with an explicit
// `units: WEATHER_FIELD_UNIT_DE` and says so in a comment ("Units and
// labels come from the existing German mirrors … the backend does not
// need to echo them"). That map was then ignored: open the Gewitter
// archive without ever visiting the Wetterdaten panel and
// `_wsStatsState.data` is still null, so every hovered value on the
// storm detail chart printed bare — "2400" where the rest of the same
// page (storms/_helpers.js · fmtMetric) prints "2400,00 J/kg".
//
// Pure string assembly, no DOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';

// stats.js ends with a `window.initWeatherStats = …` bridge that runs at
// module load, so the module graph below needs a window object to attach
// it to. Nothing in this file touches the DOM beyond that one assignment.
globalThis.window = globalThis.window || {};

const { _defaultRows } = await import('../stats-chart/_hover_tip.js');
const { _wsFmtVal, _wsStatsState } = await import('../stats.js');

// lightning_potential is banded to 0 decimals by wsFieldDigits,
// precipitation to 2 — one of each so the fix cannot pass by
// accidentally hard-coding a format.
const SAMPLE = { values: { lightning_potential: 2400, precipitation: 3.5 } };
const FIELDS = ['lightning_potential', 'precipitation'];
const LABELS = { lightning_potential: 'Blitz-Potential', precipitation: 'Niederschlag' };
const UNITS = { lightning_potential: 'J/kg', precipitation: 'mm/h' };

test('the tooltip prints the units the chart was given', () => {
  // _wsStatsState.data is null here — exactly the storm-archive case,
  // where the Wetterdaten panel was never opened.
  assert.equal(_wsStatsState.data, null);
  const rows = _defaultRows(SAMPLE, FIELDS, LABELS, UNITS);
  assert.match(rows, /2400 J\/kg/, 'lightning_potential lost its unit');
  assert.match(rows, /3\.50 mm\/h/, 'precipitation lost its unit');
});

test('the labels the chart was given still win', () => {
  const rows = _defaultRows(SAMPLE, FIELDS, LABELS, UNITS);
  assert.match(rows, /Blitz-Potential/);
  assert.match(rows, /Niederschlag/);
});

test('a field with no value is dropped, not printed as a dash row', () => {
  const rows = _defaultRows({ values: { lightning_potential: null } }, FIELDS, LABELS, UNITS);
  assert.equal(rows, '');
});

test('no units on the payload falls back to the panel formatter', () => {
  // The Wetterdaten panel itself passes its own state as `data`, so the
  // two sources agree there; this keeps any caller that ships no units
  // behaving exactly as before.
  const rows = _defaultRows(SAMPLE, ['lightning_potential'], LABELS, undefined);
  assert.match(rows, />2400</);
  assert.equal(_wsFmtVal('lightning_potential', 2400), '2400');
});

test('_wsFmtVal still reads the global when no units are passed', () => {
  assert.equal(_wsFmtVal('precipitation', 3.5), '3.50');
  assert.equal(_wsFmtVal('precipitation', 3.5, UNITS), '3.50 mm/h');
  assert.equal(_wsFmtVal('precipitation', null, UNITS), '—');
});
