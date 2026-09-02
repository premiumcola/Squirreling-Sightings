// Node tests for weather/_range-pills.js — offering only the windows the
// archive can actually fill.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { archiveSpanHours, rangePillPlan } from '../_range-pills.js';

const STEPS = [1, 6, 24, 168, 720]; // 1 h / 6 h / 24 h / 7 d / 30 d
const ext = (oldest, newest, count = 99) => ({ oldest, newest, count });

const disabled = (plan) => plan.pills.filter((p) => p.disabled).map((p) => p.hours);

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

test('a fresh install offers only what it can fill, plus one step', () => {
  // Three hours of history: 1 h is real, 6 h is the "everything I have"
  // view, and a 30 d axis over 3 h of data is the defect.
  const plan = rangePillPlan(3, STEPS, 24);
  assert.deepEqual(disabled(plan), [24, 168, 720]);
  assert.equal(plan.defaultHours, 6);
});

test('the step that covers the whole archive stays available', () => {
  // Otherwise the operator cannot see their own full history.
  const plan = rangePillPlan(3, STEPS, 24);
  assert.equal(
    plan.pills.find((p) => p.hours === 6).disabled,
    false,
  );
});

test('a full archive changes nothing', () => {
  const plan = rangePillPlan(24 * 400, STEPS, 24);
  assert.deepEqual(disabled(plan), []);
  assert.equal(plan.defaultHours, 24, 'the panel keeps its own default');
});

test('an archive longer than every step disables nothing', () => {
  const plan = rangePillPlan(99999, STEPS, 168);
  assert.deepEqual(disabled(plan), []);
  assert.equal(plan.defaultHours, 168);
});

test('an unknown span is not treated as an empty archive', () => {
  // A payload with no extent must never blank the picker.
  for (const span of [null, undefined, NaN]) {
    const plan = rangePillPlan(span, STEPS, 24);
    assert.deepEqual(disabled(plan), [], `span ${span} disabled steps`);
    assert.equal(plan.defaultHours, 24);
  }
});

test('the default only moves when the current step went dark', () => {
  // 30 minutes of data: only "1 h" survives, so that is where it lands.
  const plan = rangePillPlan(0.5, STEPS, 720);
  assert.deepEqual(disabled(plan), [6, 24, 168, 720]);
  assert.equal(plan.defaultHours, 1);
  // …but a step that is still fillable is left exactly where it was.
  assert.equal(rangePillPlan(0.5, STEPS, 1).defaultHours, 1);
});

test('exactly-covering spans do not disable their own step', () => {
  const plan = rangePillPlan(24, STEPS, 24);
  assert.equal(
    plan.pills.find((p) => p.hours === 24).disabled,
    false,
  );
  assert.deepEqual(disabled(plan), [168, 720]);
});

test('the step list is normalised, not trusted', () => {
  const plan = rangePillPlan(3, [24, 1, 6, 6, NaN, 0, -5, 168], 24);
  assert.deepEqual(
    plan.pills.map((p) => p.hours),
    [1, 6, 24, 168],
  );
});

test('no steps at all is survivable', () => {
  const plan = rangePillPlan(3, [], 24);
  assert.deepEqual(plan.pills, []);
  assert.equal(plan.defaultHours, 24);
});
