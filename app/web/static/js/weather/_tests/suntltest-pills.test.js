// ─── weather/_tests/suntltest-pills.test.js ────────────────────────────
// HYG · the Sun-Timelapse test panel's status pills.
//
// `dnBadge` was written, styled (.suntltest-badge--ok/--err/--mute in
// 23-weather-3.css) and listed FIRST in the panel's own header comment
// as a signal the panel surfaces — and never called. The backend has
// been filling `daynight_color_set` / `daynight_revert_set` on every
// session the whole time (weather_service/_sun_tl · _run_sun_tl_test_
// thread), so the operator could run a test with the Reolink day/night
// override enabled, have the Color flip fail outright, and see nothing
// about it anywhere in the UI.
//
// Pure string assembly — no DOM, matching how the other weather tests
// here are written.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { dnBadge, driftBadge, pillRow, profileBadge } = await import('../suntltest/_live.js');

// ── the three daynight states ─────────────────────────────────────────

test('dnBadge separates set / failed / skipped', () => {
  assert.match(dnBadge(true), /suntltest-badge--ok/);
  assert.match(dnBadge(false), /suntltest-badge--err/);
  // null is "override was not attempted", not "it failed".
  assert.match(dnBadge(null), /suntltest-badge--mute/);
  assert.match(dnBadge(undefined), /suntltest-badge--mute/);
});

test('a failed daynight override is not dressed up as a success', () => {
  assert.doesNotMatch(dnBadge(false), /--ok/);
  assert.doesNotMatch(dnBadge(null), /--ok/);
});

// ── the pill row must actually carry it ───────────────────────────────

test('the daynight-override result reaches the pill row', () => {
  const failed = pillRow({ daynight_color_set: false });
  assert.match(failed, /suntltest-badge--err/, 'a failed Color flip is invisible to the operator');
  const ok = pillRow({ daynight_color_set: true });
  assert.match(ok, /suntltest-badge--ok/);
});

// One badge carries the class twice (`suntltest-badge suntltest-badge--ok`),
// so count the modifier, which appears exactly once per badge.
const badgeCount = (html) => (html.match(/suntltest-badge--/g) || []).length;

test('the revert result shows only once a revert was attempted', () => {
  // Mid-run the revert has not happened yet — no second badge.
  const midRun = pillRow({ daynight_color_set: true, daynight_revert_set: null });
  assert.equal(badgeCount(midRun), 1);
  // After the revert both results are on screen.
  const done = pillRow({ daynight_color_set: true, daynight_revert_set: false });
  assert.equal(badgeCount(done), 2);
  assert.match(done, /suntltest-badge--err/);
});

test('the existing profile and drift pills are untouched', () => {
  const html = pillRow({
    validator_profile: 'twilight',
    baseline_brightness: 42,
    phase_drift_warning: 'lief 312 min nach Sonnenuntergang',
    daynight_color_set: null,
  });
  assert.match(html, /suntltest-pill--twilight/);
  assert.match(html, /brightness 42/);
  assert.match(html, /suntltest-pill--drift/);
  assert.match(html, /312 min/);
});

test('profileBadge and driftBadge stay silent when they have nothing to say', () => {
  assert.equal(profileBadge(null), '');
  assert.equal(profileBadge(undefined, 12), '');
  assert.equal(driftBadge(''), '');
  assert.equal(driftBadge(null), '');
});

test('the drift warning is escaped, not interpolated raw', () => {
  const html = driftBadge('<img src=x onerror=alert(1)>');
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});
