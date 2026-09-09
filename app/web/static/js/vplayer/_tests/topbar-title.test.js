// ─── vplayer/_tests/topbar-title.test.js ───────────────────────────────────
// What the player's top bar says.
//
// It used to say the camera's NAME, and nothing else — a string the
// operator had already passed twice on the way in (the tile they tapped,
// the drilldown they were in) and which is repeated a third time by the
// camera glyph now sitting beside it. „Titel also date und time und
// duration im titel davor reicht das logo der kamera als kamera-hinweis!
// Der name muss nicht drüber also von der kamera!"
//
// So the bar answers WHEN instead: date · time · duration.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { titleFor, cameraIconHtml } from '../_topbar.js';

const rec = (item) => ({ item, flags: { live: false } });

test('a recording reads date · time · duration', () => {
  const title = titleFor(rec({ time: '2026-09-07T10:36:24', duration_s: 27 }));
  assert.match(title, /07\.09\.2026/);
  assert.match(title, /10:36/);
  assert.match(title, /0:27/);
});

test('the camera name is NOT in the title any more', () => {
  const title = titleFor(
    rec({ time: '2026-09-07T10:36:24', duration_s: 27, camera_name: "Squirrel Town 'Nut Bar'" }),
  );
  assert.doesNotMatch(title, /Squirrel/);
});

test('a clip of unknown length still says when it was', () => {
  const title = titleFor(rec({ time: '2026-09-07T10:36:24' }));
  assert.match(title, /07\.09\.2026/);
  assert.doesNotMatch(title, /·\s*$/, 'no dangling separator where the duration would be');
});

test('a zero or missing duration is left off rather than printed as 0:00', () => {
  assert.doesNotMatch(titleFor(rec({ time: '2026-09-07T10:36:24', duration_s: 0 })), /0:00/);
  assert.doesNotMatch(
    titleFor(rec({ time: '2026-09-07T10:36:24', duration_s: null })),
    /0:00|null/,
  );
});

test('an unparseable timestamp never reaches the bar as "Invalid Date"', () => {
  const title = titleFor(rec({ time: 'not a date', label: 'Vogel' }));
  assert.equal(title, 'Vogel');
});

test('the bar is never empty and never says undefined', () => {
  assert.equal(titleFor(rec({})), 'Aufnahme');
  assert.equal(titleFor({ flags: { live: false } }), 'Aufnahme');
});

test('live says Live, whatever the item carries', () => {
  assert.equal(titleFor({ item: { time: '2026-09-07T10:36:24' }, flags: { live: true } }), 'Live');
});

// ── the glyph that replaced the name ────────────────────────────────────

test('the camera glyph carries the name it replaced, for screen readers', () => {
  const html = cameraIconHtml(rec({ camera_name: "Squirrel Town 'Nut Bar'" }));
  assert.match(html, /aria-label="Squirrel Town &#39;Nut Bar&#39;"/);
  assert.match(html, /<svg/);
});

test('a camera with no name still gets a labelled glyph', () => {
  const html = cameraIconHtml(rec({}));
  assert.match(html, /aria-label="Kamera"/);
  assert.match(html, /<svg/);
});
