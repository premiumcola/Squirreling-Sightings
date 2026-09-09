// ─── vplayer/panels/_tests/reclassify.test.js ──────────────────────────────
// The correction sheet's lifecycle — WHEN it goes away, and who is told.
//
// The report this pins down: „Nach jeder Änderung schliesst sich das
// edit menü - muss ich speichern oder fertig drücken damits übernommen
// wird?! - verwirrend!". Every tap in the sheet is already a save (one
// toggle, one POST — see _reclassify.js's header), but the panel
// repainted its row list on each reply and the sheet, being a child of a
// row, went with it. That reads as "it cancelled", which is the opposite
// of what happened.
//
// So the sheet now stays up until the operator says "Fertig", and
// announces THAT close (and only that one) through `onClosed`, which is
// the caller's cue to let its row list catch up. A programmatic
// `teardown()` — the owner opening a second sheet, or the whole panel
// going away — must NOT fire it: the owner already knows, and repainting
// there would tear the row out from under the sheet about to be mounted
// on it (_recorded.js::onEdit).
//
// The sheet only ever calls createElement/appendChild/addEventListener
// and assigns innerHTML, so plain objects are a complete stand-in — the
// same no-DOM-library rule objects-list.test.js follows.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { openReclassify, toggleLabel, labelsRequestFor } from '../_reclassify.js';

function _fakeEl() {
  const el = {
    className: '',
    innerHTML: '',
    listeners: {},
    removed: false,
    children: [],
    appendChild(child) {
      this.children.push(child);
    },
    addEventListener(type, fn) {
      el.listeners[type] = fn;
    },
    removeEventListener(type) {
      delete el.listeners[type];
    },
    remove() {
      el.removed = true;
    },
  };
  return el;
}

/** A click whose target resolves the two selectors the sheet asks for. */
function _click(sheet, { label = null, act = null } = {}) {
  const target = {
    closest(sel) {
      if (sel === '[data-label]') return label ? { dataset: { label } } : null;
      if (sel === '[data-act]') return act ? { dataset: { act } } : null;
      return null;
    },
  };
  return sheet.listeners.click({ target });
}

function _open(deps = {}) {
  const created = [];
  globalThis.document = {
    createElement: () => {
      const el = _fakeEl();
      created.push(el);
      return el;
    },
  };
  const host = _fakeEl();
  const item = { camera_id: 'cam1', event_id: 'evt1', labels: ['dog', 'motion'] };
  const handle = openReclassify(host, item, {
    request: async () => ({ ok: true, labels: [], top_label: 'motion' }),
    ...deps,
  });
  return { handle, sheet: created[0], item };
}

// ── the pure halves, unchanged by the lifecycle work ────────────────────

test('toggleLabel removes a present label and adds an absent one', () => {
  assert.deepEqual(toggleLabel(['dog', 'motion'], 'dog').sort(), ['motion']);
  assert.deepEqual(toggleLabel(['motion'], 'dog').sort(), ['dog', 'motion']);
});

test('labelsRequestFor needs both ids', () => {
  assert.equal(labelsRequestFor({ camera_id: 'c' }, []), null);
  assert.equal(
    labelsRequestFor({ camera_id: 'c', event_id: 'e' }, ['dog']).url,
    '/api/camera/c/events/e/labels',
  );
});

// ── the lifecycle ───────────────────────────────────────────────────────

test('a chip toggle saves and leaves the sheet standing', async () => {
  const saved = [];
  const { handle, sheet } = _open({ onSaved: (res, labels) => saved.push(labels) });

  await _click(sheet, { label: 'dog' });

  assert.equal(saved.length, 1, 'the toggle must POST and report back');
  assert.deepEqual(saved[0], ['motion'], 'dog comes off, the rest stays');
  assert.equal(sheet.removed, false, 'the sheet must survive its own save');
  handle.teardown();
});

test('"Fehlalarm · alle entfernen" posts an empty set and keeps the sheet', async () => {
  const saved = [];
  const { handle, sheet } = _open({ onSaved: (res, labels) => saved.push(labels) });

  await _click(sheet, { act: 'none' });

  assert.deepEqual(saved[0], []);
  assert.equal(sheet.removed, false);
  handle.teardown();
});

test('"Fertig" closes the sheet AND announces it', async () => {
  let closed = 0;
  const { sheet } = _open({ onClosed: () => (closed += 1) });

  await _click(sheet, { act: 'close' });

  assert.equal(sheet.removed, true);
  assert.equal(closed, 1, 'the caller has to know it may repaint its rows now');
});

test('teardown() closes the sheet WITHOUT announcing it', () => {
  let closed = 0;
  const { handle, sheet } = _open({ onClosed: () => (closed += 1) });

  handle.teardown();

  assert.equal(sheet.removed, true);
  assert.equal(
    closed,
    0,
    'the owner tore it down itself — a repaint here would remove the row ' +
      'the next sheet is about to be mounted on',
  );
});

test('a failed save reports the error and still leaves the sheet up', async () => {
  const errors = [];
  const { sheet } = _open({
    request: async () => {
      throw new Error('offline');
    },
    onError: (m) => errors.push(m),
  });

  await _click(sheet, { label: 'dog' });

  assert.equal(errors.length, 1);
  assert.match(errors[0], /offline/);
  assert.equal(sheet.removed, false);
});
