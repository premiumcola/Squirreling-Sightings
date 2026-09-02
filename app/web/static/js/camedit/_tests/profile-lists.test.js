// ─── camedit/_tests/profile-lists.test.js ───────────────────────────────
// Coverage for camedit/_profile-lists.js — the cat / person / audit side
// panels on the camera-settings tab.
//
// Why this matters far more than three read-only info panels suggest:
// `live-update.js::loadAll` awaits `renderProfiles()` and `renderAudit()`
// in the MIDDLE of the boot sequence, and `main.js` kicks it off as a
// bare `loadAll().then(...)` with no `.catch`. So anything these two
// throw aborts every remaining boot step — hydrateSettings, the Telegram
// panel, the push UI, the weather panels, initLibraryPage,
// startPreviewRefresh (the live camera previews) — AND the `.then` that
// starts the 3 s live-update poll. A 500 on `/api/cats`, an endpoint
// whose entire job is listing cat names, silently takes the dashboard
// down with it. These builders and their fetch helper are the layer that
// has to absorb that.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { optionalList, catListHTML, personListHTML, auditListHTML } from '../_profile-lists.js';

function withFetch(impl, run) {
  const real = globalThis.fetch;
  globalThis.fetch = impl;
  return (async () => {
    try {
      return await run();
    } finally {
      globalThis.fetch = real;
    }
  })();
}

const jsonRes = (body) => ({
  ok: true,
  headers: { get: () => 'application/json' },
  json: () => Promise.resolve(body),
});

// ── optionalList: the panel must not be able to abort the boot ─────────

test('optionalList returns the named array on the happy path', async () => {
  await withFetch(
    () => Promise.resolve(jsonRes({ profiles: [{ name: 'Minka' }] })),
    async () => {
      assert.deepEqual(await optionalList('/api/cats', 'profiles'), [{ name: 'Minka' }]);
    },
  );
});

test('a 500 on an optional panel resolves to an empty list, it does not throw', async () => {
  await withFetch(
    () => Promise.resolve({ ok: false, status: 500, text: () => Promise.resolve('boom') }),
    async () => {
      assert.deepEqual(await optionalList('/api/cats', 'profiles'), []);
    },
  );
});

test('a network failure on an optional panel resolves to an empty list', async () => {
  await withFetch(
    () => Promise.reject(new Error('network down')),
    async () => {
      assert.deepEqual(await optionalList('/api/telegram/actions', 'items'), []);
    },
  );
});

test('a 200 whose payload has no such key resolves to an empty list', async () => {
  await withFetch(
    () => Promise.resolve(jsonRes({ ok: true })),
    async () => {
      assert.deepEqual(await optionalList('/api/persons', 'profiles'), []);
    },
  );
});

test('a 200 whose key is not an array resolves to an empty list', async () => {
  await withFetch(
    () => Promise.resolve(jsonRes({ profiles: null })),
    async () => {
      assert.deepEqual(await optionalList('/api/persons', 'profiles'), []);
    },
  );
});

// ── the builders themselves ───────────────────────────────────────────

test('the cat list renders one row per profile', () => {
  const html = catListHTML([{ name: 'Minka' }, { name: 'Rocky' }]);
  assert.match(html, /Minka/);
  assert.match(html, /Rocky/);
});

test('an empty cat list falls back to the em-dash placeholder', () => {
  assert.match(catListHTML([]), /muted small">—</);
});

test('the person list marks a whitelisted profile and leaves others plain', () => {
  const html = personListHTML([
    { name: 'Anna', whitelisted: true },
    { name: 'Bob', whitelisted: false },
  ]);
  assert.match(html, /Anna<span class="muted small">\(Whitelist\)|Anna.*\(Whitelist\)/);
  assert.doesNotMatch(html.split('Bob')[1] || '', /Whitelist/);
});

test('a profile name is HTML-escaped, never injected raw', () => {
  assert.doesNotMatch(catListHTML([{ name: '<img src=x>' }]), /<img/);
});

test('the audit list renders action, time and an optional camera id', () => {
  const html = auditListHTML([{ action: 'snapshot', time: '10:00', camera_id: 'cam1' }]);
  assert.match(html, /snapshot/);
  assert.match(html, /10:00/);
  assert.match(html, /cam1/);
});

test('an empty audit list falls back to its own placeholder row', () => {
  assert.match(auditListHTML([]), /Noch keine Telegram-Aktionen/);
});

// A builder is only as safe as its worst caller. optionalList already
// guarantees an array, but these are exported and the panels are exactly
// the kind of thing a future callsite hands a raw response field to.

test('every builder tolerates a non-array, rather than throwing at the caller', () => {
  assert.doesNotThrow(() => catListHTML(undefined));
  assert.doesNotThrow(() => personListHTML(null));
  assert.doesNotThrow(() => auditListHTML(undefined));
});
