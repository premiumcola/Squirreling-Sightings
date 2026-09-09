// ─── mediaview/panels/_tests/species-picker.test.js ────────────────────────
// Two things this module promises: the picker's ROWS mirror the
// Telegram-side `species_correction_markup` exactly (dedupe, drop the
// current guess, cap at 5, unsicher+cancel always present — see
// `test_telegram_species_correction.py`'s own picker tests, the
// reference this was built to match), and a successful pick reaches
// whatever `onSaved` the caller wired, unpatched-item in, patched-item
// out — the actual network+patch step, not a simulated DOM click.
//
// `window`/`document`/`fetch` stubs follow mediathek/_tests/processing.
// test.js's style: plain objects, no DOM library. `showToast` (imported
// transitively for the error path) reads `document.getElementById`, so
// `document` has to exist before the module is imported — same ordering
// reasoning as vplayer/panels/_tests/_setup.js.
import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis.window || {};
globalThis.document = { getElementById: () => null };

const _JSON_HEADERS = { get: () => 'application/json' };

let fetchCalls = [];
let fetchResponse = { ok: true, headers: _JSON_HEADERS, json: async () => ({}) };
globalThis.fetch = async (url, init) => {
  fetchCalls.push({ url, init });
  return fetchResponse;
};

const { speciesPickerRows, submitSpeciesCorrection } = await import('../species-picker.js');
const { applyLabelPatch } = await import('../../../core/label-patch.js');

// ── speciesPickerRows — mirrors species_correction_markup ──────────────

test('candidates are deduped, the current guess is dropped, order kept', () => {
  const candidates = [
    { name: 'Elster', latin: 'Pica pica', score: 0.59 },
    { name: 'Kohlmeise', latin: 'Parus major', score: 0.31 },
    { name: 'Elster', latin: 'Pica pica', score: 0.59 }, // duplicate
    { name: null, latin: 'sp.', score: 0.1 }, // untranslated, dropped
  ];
  assert.deepEqual(speciesPickerRows(candidates, 'Elster'), ['Kohlmeise']);
});

test('the current-guess exclusion is case-insensitive', () => {
  const candidates = [{ name: 'elster' }, { name: 'Kohlmeise' }];
  assert.deepEqual(speciesPickerRows(candidates, 'ELSTER'), ['Kohlmeise']);
});

test('caps at 5 rows even with more candidates', () => {
  const candidates = Array.from({ length: 9 }, (_, i) => ({ name: `Art${i}` }));
  assert.equal(speciesPickerRows(candidates, null).length, 5);
});

test('no candidates and no current species is an empty row list', () => {
  assert.deepEqual(speciesPickerRows([], null), []);
  assert.deepEqual(speciesPickerRows(undefined, undefined), []);
});

test('a blank/whitespace name is skipped like an untranslated one', () => {
  const candidates = [{ name: '   ' }, { name: 'Kohlmeise' }];
  assert.deepEqual(speciesPickerRows(candidates, null), ['Kohlmeise']);
});

// ── submitSpeciesCorrection — the network + patch step ──────────────────

test('a successful pick patches the cached event object via onSaved', async () => {
  fetchCalls = [];
  fetchResponse = {
    ok: true,
    headers: _JSON_HEADERS,
    json: async () => ({ ok: true, bird_species: 'Kohlmeise' }),
  };
  const item = { camera_id: 'cam1', event_id: 'evt1', bird_species: 'Elster' };

  const res = await submitSpeciesCorrection(item, 'Kohlmeise', {
    onSaved: (r) => applyLabelPatch(item, r),
  });

  assert.equal(res.ok, true);
  assert.equal(item.bird_species, 'Kohlmeise');
  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0].url, '/api/camera/cam1/events/evt1/species');
  assert.equal(fetchCalls[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(fetchCalls[0].init.body), { species: 'Kohlmeise' });
});

test('"unsicher" posts species:null and still calls onSaved on ok:true', async () => {
  fetchCalls = [];
  fetchResponse = {
    ok: true,
    headers: _JSON_HEADERS,
    json: async () => ({ ok: true, bird_species: 'Elster' }),
  };
  const item = { camera_id: 'cam1', event_id: 'evt1', bird_species: 'Elster' };
  let savedWith = null;

  await submitSpeciesCorrection(item, null, { onSaved: (r) => (savedWith = r) });

  assert.deepEqual(JSON.parse(fetchCalls[0].init.body), { species: null });
  assert.deepEqual(savedWith, { ok: true, bird_species: 'Elster' });
});

test('a non-2xx response never calls onSaved and leaves the item untouched', async () => {
  fetchCalls = [];
  fetchResponse = { ok: false, status: 404, text: async () => 'Event nicht gefunden' };
  const item = { camera_id: 'cam1', event_id: 'evt1', bird_species: 'Elster' };
  let called = false;

  const res = await submitSpeciesCorrection(item, 'Kohlmeise', { onSaved: () => (called = true) });

  assert.equal(res, null);
  assert.equal(called, false);
  assert.equal(item.bird_species, 'Elster');
});
