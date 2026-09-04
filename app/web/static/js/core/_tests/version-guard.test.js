// A tab has to be able to tell that it is running old code.
//
// This is the defect the guard exists for: the operator looked at a
// dashboard whose JavaScript was current and whose CSS was weeks old,
// and every surface that could have said so reported the SERVER's
// version. „ich hab den neuen player bei mir auch einfach nicht drin ..
// ich seh noch gar nix" — with no way, from inside the tab, to find out.

import { test } from 'node:test';
import assert from 'node:assert/strict';

/** A DOM stub just deep enough for the guard: a head that can answer the
 *  meta query, a body that collects appended nodes, and elements that
 *  record their own listeners. */
function makeDom(bootHash) {
  const appended = [];
  const listeners = {};
  const mkEl = () => {
    const el = {
      className: '',
      innerHTML: '',
      attrs: {},
      removed: false,
      setAttribute(k, v) {
        this.attrs[k] = v;
      },
      addEventListener(ev, fn) {
        (this.listeners ||= {})[ev] = fn;
      },
      remove() {
        this.removed = true;
      },
      // Selector-AWARE. A stub that hands the same node back for every
      // query silently wires both buttons to one element, and the last
      // listener registered wins — which made a click on "Neu laden"
      // run the dismiss handler instead. The stub has to tell the
      // buttons apart or the test proves nothing about either.
      querySelector(sel) {
        this._q ||= {};
        return (this._q[sel] ||= mkEl());
      },
    };
    return el;
  };
  return {
    appended,
    listeners,
    document: {
      hidden: false,
      querySelector: (sel) =>
        sel === 'meta[name="shell-version"]' && bootHash !== null ? { content: bootHash } : null,
      createElement: () => mkEl(),
      addEventListener: (ev, fn) => {
        listeners[ev] = fn;
      },
      body: { appendChild: (n) => appended.push(n) },
    },
  };
}

/** Load version-guard.js against a stubbed global environment. Each call
 *  gets a fresh module instance — the guard holds state. */
async function loadGuard({ bootHash = 'aaa', serverHash = 'aaa', fetchFails = false } = {}) {
  const dom = makeDom(bootHash);
  const reloads = [];
  const cleared = { sw: 0, caches: 0 };

  // `navigator` is getter-only on globalThis in modern Node, so a plain
  // assignment throws — defineProperty is the only way to stand one in.
  const stub = (name, value) =>
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });

  stub('document', dom.document);
  stub('location', { reload: () => reloads.push(1) });
  stub('window', { __version: null });
  stub('navigator', {
    serviceWorker: {
      getRegistrations: async () => [{ unregister: async () => cleared.sw++ }],
    },
  });
  stub('caches', {
    keys: async () => ['squirreling-shell-old'],
    delete: async () => cleared.caches++,
  });
  stub('fetch', async () => {
    if (fetchFails) throw new Error('offline');
    return { ok: true, json: async () => ({ shell_hash: serverHash }) };
  });
  stub('setInterval', () => 0);

  // Cache-bust the module so state does not leak between tests.
  const mod = await import(`../version-guard.js?t=${Math.random()}`);
  return { mod, dom, reloads, cleared };
}

test('a matching build shows nothing', async () => {
  const { mod, dom } = await loadGuard({ bootHash: 'same', serverHash: 'same' });
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(dom.appended.length, 0, 'a current tab must stay silent');
});

test('a stale tab says so', async () => {
  const { mod, dom } = await loadGuard({ bootHash: 'old', serverHash: 'new' });
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(dom.appended.length, 1);
  assert.match(dom.appended[0].innerHTML, /ältere/i);
});

test('a document with no stamp at all counts as stale', async () => {
  // A tab booted from a build older than this feature has no meta tag.
  // That is precisely the case that must be caught, not skipped.
  const { mod, dom } = await loadGuard({ bootHash: null, serverHash: 'new' });
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(dom.appended.length, 1);
});

test('being offline never cries wolf', async () => {
  const { mod, dom } = await loadGuard({ bootHash: 'old', fetchFails: true });
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(dom.appended.length, 0, 'a failed check is not evidence of staleness');
});

test('the bar is announced only once', async () => {
  const { mod, dom } = await loadGuard({ bootHash: 'old', serverHash: 'new' });
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  await dom.listeners.visibilitychange?.();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(dom.appended.length, 1, 'a second check must not stack a second bar');
});

test('the reload button clears the worker and the caches first', async () => {
  // A plain reload would be served the SAME stale bundle by the same
  // service worker. This is the whole reason the button is not a link.
  const { mod, dom, reloads, cleared } = await loadGuard({ bootHash: 'old', serverHash: 'new' });
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  const bar = dom.appended[0];
  await bar.querySelector('.version-bar-btn').listeners.click();
  assert.equal(cleared.sw, 1, 'service worker was not unregistered');
  assert.equal(cleared.caches, 1, 'caches were not emptied');
  assert.equal(reloads.length, 1);
});

test('__version answers what the tab and the server are running', async () => {
  const { mod } = await loadGuard({ bootHash: 'old', serverHash: 'new' });
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(globalThis.window.__version(), { tab: 'old', server: 'new' });
});

test('the bar can be dismissed without reloading', async () => {
  // Being one deploy behind breaks nothing, and the bar is fixed over
  // the content — on a phone it sits exactly where the navigation dock
  // is. A notice with no way out would cost the operator their
  // navigation until they reload.
  const { mod, dom, reloads } = await loadGuard({ bootHash: 'old', serverHash: 'new' });
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  const bar = dom.appended[0];
  await bar.querySelector('.version-bar-close').listeners.click();
  assert.equal(bar.removed, true, 'the dismiss did not take the bar off the page');
  assert.equal(reloads.length, 0, 'dismissing must not reload');
});

test('a dismissed bar stays gone for this tab', async () => {
  const { mod, dom } = await loadGuard({ bootHash: 'old', serverHash: 'new' });
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  await dom.appended[0].querySelector('.version-bar-close').listeners.click();
  await dom.listeners.visibilitychange?.();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(dom.appended.length, 1, 'the bar came back after being dismissed');
});

test('starting twice does not stack timers or listeners', async () => {
  // Documented as idempotent, and it has to actually be: a second call
  // used to add a second interval and a second visibilitychange
  // listener, and stopVersionGuard removed neither.
  let intervals = 0;
  const { mod, dom } = await loadGuard({ bootHash: 'same', serverHash: 'same' });
  Object.defineProperty(globalThis, 'setInterval', {
    value: () => ++intervals,
    writable: true,
    configurable: true,
  });
  mod.startVersionGuard();
  mod.startVersionGuard();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(intervals, 1, 'a second start added a second interval');
  assert.equal(typeof dom.listeners.visibilitychange, 'function');
});
