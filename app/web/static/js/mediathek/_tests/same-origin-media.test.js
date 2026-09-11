// ─── mediathek/_tests/same-origin-media.test.js ────────────────────────────
// „in den timelapses fehlen die thumbs — werden die im flow nicht
// generiert nach abschluss des encodes?!"
//
// They are generated, and the event even records them. What it records is
// an ABSOLUTE url built from `server.public_base_url` at registration
// time — on the live box `http://<LAN-IP>:8099/media/…`. Opened over any
// other address that image cannot load, and the card falls back to its
// dark plate. Motion cards were never affected: they carry a relative
// `snapshot_relpath`.
//
// The address below is RFC 5737 documentation space, per CLAUDE.md — a
// real LAN address in a tracked file is the thing that rule exists for,
// and this test is the one place it would look harmless.

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis.window || {};
globalThis.document = globalThis.document || { getElementById: () => null };

const { sameOriginMedia } = await import('../_cards.js');

test('an absolute url keeps only its path — whatever host served the page', () => {
  assert.equal(
    sameOriginMedia('http://192.0.2.10:8099/media/timelapse/cam/2026-09-10_daily.jpg'),
    '/media/timelapse/cam/2026-09-10_daily.jpg',
  );
  assert.equal(sameOriginMedia('https://kameras.example/media/x.jpg'), '/media/x.jpg');
});

test('a query string survives — it may carry a cache buster', () => {
  assert.equal(sameOriginMedia('http://host:8099/media/x.jpg?t=7'), '/media/x.jpg?t=7');
});

test('a relative value is already right and is handed back untouched', () => {
  assert.equal(sameOriginMedia('/media/timelapse/cam/x.jpg'), '/media/timelapse/cam/x.jpg');
  assert.equal(sameOriginMedia('media/x.jpg'), 'media/x.jpg');
});

test('nothing is still nothing, never the string "undefined"', () => {
  assert.equal(sameOriginMedia(null), '');
  assert.equal(sameOriginMedia(undefined), '');
  assert.equal(sameOriginMedia(''), '');
});

test('an unparseable value is not made worse', () => {
  assert.equal(sameOriginMedia('http://'), 'http://');
});
