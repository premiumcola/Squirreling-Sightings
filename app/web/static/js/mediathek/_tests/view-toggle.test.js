// ─── mediathek/_tests/view-toggle.test.js ──────────────────────────────────
// Which of the Mediathek's four states is visible — and that switching
// to one BRINGS IT INTO VIEW.
//
// The four states are stacked inside one long page: the Mediathek
// section is followed by the weather chart, its legend, three settings
// folds and the Sichtungen block. Tapping a tile near the bottom of the
// overview swapped the state in place and left the scroll position where
// the finger was, so „Vogelarten" answered with a screen full of weather
// data and the grid sat off-screen above it — „Das ist die screen
// ansicht wenn ich auf vogelarten klicke?!".
//
// Two things must NOT scroll: a re-render of the state already shown
// (that would yank the page while it is being read) and the very first
// call, which is the initial paint.

import { test } from 'node:test';
import assert from 'node:assert/strict';

const _VIEWS = ['mediaOverview', 'mediaSpeciesGrid', 'mediaDrilldown', 'libraryBlock'];

const scrolled = [];
const els = Object.fromEntries(
  _VIEWS.map((id) => [
    id,
    {
      id,
      style: {},
      scrollIntoView(opts) {
        scrolled.push({ id, opts });
      },
    },
  ]),
);

// The merged feed's filter bar. It is NOT one of the four states — it
// sits above all of them — but the toggle owns its visibility too, so it
// has to be in the stub.
els.libraryFilterBar = { id: 'libraryFilterBar', style: {} };

globalThis.window = globalThis.window || {};
globalThis.document = { getElementById: (id) => els[id] || null };

const { showMediathekView } = await import('../_view-toggle.js');

function visible() {
  return _VIEWS.filter((id) => els[id].style.display !== 'none');
}

test('exactly one state is visible at a time', () => {
  showMediathekView('mediaOverview');
  assert.deepEqual(visible(), ['mediaOverview']);
  showMediathekView('mediaDrilldown');
  assert.deepEqual(visible(), ['mediaDrilldown']);
});

test('the first call does not scroll — that one is the initial paint', () => {
  // The module is already primed by the test above; what this pins is
  // that the very first call produced nothing, which it did: the two
  // entries below belong to the switch in that test.
  assert.equal(scrolled.filter((s) => s.id === 'mediaOverview').length, 0);
});

test('switching states scrolls the new one into view', () => {
  scrolled.length = 0;
  showMediathekView('mediaSpeciesGrid');
  assert.deepEqual(
    scrolled.map((s) => s.id),
    ['mediaSpeciesGrid'],
  );
  assert.equal(scrolled[0].opts.block, 'start');
});

test('re-rendering the SAME state never scrolls', () => {
  showMediathekView('mediaSpeciesGrid');
  scrolled.length = 0;
  showMediathekView('mediaSpeciesGrid');
  showMediathekView('mediaSpeciesGrid');
  assert.deepEqual(scrolled, [], 'a repaint must not yank the page');
});

test('reduced motion gets the jump, not the glide', () => {
  showMediathekView('mediaOverview');
  scrolled.length = 0;
  globalThis.matchMedia = () => ({ matches: true });
  showMediathekView('mediaDrilldown');
  assert.equal(scrolled[0].opts.behavior, 'auto');
  delete globalThis.matchMedia;
});

test('a state whose element is missing is survivable', () => {
  const saved = els.libraryBlock;
  delete els.libraryBlock;
  showMediathekView('libraryBlock'); // must not throw
  els.libraryBlock = saved;
});

// ── one class-filter row at a time — „Filter sind doppelt drin!" ────────
//
// #libraryFilterBar filters the merged feed. The drilldown brings its
// own bar for the grid it actually shows. With the drilldown open both
// were on screen: two rows of the same taxonomy, each with its own count
// for „Vogel", and the top one filtering a grid that was not visible.

test('the drilldown hides the merged feed’s filter bar', () => {
  showMediathekView('mediaDrilldown');
  assert.equal(els.libraryFilterBar.style.display, 'none');
});

test('every other state gives it back', () => {
  for (const which of ['mediaOverview', 'libraryBlock', 'mediaSpeciesGrid']) {
    showMediathekView(which);
    assert.equal(els.libraryFilterBar.style.display, '', `${which} must show the bar`);
  }
});

test('a missing filter bar is survivable', () => {
  const saved = els.libraryFilterBar;
  delete els.libraryFilterBar;
  showMediathekView('mediaDrilldown'); // must not throw
  els.libraryFilterBar = saved;
});
