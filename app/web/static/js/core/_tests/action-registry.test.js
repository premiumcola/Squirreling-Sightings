// ─── core/_tests/action-registry.test.js ────────────────────────────────
// The one global `data-action` delegator, and specifically what happens
// when a registered handler FAILS.
//
// Most handlers wired through here are async writes — `toggleCoralSetting`
// (camedit/coral-test.js), `saveMqttSettings` (camedit/mqtt-settings.js),
// `bulkDeleteSelectedMedia`. They all follow the same shape:
//
//     await apiPost(...);
//     showToast('… gespeichert', 'success');
//
// The success toast sits AFTER the await, so a rejected POST skips it.
// And `_handle` called `fn(target, ev)` without awaiting, so the
// rejection had nowhere to go: no `unhandledrejection` handler exists
// anywhere in this frontend (grepped), so the user saw a checkbox that
// stayed flipped in its new position, no toast of any kind, and settings
// that silently did not save. A control that reads as "done" when it
// isn't.
//
// The dispatcher is the right place to fix that once rather than in
// every handler: it is the single point every `data-action` passes
// through.
import { dispatch, actionEl } from './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { registerAction } from '../action-registry.js';

/** Run `body` with console.error captured. */
async function withConsole(body) {
  const realError = console.error;
  const seen = [];
  console.error = (...a) => seen.push(a);
  try {
    await body(seen);
  } finally {
    console.error = realError;
  }
}

// ── the happy paths still work ────────────────────────────────────────

test('a click dispatches to the handler registered under that action', () => {
  let calls = 0;
  registerAction('t_ok', () => {
    calls += 1;
  });
  dispatch('click', actionEl('t_ok'));
  assert.equal(calls, 1);
});

test('returning false calls preventDefault', () => {
  registerAction('t_false', () => false);
  const ev = dispatch('click', actionEl('t_false'));
  assert.equal(ev.defaultPrevented, true);
});

test('an element opting into a different event type ignores a click', () => {
  let calls = 0;
  registerAction('t_change', () => {
    calls += 1;
  });
  dispatch('click', actionEl('t_change', { actionEvent: 'change' }));
  assert.equal(calls, 0);
  dispatch('change', actionEl('t_change', { actionEvent: 'change' }));
  assert.equal(calls, 1);
});

test('an unregistered action name is a no-op, not a throw', () => {
  assert.doesNotThrow(() => dispatch('click', actionEl('t_nobody_registered_this')));
});

// ── the failure paths — the actual bug ────────────────────────────────

test('a handler that rejects is reported, not swallowed', async () => {
  await withConsole(async (seen) => {
    registerAction('t_reject', async () => {
      throw new Error('save failed');
    });
    dispatch('click', actionEl('t_reject'));
    // let the rejection settle
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(seen.length, 1, 'the rejected handler should have been reported');
    assert.match(seen[0].join(' '), /t_reject/);
  });
});

test('a handler that throws synchronously is reported, not propagated to the listener', async () => {
  await withConsole(async (seen) => {
    registerAction('t_throw', () => {
      throw new Error('boom');
    });
    assert.doesNotThrow(() => dispatch('click', actionEl('t_throw')));
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(seen.length, 1);
    assert.match(seen[0].join(' '), /t_throw/);
  });
});

test('a handler that resolves normally reports nothing', async () => {
  await withConsole(async (seen) => {
    registerAction('t_resolve', async () => 'fine');
    dispatch('click', actionEl('t_resolve'));
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(seen.length, 0);
  });
});

test('one failing action does not stop the next one from dispatching', async () => {
  await withConsole(async () => {
    let ran = 0;
    registerAction('t_bad', async () => {
      throw new Error('nope');
    });
    registerAction('t_good', () => {
      ran += 1;
    });
    dispatch('click', actionEl('t_bad'));
    dispatch('click', actionEl('t_good'));
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(ran, 1);
  });
});
