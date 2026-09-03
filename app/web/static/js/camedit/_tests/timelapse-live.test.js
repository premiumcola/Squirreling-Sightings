// Node tests for camedit/_timelapse-live.js — the tile shows what is
// actually capturing, and nothing else.
//
// The rule under test is the one the operator asked for: sun and event
// timelapses appear on the live tile only while their window is running.
// A scheduled capture, a skipped one and a finished one all produce no
// row, however tempting their window times look.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { fmtRemaining, weatherLiveRows, tlTileVisible } from '../_timelapse-live.js';

const sun = (state, extra = {}) => ({
  camera_id: 'cam1',
  camera_name: 'Garten',
  phase: 'sunset',
  phase_text: 'Sonnenuntergang',
  state,
  remaining_s: 900,
  ...extra,
});

const evt = (state, extra = {}) => ({
  camera_id: 'cam2',
  camera_name: 'Hof',
  trigger: 'storm_front',
  trigger_text: 'Sturmfront',
  state,
  remaining_s: 1800,
  ...extra,
});

const wx = (sunRows = [], eventRows = []) => ({
  available: true,
  sun: sunRows,
  event: eventRows,
  running_count: 0,
});

test('remaining time reads in seconds, minutes and hours', () => {
  assert.equal(fmtRemaining(45), 'noch 45 s');
  assert.equal(fmtRemaining(900), 'noch 15 min');
  assert.equal(fmtRemaining(75 * 60), 'noch 75 min');
  assert.equal(fmtRemaining(2 * 3600), 'noch 2 h');
  assert.equal(fmtRemaining(2 * 3600 + 600), 'noch 2 h 10 min');
});

test('an unknown remaining time yields no phrase rather than a wrong one', () => {
  // Number(null) is 0, so a naive coercion prints a confident "noch 1 s"
  // for a value we simply do not have. That was a real bug here.
  assert.equal(fmtRemaining(null), '');
  assert.equal(fmtRemaining(undefined), '');
  assert.equal(fmtRemaining(''), '');
  assert.equal(fmtRemaining('bald'), '');
  assert.equal(fmtRemaining(-5), '');
});

test('a window about to close says so instead of counting to zero', () => {
  assert.equal(fmtRemaining(0), 'endet gleich');
});

test('a running sun capture becomes a row', () => {
  const rows = weatherLiveRows(wx([sun('running')]));
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0], {
    kind: 'sun',
    camId: 'cam1',
    camName: 'Garten',
    what: 'Sonnenuntergang',
    remaining: 'noch 15 min',
  });
});

test('scheduled, skipped and finished captures produce no row', () => {
  for (const state of ['scheduled', 'skipped', 'finished', 'unknown']) {
    assert.deepEqual(weatherLiveRows(wx([sun(state)])), [], `${state} leaked onto the tile`);
  }
});

test('a running event capture is named by its trigger', () => {
  const rows = weatherLiveRows(wx([], [evt('running')]));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].kind, 'event');
  assert.equal(rows[0].what, 'Sturmfront');
  assert.equal(rows[0].remaining, 'noch 30 min');
});

test('sun and event captures coexist, sun first', () => {
  const rows = weatherLiveRows(wx([sun('running')], [evt('running')]));
  assert.deepEqual(
    rows.map((r) => r.kind),
    ['sun', 'event'],
  );
});

test('an unavailable weather service claims nothing', () => {
  assert.deepEqual(weatherLiveRows({ available: false, sun: [sun('running')] }), []);
  assert.deepEqual(weatherLiveRows(null), []);
  assert.deepEqual(weatherLiveRows(undefined), []);
  assert.deepEqual(weatherLiveRows({}), []);
});

test('a row survives missing labels without printing undefined', () => {
  const rows = weatherLiveRows(
    wx([sun('running', { phase_text: undefined, camera_name: undefined, remaining_s: null })]),
  );
  assert.equal(rows[0].what, 'Sonnen-Timelapse');
  assert.equal(rows[0].camName, 'cam1');
  assert.equal(rows[0].remaining, '');
});

test('the tile appears for a periodic profile alone', () => {
  assert.equal(tlTileVisible({ active_count: 2 }, []), true);
});

test('the tile appears for a running weather capture alone', () => {
  assert.equal(tlTileVisible({ active_count: 0 }, [{ kind: 'sun' }]), true);
});

test('the tile stays away when neither reason holds', () => {
  assert.equal(tlTileVisible({ active_count: 0 }, []), false);
  assert.equal(tlTileVisible(null, []), false);
  // A failed poll must not resurrect it either.
  assert.equal(tlTileVisible(undefined, undefined), false);
});
