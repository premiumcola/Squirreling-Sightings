// ─── mediaview/_tests/live-detect-tick-status.test.js ──────────────────────
// The two pure verdicts live-detect-poll.js reaches about a tick.
//
// P7 · the in-flight boundary is the load-bearing one: a request younger
// than the ceiling is never aborted, because Flask cannot cancel its
// handler — aborting doubles the server's load instead of freeing it. The
// tests below pin BOTH edges (0 = nothing out, ceiling = old enough to stop
// protecting) because an off-by-one there is invisible until the box is
// under load.
//
// B23' · the failure classification is what puts a real reason on screen;
// leaving either 429 code wordless is what let the stall watchdog's guess
// stand in for the truth.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  _inflightAgeMs,
  _isInflightPending,
  _classifyTickFailure,
} from '../_live-detect-tick-status.js';

const CEILING = 30_000;

test('no request out means age 0, whatever falsy shape the stamp has', () => {
  assert.equal(_inflightAgeMs(0, 1_000_000), 0);
  assert.equal(_inflightAgeMs(undefined, 1_000_000), 0);
  assert.equal(_inflightAgeMs(null, 1_000_000), 0);
});

test('a request in flight ages by the wall clock', () => {
  assert.equal(_inflightAgeMs(1_000_000, 1_000_500), 500);
  assert.equal(_inflightAgeMs(1_000_000, 1_030_000), 30_000);
});

test('P7 · age 0 is not pending — nothing is out, so the caller may fire', () => {
  assert.equal(_isInflightPending(0, CEILING), false);
});

test('P7 · a young request IS pending: the caller stands down rather than racing', () => {
  assert.equal(_isInflightPending(1, CEILING), true);
  assert.equal(_isInflightPending(500, CEILING), true);
  assert.equal(_isInflightPending(29_999, CEILING), true);
});

test('P7 · the ceiling boundary is exclusive — at exactly 30 s it is no longer pending', () => {
  // This is the edge the abort rule is written against: below it the
  // request is protected, at and above it the watchdog may act.
  assert.equal(_isInflightPending(CEILING, CEILING), false);
  assert.equal(_isInflightPending(CEILING + 1, CEILING), false);
  assert.equal(_isInflightPending(120_000, CEILING), false);
});

test('P7 · a negative age (clock skew) is not pending', () => {
  assert.equal(_isInflightPending(-5, CEILING), false);
});

test("B23' · the body's own code wins over the HTTP status", () => {
  const v = _classifyTickFailure(429, { code: 'busy', error: 'schon beschäftigt' });
  assert.equal(v.code, 'busy');
  assert.equal(v.msg, 'schon beschäftigt');
  assert.equal(v.text, 'busy · schon beschäftigt');
});

test("B23' · both 429 codes keep their message, so neither lands on screen wordless", () => {
  const busy = _classifyTickFailure(429, { code: 'busy', error: 'läuft noch' });
  assert.equal(busy.text, 'busy · läuft noch');
  const refused = _classifyTickFailure(429, {
    code: 'mode_too_expensive',
    error: '3×3 kostet 10 Inferenzen',
  });
  assert.equal(refused.code, 'mode_too_expensive');
  assert.equal(refused.msg, '3×3 kostet 10 Inferenzen');
  assert.equal(refused.text, 'mode_too_expensive · 3×3 kostet 10 Inferenzen');
});

test("B23' · with no code in the body, the status carries the banner", () => {
  const v = _classifyTickFailure(503, null);
  assert.equal(v.code, 503);
  assert.equal(v.msg, '');
  assert.equal(v.text, '503');
});

test("B23' · a body that did not parse and no status still yields a greppable '?'", () => {
  const v = _classifyTickFailure(undefined, null);
  assert.equal(v.code, '?');
  assert.equal(v.text, '?');
});

test("B23' · `error` is preferred over `message`, and `message` is the fallback", () => {
  assert.equal(_classifyTickFailure(500, { error: 'A', message: 'B' }).msg, 'A');
  assert.equal(_classifyTickFailure(500, { message: 'B' }).msg, 'B');
  assert.equal(_classifyTickFailure(500, { message: 'B' }).text, '500 · B');
});

test("B23' · status-only failures stringify the code rather than emitting 'undefined'", () => {
  // The banner is screenshotted by the operator; "503" must never read
  // "503 · undefined".
  for (const data of [null, {}, { error: '' }, { message: '' }]) {
    assert.equal(_classifyTickFailure(503, data).text, '503');
  }
});
