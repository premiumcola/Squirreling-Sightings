// ─── sichtungen/_tests/clips-gallery.test.js ─────────────────────────────
// The pure leaves behind the clips gallery (_clips-helpers.js). The
// renderer itself imports mediathek/_cards.js, whose module graph
// reaches mediathek/_processing.js — `window._toggleProcTile = ...` at
// MODULE-LOAD time, the same wall library/_tests/bind.test.js and
// test_species_dossier_panel_js.py both document. Importing
// _clips-gallery.js here throws `ReferenceError: window is not defined`
// before a single assertion runs, so the logic worth testing lives in
// that DOM-free leaf; the markup is pinned source-level on the Python
// side instead.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clampIndex, clipVideoUrl } from '../_clips-helpers.js';

test('clampIndex keeps the index inside the list', () => {
  assert.equal(clampIndex(-3, 5), 0);
  assert.equal(clampIndex(0, 5), 0);
  assert.equal(clampIndex(4, 5), 4);
  assert.equal(clampIndex(9, 5), 4);
});

test('clampIndex handles a single clip and an empty list', () => {
  assert.equal(clampIndex(0, 1), 0);
  assert.equal(clampIndex(1, 1), 0);
  // Empty: 0 rather than -1, so a caller can index without a guard.
  assert.equal(clampIndex(0, 0), 0);
  assert.equal(clampIndex(3, 0), 0);
});

test('clampIndex survives a non-numeric index', () => {
  assert.equal(clampIndex(undefined, 4), 0);
  assert.equal(clampIndex(NaN, 4), 0);
  assert.equal(clampIndex(2.7, 4), 2);
});

test('clipVideoUrl prefers an absolute url over the storage relpath', () => {
  assert.equal(
    clipVideoUrl({ video_url: 'https://x.invalid/a.mp4', video_relpath: 'cam/a.mp4' }),
    'https://x.invalid/a.mp4',
  );
});

test('clipVideoUrl builds the /media path from a relpath', () => {
  assert.equal(
    clipVideoUrl({ video_relpath: 'cam1/2026-09-02/e1.mp4' }),
    '/media/cam1/2026-09-02/e1.mp4',
  );
});

// A still-only event has no clip to play — the card shows no play button
// for it either, so the gallery must not wire one.
test('clipVideoUrl returns empty for an unplayable item', () => {
  assert.equal(clipVideoUrl({}), '');
  assert.equal(clipVideoUrl(null), '');
  assert.equal(clipVideoUrl({ snapshot_relpath: 'cam1/x.jpg' }), '');
});
