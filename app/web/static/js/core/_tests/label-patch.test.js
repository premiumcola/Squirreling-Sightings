// ─── core/_tests/label-patch.test.js ───────────────────────────────────────
// The fields a label save hands back, and the three ways a naive copy
// of them goes wrong: blanking a field the reply never mentioned,
// dropping a null that MEANS something, and sharing one array between
// the caches so a later edit to one rewrites the rest.
//
// whole_clip/detections joined the reply later, for a different bug:
// the object-list panel's per-row heading reads THOSE, never
// labels/top_label, so a save that patched only the first four fields
// left every heading stuck on its pre-edit class forever.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { applyLabelPatch } from '../label-patch.js';

test('the four fields land on the target', () => {
  const item = { labels: ['bird'], top_label: 'bird', bird_species: 'Amsel', cat_name: null };
  applyLabelPatch(item, {
    ok: true,
    labels: ['cat'],
    top_label: 'cat',
    cat_name: 'Mimi',
    bird_species: null,
  });
  assert.deepEqual(item.labels, ['cat']);
  assert.equal(item.top_label, 'cat');
  assert.equal(item.cat_name, 'Mimi');
  assert.equal(item.bird_species, null);
});

test('a cleared identity is an answer, not a missing key', () => {
  // apply_label_change() nulls bird_species the moment `bird` leaves the
  // set. Treating null as "not sent" is how a disproven species survives
  // its own correction.
  const item = { bird_species: 'Grünfink', cat_name: 'Mimi' };
  applyLabelPatch(item, { labels: [], top_label: 'motion', cat_name: null, bird_species: null });
  assert.equal(item.bird_species, null);
  assert.equal(item.cat_name, null);
});

test('a field the reply never mentions is left alone', () => {
  const item = { labels: ['cat'], top_label: 'cat', cat_name: 'Mimi', bird_species: 'Amsel' };
  applyLabelPatch(item, { ok: true, labels: ['dog'] });
  assert.deepEqual(item.labels, ['dog']);
  assert.equal(item.top_label, 'cat');
  assert.equal(item.cat_name, 'Mimi');
  assert.equal(item.bird_species, 'Amsel');
});

test('top_label is never recomputed from labels on this side', () => {
  // sync_top_label() is the backend's own derivation and the ledger is
  // booked against it. A frontend guess that disagreed would show one
  // verdict and have filed another.
  const item = {};
  applyLabelPatch(item, { labels: ['bird', 'cat'], top_label: 'cat' });
  assert.equal(item.top_label, 'cat');
});

test('a non-array labels field cannot blank the set', () => {
  const item = { labels: ['cat'] };
  applyLabelPatch(item, { ok: true, labels: null });
  assert.deepEqual(item.labels, ['cat']);
});

test('each target gets its own array', () => {
  const res = { labels: ['cat'], top_label: 'cat' };
  const a = {};
  const b = {};
  applyLabelPatch(a, res);
  applyLabelPatch(b, res);
  a.labels.push('dog');
  assert.deepEqual(b.labels, ['cat']);
  assert.deepEqual(res.labels, ['cat']);
});

test('a missing target or reply is a no-op, not a throw', () => {
  assert.equal(applyLabelPatch(null, { labels: ['cat'] }), null);
  const item = { labels: ['cat'] };
  assert.equal(applyLabelPatch(item, null), item);
  assert.deepEqual(applyLabelPatch(item, 'nope').labels, ['cat']);
});

test('whole_clip lands so the object-list heading stops reading a stale label', () => {
  const item = {
    whole_clip: { detections: [{ label: 'person', score: 0.8 }], frames: 5 },
  };
  applyLabelPatch(item, {
    labels: ['bird'],
    whole_clip: { detections: [{ label: 'motion', score: 0.8 }], frames: 5 },
  });
  assert.equal(item.whole_clip.detections[0].label, 'motion');
});

test('detections (the trigger-frame fallback) lands the same way', () => {
  const item = { detections: [{ label: 'person' }] };
  applyLabelPatch(item, { labels: [], detections: [{ label: 'motion' }] });
  assert.equal(item.detections[0].label, 'motion');
});

test('whole_clip/detections absent from the reply leave the cached copy alone', () => {
  const item = { whole_clip: { detections: [{ label: 'bird' }] }, detections: [{ label: 'cat' }] };
  applyLabelPatch(item, { labels: ['bird'] });
  assert.equal(item.whole_clip.detections[0].label, 'bird');
  assert.equal(item.detections[0].label, 'cat');
});
