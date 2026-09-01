// ─── mediathek/_tests/trash-modal.test.js ───────────────────────────────
// _trashThumbHTML(it) builds the leading preview for one Papierkorb
// row — trash.list_trashed() (backend) now exposes `thumb_url` read
// straight off whatever snapshot the entry's move-to-trash already
// carried in. Pinning: an <img> renders when present, only the
// placeholder icon renders when absent (never an empty box), and the
// URL is HTML-escaped like every other innerHTML template string in
// this codebase.
import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = { addEventListener() {} };
globalThis.document = { getElementById: () => null, addEventListener() {} };

const { _trashThumbHTML } = await import('../trash-modal.js');

test('a present thumb_url renders an <img> with that src', () => {
  const html = _trashThumbHTML({ thumb_url: '/media/.trash/cam1/ev1/ev1.jpg' });
  assert.match(html, /<img src="\/media\/\.trash\/cam1\/ev1\/ev1\.jpg"/);
});

test('a missing thumb_url renders only the placeholder, no <img>', () => {
  const html = _trashThumbHTML({ thumb_url: null });
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /<svg/);
});

test('an empty-string thumb_url is treated the same as missing', () => {
  const html = _trashThumbHTML({ thumb_url: '' });
  assert.doesNotMatch(html, /<img/);
});

test('the thumb_url is HTML-escaped before insertion', () => {
  const html = _trashThumbHTML({ thumb_url: '"><script>alert(1)</script>' });
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&quot;&gt;&lt;script&gt;/);
});

test('the placeholder icon is always present, even with a valid thumb_url', () => {
  // The <img> can fail to load at runtime (onerror removes it) — the
  // placeholder must already be underneath, not added after the fact.
  const html = _trashThumbHTML({ thumb_url: '/media/.trash/cam1/ev1/ev1.jpg' });
  assert.match(html, /<svg/);
});
