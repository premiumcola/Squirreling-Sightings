// ─── sichtungen/_tests/ach-defs.test.js ──────────────────────────────────
// Pure data + tier math — no DOM, no fetch, so this is a real import-and-
// exercise test (unlike _dossier-panel.js / _achievements.js, which pull
// in library/_bind.js's heavy module graph; see
// test_species_dossier_panel_js.py's docstring for why those fall back
// to source-level regression pins instead).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ACH_DEFS, _achTier, _rarityText } from '../_ach-defs.js';

test('tier boundaries: 0 is locked, 1-4 bronze, 5-19 silver, 20+ gold', () => {
  assert.equal(_achTier(0), 'locked');
  assert.equal(_achTier(undefined), 'locked');
  assert.equal(_achTier(1), 'bronze');
  assert.equal(_achTier(4), 'bronze');
  assert.equal(_achTier(5), 'silver');
  assert.equal(_achTier(19), 'silver');
  assert.equal(_achTier(20), 'gold');
  assert.equal(_achTier(500), 'gold');
});

test('every ACH_DEFS entry has a unique id', () => {
  const ids = ACH_DEFS.map((a) => a.id);
  assert.equal(new Set(ids).size, ids.length);
});

test('every ACH_DEFS entry has the fields the grid/dossier-panel lookup rely on', () => {
  for (const a of ACH_DEFS) {
    assert.equal(typeof a.id, 'string');
    assert.equal(typeof a.name, 'string');
    assert.ok(a.name.length > 0);
    assert.ok(a.cat === 'birds' || a.cat === 'mammals');
    assert.ok(
      a.freq in { 'sehr haeufig': 1, haeufig: 1, regelmaessig: 1, gelegentlich: 1, selten: 1 },
    );
  }
});

test('bird species names match the classifier latin_to_de map verbatim', () => {
  // sichtungen/_dossier-panel.js resolves a Tiere tile click to a
  // species dossier purely by matching ACH_DEFS' German a.name against
  // bird_dossiers.json's common_name_de (itself sourced from
  // config/inat_to_german.json). A silent rename on either side breaks
  // that lookup for exactly the species it drifts on — pin the current
  // Top-20 Bavarian bird names so a future edit here is a deliberate,
  // visible diff instead of a name that quietly stops resolving.
  const birdNames = ACH_DEFS.filter((a) => a.cat === 'birds').map((a) => a.name);
  assert.deepEqual(birdNames, [
    'Haussperling',
    'Amsel',
    'Kohlmeise',
    'Star',
    'Feldsperling',
    'Blaumeise',
    'Ringeltaube',
    'Mauersegler',
    'Elster',
    'Mehlschwalbe',
    'Buchfink',
    'Rotkehlchen',
    'Grünfink',
    'Rabenkrähe',
    'Hausrotschwanz',
    'Mönchsgrasmücke',
    'Stieglitz',
    'Buntspecht',
    'Kleiber',
    'Eichelhäher',
  ]);
});

test('_rarityText colours a locked entry neutral grey regardless of rank', () => {
  const locked = _rarityText('selten', false);
  const unlocked = _rarityText('selten', true);
  assert.match(locked, /rgba\(255,255,255,0\.25\)/);
  assert.doesNotMatch(unlocked, /rgba\(255,255,255,0\.25\)/);
});

test('_rarityText returns an empty string for an unknown frequency key', () => {
  assert.equal(_rarityText('nonexistent', true), '');
});
