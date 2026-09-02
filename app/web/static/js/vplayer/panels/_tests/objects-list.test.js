// ─── vplayer/panels/_tests/objects-list.test.js ────────────────────────────
// What the detected-object list actually RENDERS.
//
// The row builder is proved next door in _data/_tests/map.test.js; this
// file exists for the one promise that cannot be proved on the rows
// alone — that a clip recorded before the whole-clip aggregate existed
// comes out of the renderer byte-for-byte as it always did. Preferring a
// new source is only safe if the old ones are untouched, and "untouched"
// is a claim about markup, not about a field.
//
// The frozen strings below were captured by running this exact renderer
// and diffing — not by reading the template and writing down what it
// ought to produce.
//
// They were re-frozen once, when the per-row delete button was removed
// (it rendered a 44 px control that no backend could serve — see
// _objects-list.js's header). That edit is DELIBERATELY not a
// regression: it changes every basis identically, which is the shape a
// chrome change is allowed to have here. What these strings still
// forbid is a change that lands on ONE basis — an old event drifting
// because a feature about new events touched the shared renderer.
//
// The renderer needs a host element. It only ever calls addEventListener
// and assigns innerHTML, so a plain object is a complete stand-in and no
// DOM library is pulled in for it.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { objectRowsFor, objectsNote } from '../../_data/_map.js';
import { renderObjectsList } from '../_objects-list.js';

/** A host the renderer is satisfied by, with no DOM behind it. */
function fakeHost() {
  return { addEventListener() {}, removeEventListener() {}, innerHTML: '' };
}

/**
 * The rendered markup with the two inline icon SVGs collapsed away.
 *
 * They are ~200 unchanging characters per row and turn every assertion
 * below into something no reader can check. Everything this feature can
 * affect — the class name, the score, the number chip, the lane colour,
 * the reason line, the footnote — survives the collapse.
 */
function render(item, tracks, models) {
  const host = fakeHost();
  const list = renderObjectsList(host, {});
  const rows = objectRowsFor(item, tracks);
  list.update(rows, models || null, objectsNote(rows, item));
  return host.innerHTML.replaceAll(/<svg\b[^>]*>.*?<\/svg>/g, '');
}

// ── old events: frozen ─────────────────────────────────────────────────

const SIDECAR = {
  tracks: [
    { _num: 1, label: 'person', color: '#22c55e', best_score: 0.91, model: 'detector', samples: [{ t: 3 }, { t: 11 }] }, // prettier-ignore
    { _num: 2, label: 'bird', best_score: 0.44, model: 'bird_classifier', samples: [{ t: 5 }] },
  ],
};

const OLD_SIDECAR_HTML =
  '<div class="vp-pnl-row vp-pnl-obj" data-key="track:1" style="--vp-lane-colour:#22c55e">' +
  '<span class="vp-pnl-num">#1</span><span class="vp-pnl-cls">Person</span>' +
  '<span class="vp-pnl-score">91 %</span>' +
  '<button type="button" class="vp-pnl-iconbtn" data-act="edit" aria-label="Erkennungen dieser Aufnahme korrigieren"></button>' +
  '<span class="vp-pnl-reason">0:03–0:11 · Objekt-Detektor</span></div>' +
  '<div class="vp-pnl-row vp-pnl-obj" data-key="track:2" style="--vp-lane-colour:#f6b73c">' +
  '<span class="vp-pnl-num">#2</span><span class="vp-pnl-cls">Vogel</span>' +
  '<span class="vp-pnl-score">44 %</span>' +
  '<button type="button" class="vp-pnl-iconbtn" data-act="edit" aria-label="Erkennungen dieser Aufnahme korrigieren"></button>' +
  '<span class="vp-pnl-reason">0:05 · Vogel-Klassifikator</span></div>';

test('an event with only a sidecar still renders from the sidecar, frozen', () => {
  assert.equal(render({}, SIDECAR), OLD_SIDECAR_HTML);
});

test('an event with only a trigger frame still renders from it, frozen', () => {
  // Note the species on the detection: `detections[]` has carried one
  // for a long time and the row has never shown it. Surfacing it here
  // would silently restyle the entire existing archive, so this branch
  // deliberately leaves it alone — see _map.js::_frameRows.
  const item = {
    detections: [{ label: 'bird', score: 0.7, model: 'bird_classifier', species: 'Grünfink' }],
  };
  assert.equal(
    render(item, null),
    '<div class="vp-pnl-row vp-pnl-obj" data-key="det:0" style="--vp-lane-colour:var(--muted)">' +
      '<span class="vp-pnl-cls">Vogel</span><span class="vp-pnl-score">70 %</span>' +
      '<button type="button" class="vp-pnl-iconbtn" data-act="edit" aria-label="Erkennungen dieser Aufnahme korrigieren"></button>' +
      '<span class="vp-pnl-reason">— · Vogel-Klassifikator</span></div>',
  );
});

test('an old event never grows a footnote', () => {
  // The footnote is the one piece of new chrome in the list. If it can
  // appear without a whole_clip block, every archived clip has changed.
  assert.ok(!render({}, SIDECAR).includes('vp-pnl-note'));
  assert.ok(!render({ detections: [{ label: 'cat', score: 0.4 }] }, null).includes('vp-pnl-note'));
});

test('a clip with nothing in it still says so', () => {
  assert.equal(
    render({}, null),
    '<div class="vp-pnl-empty">Keine Objekte in dieser Aufnahme</div>',
  );
});

// ── new events: the whole clip ─────────────────────────────────────────

const TWO_BIRDS = {
  whole_clip: {
    detections: [
      { label: 'bird', score: 0.88, species: 'Grünfink', model: 'bird_classifier', first_s: 1, last_s: 4 }, // prettier-ignore
      { label: 'bird', score: 0.71, species: 'Blaumeise', model: 'bird_classifier', first_s: 6, last_s: 9 }, // prettier-ignore
    ],
    species: [{ species: 'Grünfink' }, { species: 'Blaumeise' }],
    frames: 40,
    truncated: false,
  },
};

test('two birds in one clip are named separately — the whole point', () => {
  const html = render(TWO_BIRDS, SIDECAR);
  assert.ok(html.includes('>Grünfink<'), 'first species missing');
  assert.ok(html.includes('>Blaumeise<'), 'second species missing');
  // and not once as the generic class they share
  assert.ok(!html.includes('>Vogel<'));
});

test('a whole-clip row shows the span it was present for', () => {
  assert.ok(render(TWO_BIRDS, null).includes('0:01–0:04'));
});

test('a whole-clip row carries no number chip it cannot back up', () => {
  // #N and the lane colour belong to the sidecar's numbering, which the
  // timeline and the boxes read. This basis has no lane to point at.
  const html = render(TWO_BIRDS, SIDECAR);
  assert.ok(!html.includes('vp-pnl-num'));
  assert.ok(html.includes('--vp-lane-colour:var(--muted)'));
});

test('a truncated list says it is partial, once, under the rows', () => {
  const item = { whole_clip: { ...TWO_BIRDS.whole_clip, truncated: true } };
  const html = render(item, null);
  assert.ok(html.endsWith('<div class="vp-pnl-note">Ganzer Clip · Liste gekürzt</div>'));
  // once, not per row
  assert.equal(html.split('vp-pnl-note').length - 1, 1);
});

test('an unidentified bird in a whole-clip row still reads as Vogel', () => {
  const item = {
    whole_clip: { detections: [{ label: 'bird', score: 0.5, first_s: 0, last_s: 1 }], species: [] },
  };
  assert.ok(render(item, null).includes('>Vogel<'));
});
