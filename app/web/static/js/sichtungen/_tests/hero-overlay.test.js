// ─── sichtungen/_tests/hero-overlay.test.js ──────────────────────────────
// _hero-overlay.js is a pure leaf (esc + string templates, no DOM/fetch
// imports) — a real import-and-exercise test, unlike _dossier-panel.js /
// _achievements.js (see test_species_dossier_panel_js.py's docstring for
// why those fall back to source-level regression pins).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { heroHtml, audioListHtml, photoUrlsOf } from '../_hero-overlay.js';

const _BASE = { common_name_de: 'Rotkehlchen', latin: 'Erithacus rubecula' };

test('heroHtml renders two photo boxes', () => {
  const html = heroHtml({
    ..._BASE,
    wikipedia_thumb_url: 'https://x.invalid/robin-front.jpg',
    wikipedia_thumb_url_2: 'https://x.invalid/robin-side.jpg',
  });
  assert.equal((html.match(/class="sd-hero-photo"/g) || []).length, 2);
  assert.match(html, /sd-hero--2/);
  assert.match(html, /src="https:\/\/x\.invalid\/robin-front\.jpg"/);
  assert.match(html, /src="https:\/\/x\.invalid\/robin-side\.jpg"/);
});

// The whole point of the 2026-09 fix: a slot shows a real photograph or
// it does not exist. The old placeholder put the app's generic bird
// glyph next to a real photo, where it read as a picture OF the species.
test('heroHtml renders one box for one photo, never a placeholder', () => {
  const html = heroHtml({ ..._BASE, wikipedia_thumb_url: 'https://x.invalid/only.jpg' });
  assert.equal((html.match(/class="sd-hero-photo"/g) || []).length, 1);
  assert.match(html, /sd-hero--1/);
  assert.doesNotMatch(html, /sd-hero-placeholder/);
  assert.doesNotMatch(html, /🐦/u);
});

test('heroHtml renders three boxes for three photos', () => {
  const html = heroHtml({
    ..._BASE,
    photo_urls: ['https://x.invalid/a.jpg', 'https://x.invalid/b.jpg', 'https://x.invalid/c.jpg'],
  });
  assert.equal((html.match(/class="sd-hero-photo"/g) || []).length, 3);
  assert.match(html, /sd-hero--3/);
});

test('photoUrlsOf prefers photo_urls over the legacy mirror fields', () => {
  const d = {
    photo_urls: ['https://x.invalid/new1.jpg', 'https://x.invalid/new2.jpg'],
    wikipedia_thumb_url: 'https://x.invalid/legacy.jpg',
    wikipedia_thumb_url_2: null,
  };
  assert.deepEqual(photoUrlsOf(d), ['https://x.invalid/new1.jpg', 'https://x.invalid/new2.jpg']);
});

// A dossier cached before photo_urls existed still has to render.
test('photoUrlsOf falls back to the legacy fields for an un-refetched dossier', () => {
  const d = { wikipedia_thumb_url: 'https://x.invalid/a.jpg', wikipedia_thumb_url_2: '' };
  assert.deepEqual(photoUrlsOf(d), ['https://x.invalid/a.jpg']);
});

test('heroHtml drops the hero entirely and names the species when no photo exists', () => {
  const html = heroHtml({ ..._BASE, wikipedia_thumb_url: '', wikipedia_thumb_url_2: '' });
  assert.doesNotMatch(html, /sd-hero-placeholder/);
  assert.doesNotMatch(html, /class="sd-hero /);
  assert.match(html, /sd-name-line/);
  assert.match(html, /Rotkehlchen/);
});

test('heroHtml burns the latin name under the german one', () => {
  const html = heroHtml({ ..._BASE, wikipedia_thumb_url: 'https://x.invalid/a.jpg' });
  const caption = html.split('class="sd-hero-caption"')[1] || '';
  assert.match(caption, /sd-hero-name">Rotkehlchen</);
  assert.match(caption, /sd-hero-latin">Erithacus rubecula</);
  // The German name has to come FIRST in the caption block.
  assert.ok(caption.indexOf('sd-hero-name') < caption.indexOf('sd-hero-latin'));
});

// A species with no German name already falls back to the latin one for
// the main line — repeating it underneath would be the exact duplication
// folding the name into the photo was meant to remove.
test('heroHtml does not repeat the latin name when it IS the main name', () => {
  const html = heroHtml({
    latin: 'Erithacus rubecula',
    common_name_de: '',
    wikipedia_thumb_url: 'https://x.invalid/a.jpg',
  });
  assert.doesNotMatch(html, /sd-hero-latin/);
  assert.equal((html.match(/Erithacus rubecula/g) || []).length, 1);
});

test('photoUrlsOf skips blank and whitespace-only urls', () => {
  assert.deepEqual(photoUrlsOf({ wikipedia_thumb_url: '   ', wikipedia_thumb_url_2: null }), []);
  assert.deepEqual(photoUrlsOf({ wikipedia_thumb_url: 'https://x.invalid/a.jpg' }), [
    'https://x.invalid/a.jpg',
  ]);
});

test('heroHtml only burns the name and play button into the first photo', () => {
  const html = heroHtml({
    ..._BASE,
    wikipedia_thumb_url: 'https://x.invalid/a.jpg',
    wikipedia_thumb_url_2: 'https://x.invalid/b.jpg',
    audio_url: 'https://x.invalid/song.mp3',
  });
  const [first, second] = html.split('class="sd-hero-photo"').slice(1);
  assert.match(first, /sd-hero-name/);
  assert.match(first, /sd-hero-play/);
  assert.doesNotMatch(second, /sd-hero-name/);
  assert.doesNotMatch(second, /sd-hero-play/);
});

test('heroHtml renders no play button without any recording', () => {
  const html = heroHtml({ ..._BASE, wikipedia_thumb_url: 'https://x.invalid/a.jpg' });
  assert.doesNotMatch(html, /sd-hero-play/);
});

test('audioListHtml still renders for the legacy single-clip shape', () => {
  const html = audioListHtml({ ..._BASE, audio_url: 'https://x.invalid/song.mp3' });
  assert.match(html, /sd-audio-el/);
});
