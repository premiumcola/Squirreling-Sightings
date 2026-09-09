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

const { allBirdPickerNames, submitSpeciesCorrection } = await import('../species-picker.js');
const { ACH_DEFS } = await import('../../../sichtungen/_ach-defs.js');
const { applyLabelPatch } = await import('../../../core/label-patch.js');

const CATALOGUE_SIZE = ACH_DEFS.filter((d) => d.cat === 'birds').length;

// ── allBirdPickerNames — candidates first, then the whole catalogue ─────
// The picker used to render event.species_candidates alone, capped at 5.
// That list is frequently empty, which left the sheet with nothing to
// tap but "unsicher" — the operator's report: "Spezies wechseln gibt
// keine sinnvollen Auswahlmöglichkeiten".

test('the achievement-board bird catalogue is always offered', () => {
  const names = allBirdPickerNames([], null);
  assert.equal(names.length, CATALOGUE_SIZE);
  assert.ok(names.includes('Kohlmeise'));
  assert.ok(names.includes('Elster'));
});

test('mammal achievements never leak into a bird-species picker', () => {
  const names = allBirdPickerNames([], null);
  assert.ok(!names.some((n) => n.startsWith('Eichhörnchen')));
  assert.ok(!names.includes('Igel'));
});

test("this event's own candidates come first, in order", () => {
  const candidates = [{ name: 'Stieglitz' }, { name: 'Buchfink' }];
  const names = allBirdPickerNames(candidates, null);
  assert.deepEqual(names.slice(0, 2), ['Stieglitz', 'Buchfink']);
  assert.equal(names.length, CATALOGUE_SIZE, 'a catalogue species must not be listed twice');
});

test('a candidate outside the catalogue is still offered', () => {
  const names = allBirdPickerNames([{ name: 'Stockente' }], null);
  assert.equal(names[0], 'Stockente');
  assert.equal(names.length, CATALOGUE_SIZE + 1);
});

test('the current guess is dropped, case-insensitively', () => {
  const names = allBirdPickerNames([{ name: 'elster' }], 'ELSTER');
  assert.ok(!names.some((n) => n.toLowerCase() === 'elster'));
  assert.equal(names.length, CATALOGUE_SIZE - 1);
});

test('blank and untranslated candidate names are skipped', () => {
  const names = allBirdPickerNames([{ name: '   ' }, { name: null }], null);
  assert.equal(names.length, CATALOGUE_SIZE);
});

test('a missing candidate list is not an empty picker', () => {
  assert.equal(allBirdPickerNames(undefined, undefined).length, CATALOGUE_SIZE);
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
