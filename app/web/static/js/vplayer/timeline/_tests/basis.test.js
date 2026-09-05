// ─── vplayer/timeline/_tests/basis.test.js ─────────────────────────────────
// The rail draws ONE population per render. These cases pin which one it
// picks, and — the half that actually caused the bug — that a lane
// synthesised from the clip aggregate states only things that are true:
// no invented track number, no borrowed colour, and never the `masked` or
// `predicted` texture, which mean something specific to an operator.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { classColor } from '../../../core/class-colors.js';
import { liveTrackColor } from '../../../core/track-color.js';
import {
  TL_BASIS_CLIP,
  TL_BASIS_NONE,
  TL_BASIS_SIDECAR,
  TL_BASIS_TRIGGER,
  timelineBasis,
} from '../_basis.js';
import { mountTimeline } from '../index.js';
import { lanesHtml } from '../_lanes.js';
import { buildTimelineModel } from '../_model.js';

const OPTS = { duration: 20, preRoll: 3, postRoll: 4, threshold: 0.5 };

/** An event carrying a whole-clip aggregate. */
function clipItem(...detections) {
  return { whole_clip: { detections, species: [], frames: 120, truncated: false } };
}

/** A `_clip_tally.py` row, with only the fields the rail reads varying. */
function clipRow(over = {}) {
  return {
    track_id: 7,
    label: 'bird',
    species: null,
    score: 0.57,
    model: 'bird_classifier',
    frames: 12,
    first_s: 1.2,
    last_s: 7.8,
    ...over,
  };
}

/** A tracks.json sidecar track, as the fetcher stamps it. */
function sidecarTrack(num, label, t0, t1) {
  return {
    _num: num,
    label,
    color: liveTrackColor(num),
    samples: [
      { f: 0, t: t0, bbox: { x1: 10, y1: 10, x2: 20, y2: 20 }, score: 0.9, source: 'detect' },
      { f: 9, t: t1, bbox: { x1: 12, y1: 12, x2: 22, y2: 22 }, score: 0.9, source: 'detect' },
    ],
  };
}

const lanesOf = (item, tracks) => {
  const picked = timelineBasis(item, tracks);
  return { basis: picked.basis, lanes: buildTimelineModel(picked.tracks, OPTS).lanes };
};

// ── which population ───────────────────────────────────────────────────

test('the sidecar wins whenever it has tracks, even beside an aggregate', () => {
  // The rail wants TIMING, and only the sidecar has per-sample t/source/
  // score. Its numbering is also what the boxes and the `#N` chips share.
  const sidecar = { tracks: [sidecarTrack(1, 'cat', 5, 9)] };
  const { basis, lanes } = lanesOf(clipItem(clipRow()), sidecar);
  assert.equal(basis, TL_BASIS_SIDECAR);
  assert.equal(lanes.length, 1);
  assert.equal(lanes[0].trackNum, 1, 'the sidecar lane keeps its own number');
  assert.equal(lanes[0].label, 'cat');
});

test('an empty sidecar beside a populated aggregate draws clip lanes', () => {
  // THE REPORTED BUG. The panel listed "Vogel 57 %" and the rail above it
  // was a bare grey line, because it was fed the sidecar and nothing else.
  for (const empty of [null, undefined, {}, { tracks: [] }, { tracks: null, built_at: 1 }]) {
    const { basis, lanes } = lanesOf(clipItem(clipRow()), empty);
    assert.equal(basis, TL_BASIS_CLIP);
    assert.equal(lanes.length, 1, 'a listed subject must have a lane');
    assert.equal(lanes[0].barT0, 1.2);
    assert.equal(lanes[0].barT1, 7.8);
  }
});

test('both populations empty draws no lanes and does not throw', () => {
  for (const item of [null, undefined, {}, { whole_clip: null }, clipItem()]) {
    const { basis, lanes } = lanesOf(item, { tracks: [] });
    assert.equal(basis, TL_BASIS_NONE);
    assert.deepEqual(lanes, []);
  }
});

test('an event with neither key falls back to its trigger frame', () => {
  // Every clip in the archive from before the aggregate existed. It used
  // to reach the model with an empty list and draw nothing — which is
  // precisely what was reported: „auch hier ist 'n Vogel drin. Keine
  // Box." The bird is on `detections`, and that is a third source.
  const old = { event_id: 'evt_2026_0101', type: 'motion', detections: [{ label: 'bird' }] };
  const picked = timelineBasis(old, null, { triggerT: 3 });
  assert.equal(picked.basis, TL_BASIS_TRIGGER);
  const m = buildTimelineModel(picked.tracks, OPTS);
  assert.equal(m.lanes.length, 1);
  assert.equal(m.lanes[0].label, 'bird');
  // ONE INSTANT, never a span: the trigger frame has no duration and
  // claiming one would invent what the sidecar exists to measure.
  assert.equal(m.lanes[0].barT0, 3);
  assert.equal(m.lanes[0].barT1, 3);
  assert.equal(m.firstEventT, 3);
});

test('mehrere Auslöse-Erkennungen derselben Klasse werden EINE Spur', () => {
  // Die Achse ist Zeit, und ein Auslöse-Bild ist ein Augenblick. Zwei
  // „Person"-Zeilen auf demselben Tick, mit demselben Namen, sind durch
  // nichts zu unterscheiden — „da passt so einiges nicht". Der beste
  // Wert der Klasse gewinnt; WIE VIELE es waren, steht als Kästen im
  // Bild und als Zeilen in der Objektliste.
  const item = {
    detections: [
      { label: 'person', score: 0.41 },
      { label: 'person', score: 0.58 },
      { label: 'bird', score: 0.62 },
    ],
  };
  const picked = timelineBasis(item, null, { triggerT: 2 });
  assert.equal(picked.basis, TL_BASIS_TRIGGER);
  assert.equal(picked.tracks.length, 2, 'zwei Klassen, nicht drei Erkennungen');
  const person = picked.tracks.find((t) => t.label === 'person');
  assert.equal(person.samples[0].score, 0.58, 'der beste Wert der Klasse');
});

test('an event with no detections at all still draws nothing', () => {
  const bare = { event_id: 'evt_2026_0101', type: 'motion' };
  const picked = timelineBasis(bare, null);
  assert.deepEqual(picked, { basis: TL_BASIS_NONE, tracks: [] });
  const m = buildTimelineModel(picked.tracks, OPTS);
  assert.deepEqual(m.lanes, []);
  assert.equal(m.firstEventT, null);
});

test('the sidecar and the aggregate both outrank the trigger frame', () => {
  // The third basis is a fallback, not a merge. A clip that HAS per-frame
  // geometry must never be drawn from its one trigger instant instead.
  const item = { ...clipItem(clipRow()), detections: [{ label: 'bird' }] };
  assert.equal(timelineBasis(item, null).basis, TL_BASIS_CLIP);
  assert.equal(
    timelineBasis(item, { tracks: [sidecarTrack(1, 'cat', 5, 9)] }).basis,
    TL_BASIS_SIDECAR,
  );
});

test('a malformed aggregate is treated as no aggregate at all', () => {
  for (const bad of [{ whole_clip: { detections: 'rows' } }, { whole_clip: { detections: {} } }]) {
    assert.equal(timelineBasis(bad, null).basis, TL_BASIS_NONE);
  }
  // Rows that cannot be placed on a rail are dropped, and an aggregate of
  // nothing BUT those falls through rather than reporting an empty clip
  // basis.
  const unplaceable = clipItem(clipRow({ first_s: null }), clipRow({ first_s: 'soon' }));
  assert.equal(timelineBasis(unplaceable, null).basis, TL_BASIS_NONE);
});

// ── what a clip lane may state ─────────────────────────────────────────

test('a one-frame subject keeps its dot and a zero-length bar', () => {
  const { lanes } = lanesOf(clipItem(clipRow({ first_s: 4, last_s: 4 })), null);
  assert.equal(lanes.length, 1, 'dropping the lane would hide the detection');
  assert.deepEqual(
    { dot: lanes[0].dotT, t0: lanes[0].barT0, t1: lanes[0].barT1 },
    { dot: 4, t0: 4, t1: 4 },
  );
});

test('a two-point row paints one honest confirmed run', () => {
  // Not `predicted` (the tracker never carried this forward) and not
  // `masked` (the aggregate only ever holds detections that survived the
  // masks). Both textures tell the operator something specific.
  const { lanes } = lanesOf(clipItem(clipRow()), null);
  assert.deepEqual(lanes[0].segments, [{ status: 'confirmed', t0: 1.2, t1: 7.8 }]);
  assert.equal(lanes[0].status, 'confirmed');
});

test('masks configured on the clip cannot make a clip lane read as masked', () => {
  const masks = [
    {
      points: [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 100, y: 100 },
        { x: 0, y: 100 },
      ],
    },
  ];
  const picked = timelineBasis(clipItem(clipRow()), null);
  const m = buildTimelineModel(picked.tracks, { ...OPTS, masks, srcW: 100, srcH: 100 });
  assert.equal(m.lanes[0].status, 'confirmed', 'a false "masked" says the mask is broken');
});

test('a subject that never beat the spawn threshold reads weak', () => {
  // The one case where a clip lane SHOULD be dashed: the row's score is
  // its BEST over the whole clip, so under the threshold means it never
  // once got above it.
  const { lanes } = lanesOf(clipItem(clipRow({ score: 0.2 })), null);
  assert.equal(lanes[0].status, 'weak');
});

test('a clip lane carries no track number', () => {
  // The aggregate's track_id comes from the live tracker's run; the `#N`
  // chips and box strokes read the sidecar's. No number is honest.
  const { lanes } = lanesOf(clipItem(clipRow({ track_id: 7 })), null);
  assert.equal(lanes[0].trackNum, null);
  assert.ok(!lanesHtml({ lanes, duration: 20 }).includes('#7'));
});

test('a clip lane is coloured by class, never out of the numbering palette', () => {
  const { lanes } = lanesOf(clipItem(clipRow({ label: 'squirrel' })), null);
  assert.equal(lanes[0].colour, classColor('squirrel'));
  const numbered = new Set([1, 2, 3, 4, 5, 6, 7, 8].map(liveTrackColor));
  assert.ok(!numbered.has(lanes[0].colour), 'reusing the track palette would claim an identity');
});

// ── how a lane is named ────────────────────────────────────────────────

test('a named bird lane is called by its species', () => {
  const { lanes } = lanesOf(clipItem(clipRow({ label: 'bird', species: 'Grünfink' })), null);
  const html = lanesHtml({ lanes, duration: 20 });
  assert.ok(html.includes('Grünfink'), 'the objects list already calls it that');
  assert.ok(!html.includes('>Vogel<'));
});

test('an unidentified bird keeps its German class name', () => {
  const { lanes } = lanesOf(clipItem(clipRow({ label: 'bird', species: null })), null);
  assert.ok(lanesHtml({ lanes, duration: 20 }).includes('Vogel'));
});

test('a sidecar lane is named exactly as it was before the species rule', () => {
  const sidecar = { tracks: [sidecarTrack(2, 'cat', 5, 9)] };
  const { lanes } = lanesOf(null, sidecar);
  const html = lanesHtml({ lanes, duration: 20 });
  assert.ok(html.includes('#2 Katze'), 'number and German class, unchanged');
});

test('a lane with no class at all still has a name', () => {
  const sidecar = { tracks: [sidecarTrack(1, '', 5, 9)] };
  const { lanes } = lanesOf(null, sidecar);
  assert.ok(lanesHtml({ lanes, duration: 20 }).includes('#1 Objekt'));
});

// ── the basis on the DOM ───────────────────────────────────────────────

/**
 * The narrowest host mountTimeline actually touches. There is no DOM in
 * this test tree at all — every gate here is plain node — and the mount
 * reads `querySelector` (every hit guards on null) and writes
 * `innerHTML`, `dataset` and `style`, so the real element is not needed
 * to pin the one attribute a later reader will look for.
 *
 * `style` is here because the mount publishes the lane block's measured
 * height as a custom property for the playhead's riser. Every real
 * element has one; leaving it off the stub made the mount throw on a
 * host that could not exist.
 *
 * The listener pair and `querySelectorAll` are here for the same reason:
 * the mount delegates the rail beads' clicks off the host. A stub thinner
 * than the thing it stands for turns a working change into a red test —
 * which is the failure mode this file has now hit twice.
 */
const stubHost = () => ({
  dataset: {},
  innerHTML: '',
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
  style: { setProperty() {}, removeProperty() {} },
});

test('the rail records on itself which population it drew', () => {
  const host = stubHost();
  const tl = mountTimeline(host, { flags: { timeline: 'lanes' } }, {});
  const item = clipItem(clipRow());

  tl.render(timelineBasis(item, { tracks: [sidecarTrack(1, 'cat', 5, 9)] }).tracks, {
    ...OPTS,
    basis: TL_BASIS_SIDECAR,
  });
  assert.equal(host.dataset.basis, TL_BASIS_SIDECAR);

  tl.render(timelineBasis(item, null).tracks, { ...OPTS, basis: TL_BASIS_CLIP });
  assert.equal(host.dataset.basis, TL_BASIS_CLIP);

  // A render that names no basis must not leave the previous one behind
  // claiming these lanes came from somewhere they did not.
  tl.render([], OPTS);
  assert.equal(host.dataset.basis, TL_BASIS_NONE);

  tl.teardown();
  assert.equal(host.dataset.basis, undefined, 'a torn-down rail claims nothing');
});
