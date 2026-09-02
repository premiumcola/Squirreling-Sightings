// ─── vplayer/_tests/helpers.test.js ────────────────────────────────────────
// The formatters, and specifically their DEGRADATION. The backend work
// these panels read (per-event provenance, per-detection model
// attribution, TPU busy ratio) is landing concurrently, so every one of
// these will be handed a missing field at some point. The rule the
// whole package depends on: a missing field renders as a placeholder,
// never as the literal string "undefined", never as "NaN", and never as
// a blank that a reader would mistake for a real zero.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PLACEHOLDER,
  ageLabel,
  clockLabel,
  countLabel,
  pctLabel,
  remainingLabel,
  spanLabel,
  valueOr,
} from '../_helpers.js';

/** Every formatter, with the input that most often turns up missing. */
const FORMATTERS = [
  ['spanLabel', () => spanLabel(undefined, undefined)],
  ['pctLabel', () => pctLabel(undefined)],
  ['countLabel', () => countLabel(undefined, 'Objekt', 'Objekte')],
  ['valueOr', () => valueOr(undefined)],
  ['ageLabel', () => ageLabel(undefined)],
];

test('no formatter ever emits "undefined" or "NaN" for a missing field', () => {
  for (const [name, run] of FORMATTERS) {
    const out = run();
    assert.equal(typeof out, 'string', `${name} must return a string`);
    assert.ok(!out.includes('undefined'), `${name} leaked "undefined": ${out}`);
    assert.ok(!out.includes('NaN'), `${name} leaked "NaN": ${out}`);
    assert.ok(out.length > 0, `${name} returned an empty string`);
    assert.equal(out, PLACEHOLDER, `${name} should degrade to the placeholder`);
  }
});

test('the clock formatters are re-exported AND usable inside this module', () => {
  // The re-export is what package consumers import; spanLabel calling
  // clockLabel is what proves the separate import statement is there.
  assert.equal(clockLabel(61), '1:01');
  assert.equal(remainingLabel(1, 6), '−0:05');
  assert.equal(spanLabel(61, 121), '1:01–2:01');
});

test('spanLabel renders from–to with an en dash and no spaces', () => {
  const out = spanLabel(3, 11);
  assert.equal(out, '0:03–0:11');
  assert.ok(out.includes('–'), 'separator must be U+2013 EN DASH');
  assert.ok(!out.includes(' '), 'no spaces around the separator');
});

test('a zero-length span reads as one moment, not a duration', () => {
  assert.equal(spanLabel(3, 3), '0:03');
  assert.equal(spanLabel(3, undefined), '0:03');
  assert.equal(spanLabel(3, 2), '0:03', 'an end before the start is not a span');
});

test('spanLabel clamps a negative start rather than printing one', () => {
  assert.equal(spanLabel(-4, 11), '0:00–0:11');
});

test('pctLabel renders a 0..1 fraction as "N %" with a space', () => {
  assert.equal(pctLabel(0.87), '87 %');
  assert.equal(pctLabel(0), '0 %');
  assert.equal(pctLabel(1), '100 %');
});

test('pctLabel takes a value above 1 as already scaled', () => {
  assert.equal(pctLabel(87), '87 %');
  assert.equal(pctLabel(99.6), '100 %');
});

test('pctLabel rounds rather than truncating, and parses a string', () => {
  assert.equal(pctLabel(0.876), '88 %');
  assert.equal(pctLabel(0.874), '87 %');
  assert.equal(pctLabel('0.42'), '42 %');
  assert.equal(pctLabel('nope'), PLACEHOLDER);
});

test('countLabel picks the singular for exactly one', () => {
  assert.equal(countLabel(1, 'Objekt', 'Objekte'), '1 Objekt');
  assert.equal(countLabel(0, 'Objekt', 'Objekte'), '0 Objekte');
  assert.equal(countLabel(3, 'Objekt', 'Objekte'), '3 Objekte');
});

test('valueOr passes a real value through and labels an absent one', () => {
  assert.equal(valueOr('efficientdet_lite0'), 'efficientdet_lite0');
  assert.equal(valueOr(0), '0', 'a real zero is a value, not a placeholder');
  assert.equal(valueOr(false), 'false');
  assert.equal(valueOr(null), PLACEHOLDER);
  assert.equal(valueOr(''), PLACEHOLDER);
  assert.equal(valueOr('   '), PLACEHOLDER);
  assert.equal(valueOr(NaN), PLACEHOLDER);
});

test('valueOr appends a unit only when there is a value to carry it', () => {
  assert.equal(valueOr(12, 'ms'), '12 ms');
  assert.equal(valueOr(null, 'ms'), PLACEHOLDER, 'never a bare unit');
});

test('ageLabel stays in seconds with a comma decimal under a minute', () => {
  assert.equal(ageLabel(4.23), '4,2 s');
  assert.equal(ageLabel(0), '0,0 s');
  assert.equal(ageLabel(59.9), '59,9 s');
});

test('ageLabel switches to the clock form at a minute', () => {
  assert.equal(ageLabel(60), '1:00');
  assert.equal(ageLabel(65), '1:05');
});

test('ageLabel rejects a negative age instead of rendering one', () => {
  assert.equal(ageLabel(-1), PLACEHOLDER);
});
