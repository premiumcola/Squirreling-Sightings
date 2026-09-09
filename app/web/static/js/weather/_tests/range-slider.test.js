// Node tests for weather/_range-slider.js — the „nah → fern" time
// chooser that replaced the five fixed range pills. Same ladder of hour
// values behind it, so the archive-extent rules these tests pin are the
// pill bar's own rules, carried over: the slider must only reach as far
// as the buffer can actually fill, plus exactly one step of headroom.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  archiveSpanHours,
  parseSteps,
  rangeSliderPlan,
  hoursAtIndex,
  formatRangeHours,
  rangeReadoutText,
} from '../_range-slider.js';

const STEPS = [1, 6, 24, 168, 720]; // 1 h / 6 h / 24 h / 7 d / 30 d
const ext = (oldest, newest, count = 99) => ({ oldest, newest, count });

test('archiveSpanHours reads the buffer extent', () => {
  assert.equal(archiveSpanHours(ext('2026-08-30T00:00:00', '2026-08-30T06:00:00')), 6);
  assert.equal(archiveSpanHours(ext('2026-08-23T12:00:00', '2026-08-30T12:00:00')), 168);
});

test('an extent that cannot say anything reads as unknown', () => {
  assert.equal(archiveSpanHours(null), null);
  assert.equal(archiveSpanHours(undefined), null);
  assert.equal(archiveSpanHours(ext(null, null, 0)), null);
  // One sample is a point, not a span.
  assert.equal(archiveSpanHours(ext('2026-08-30T00:00:00', '2026-08-30T00:00:00', 1)), null);
  assert.equal(archiveSpanHours(ext('nonsense', '2026-08-30T06:00:00')), null);
  // Clock skew: newest before oldest is not a negative span, it is junk.
  assert.equal(archiveSpanHours(ext('2026-08-30T06:00:00', '2026-08-30T00:00:00')), null);
});

// ── the slider's domain ─────────────────────────────────────────────────

test('a fresh install stops the track short instead of offering empty months', () => {
  // Three hours of history: 1 h is real, 6 h is the "everything I have"
  // view, and a 30 d axis over 3 h of data is the defect.
  const plan = rangeSliderPlan(3, STEPS, 24);
  assert.deepEqual(plan.steps, [1, 6]);
  assert.equal(plan.hours, 6);
  assert.equal(plan.index, 1, 'the handle sits at the far end of what is reachable');
});

test('the step that covers the whole archive stays reachable', () => {
  // Otherwise the operator cannot see their own full history.
  assert.ok(rangeSliderPlan(3, STEPS, 24).steps.includes(6));
});

test('a full archive changes nothing', () => {
  const plan = rangeSliderPlan(24 * 400, STEPS, 24);
  assert.deepEqual(plan.steps, STEPS);
  assert.equal(plan.hours, 24, 'the panel keeps its own default');
  assert.equal(plan.index, 2);
});

test('an archive longer than every step reaches all the way to „fern"', () => {
  const plan = rangeSliderPlan(99999, STEPS, 168);
  assert.deepEqual(plan.steps, STEPS);
  assert.equal(plan.hours, 168);
});

test('an unknown span is not treated as an empty archive', () => {
  // A payload with no extent must never collapse the track.
  for (const span of [null, undefined, NaN]) {
    const plan = rangeSliderPlan(span, STEPS, 24);
    assert.deepEqual(plan.steps, STEPS, `span ${span} trimmed the track`);
    assert.equal(plan.hours, 24);
  }
});

test('the handle only moves when its step went off the end', () => {
  // 30 minutes of data: only "1 h" survives, so that is where it lands.
  const plan = rangeSliderPlan(0.5, STEPS, 720);
  assert.deepEqual(plan.steps, [1]);
  assert.equal(plan.hours, 1);
  // …and a step that is still reachable is left exactly where it was.
  assert.equal(rangeSliderPlan(0.5, STEPS, 1).hours, 1);
});

test('exactly-covering spans keep their own step', () => {
  const plan = rangeSliderPlan(24, STEPS, 24);
  assert.deepEqual(plan.steps, [1, 6, 24]);
  assert.equal(plan.hours, 24);
});

test('the step list is normalised, not trusted', () => {
  assert.deepEqual(parseSteps('24,1,6,6,x,0,-5,168'), [1, 6, 24, 168]);
  assert.deepEqual(rangeSliderPlan(3, [24, 1, 6, 6, NaN, 0, -5, 168], 24).steps, [1, 6]);
  assert.deepEqual(parseSteps(undefined), []);
});

test('no steps at all is survivable', () => {
  const plan = rangeSliderPlan(3, [], 24);
  assert.deepEqual(plan.steps, []);
  assert.equal(plan.hours, 24);
});

// ── handle position → hours ─────────────────────────────────────────────

test('hoursAtIndex maps a handle position onto its step', () => {
  assert.equal(hoursAtIndex(STEPS, 0), 1);
  assert.equal(hoursAtIndex(STEPS, '4'), 720, 'input.value arrives as a string');
});

test('hoursAtIndex clamps rather than reading off the end of the ladder', () => {
  assert.equal(hoursAtIndex(STEPS, -3), 1);
  assert.equal(hoursAtIndex(STEPS, 99), 720);
});

test('hoursAtIndex refuses to guess at junk', () => {
  assert.equal(hoursAtIndex(STEPS, 'nonsense'), null);
  assert.equal(hoursAtIndex([], 0), null);
  assert.equal(hoursAtIndex(null, 0), null);
});

// ── the readout — the slider must never be a mystery control ────────────

test('the chosen range is always spelled out, hours below two days, days above', () => {
  assert.equal(formatRangeHours(1), '1 h');
  assert.equal(formatRangeHours(6), '6 h');
  // "1 d" would be a second name for the step this whole app calls 24 h.
  assert.equal(formatRangeHours(24), '24 h');
  assert.equal(formatRangeHours(168), '7 d');
  assert.equal(formatRangeHours(720), '30 d');
});

test('an unusable range reads as a dash, never as "NaN h"', () => {
  for (const bad of [null, undefined, NaN, 0, -5]) {
    assert.equal(formatRangeHours(bad), '—');
  }
});

test('a dragged chart span matches no step, so the readout stops claiming one', () => {
  assert.equal(rangeReadoutText(24, false), '24 h');
  assert.equal(rangeReadoutText(24, true), 'eigener Zeitraum');
});
