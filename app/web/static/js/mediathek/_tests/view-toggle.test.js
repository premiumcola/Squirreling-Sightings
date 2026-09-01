// ─── mediathek/_tests/view-toggle.test.js ───────────────────────────────
// showMediathekView is the single source of truth for which of the three
// Mediathek states (#mediaOverview / #mediaDrilldown / #libraryBlock) is
// visible — pinning that exactly one is ever shown at a time, and that a
// missing element (a page that never mounted one of the three, e.g. in
// another test's stub) doesn't throw.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const els = {
  mediaOverview: { style: { display: '' } },
  mediaDrilldown: { style: { display: 'none' } },
  libraryBlock: { style: { display: 'none' } },
};
globalThis.document = { getElementById: (id) => els[id] || null };

const { showMediathekView } = await import('../_view-toggle.js');

test('showing the drilldown hides the overview and the results grid', () => {
  showMediathekView('mediaDrilldown');
  assert.equal(els.mediaOverview.style.display, 'none');
  assert.equal(els.mediaDrilldown.style.display, '');
  assert.equal(els.libraryBlock.style.display, 'none');
});

test('showing the results grid hides both the overview and the drilldown', () => {
  showMediathekView('libraryBlock');
  assert.equal(els.mediaOverview.style.display, 'none');
  assert.equal(els.mediaDrilldown.style.display, 'none');
  assert.equal(els.libraryBlock.style.display, '');
});

test('showing the overview hides the drilldown and the results grid', () => {
  showMediathekView('mediaDrilldown'); // start from a non-default state
  showMediathekView('mediaOverview');
  assert.equal(els.mediaOverview.style.display, '');
  assert.equal(els.mediaDrilldown.style.display, 'none');
  assert.equal(els.libraryBlock.style.display, 'none');
});

test('a missing element in the DOM is skipped without throwing', () => {
  const original = globalThis.document.getElementById;
  globalThis.document.getElementById = (id) => (id === 'mediaOverview' ? els.mediaOverview : null);
  try {
    assert.doesNotThrow(() => showMediathekView('mediaOverview'));
  } finally {
    globalThis.document.getElementById = original;
  }
});
