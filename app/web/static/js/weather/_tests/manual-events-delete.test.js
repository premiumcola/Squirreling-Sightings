// ─── weather/_tests/manual-events-delete.test.js ────────────────────────
// _wireDeleteButton — the press-again-in-place delete for a saved
// manual weather event, replacing a separate showConfirm() popup the
// operator reported rendering BEHIND the modal that opened it ("der
// Bestätigungsscreen... ist hinter dem eigentlichen Screen") with
// annotated screenshots. A first tap arms the button (no request
// fired yet); a second tap while armed fires the real DELETE; letting
// the arm timer lapse (or any other reset) disarms it, so a stray tap
// minutes later can never land on an already-armed button.
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';

// Minimal stub: only what _manual-events.js's module-level code and
// _wireDeleteButton's own call graph touch. `getElementById` always
// returns null — every consumer of it in this file (_closeManualEventModal,
// showToast's own #toastContainer lookup) already no-ops safely on that.
globalThis.window = {
  addEventListener() {},
  loadWeatherSightings() {},
  reloadLibraryPage() {},
};
globalThis.document = {
  getElementById: () => null,
  addEventListener() {},
  removeEventListener() {},
};

const { _wireDeleteButton } = await import('../_manual-events.js');

function fakeButton() {
  const classes = new Set();
  return {
    innerHTML: '',
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      has: (c) => classes.has(c),
    },
    _handlers: {},
    addEventListener(type, fn) {
      this._handlers[type] = fn;
    },
    click() {
      this._handlers.click?.();
    },
  };
}

function withFakeFetch(responses) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = (url, init) => {
    calls.push({ url, init });
    const r = responses.shift() ?? { ok: true };
    return Promise.resolve({
      ok: r.ok !== false,
      status: r.status || 200,
      statusText: r.statusText || '',
      text: async () => r.text || '',
    });
  };
  return { calls, restore: () => (globalThis.fetch = original) };
}

test('a single tap arms the button without firing a request', () => {
  // Fake the arm-timeout too — a real pending 4 s setTimeout would keep
  // the test process alive until it fires, needlessly slowing the suite
  // down for a timer this test never intends to let elapse.
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const { calls, restore } = withFakeFetch([]);
    try {
      const btn = fakeButton();
      _wireDeleteButton(btn, 'ev1');
      btn.click();
      assert.equal(calls.length, 0);
      assert.equal(btn.classList.has('is-armed'), true);
      assert.match(btn.innerHTML, /Sicher\?/);
    } finally {
      restore();
    }
  } finally {
    mock.timers.reset();
  }
});

test('the arm auto-reverts after the timeout without a second tap', () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const btn = fakeButton();
    _wireDeleteButton(btn, 'ev1');
    btn.click();
    assert.equal(btn.classList.has('is-armed'), true);
    mock.timers.tick(4000);
    assert.equal(btn.classList.has('is-armed'), false);
    assert.doesNotMatch(btn.innerHTML, /Sicher\?/);
  } finally {
    mock.timers.reset();
  }
});

test('a second tap while armed fires the real DELETE request', () => {
  const { calls, restore } = withFakeFetch([{ ok: true }]);
  try {
    const btn = fakeButton();
    _wireDeleteButton(btn, 'ev1');
    btn.click(); // arm
    btn.click(); // confirm
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/api\/weather\/manual-events\/ev1$/);
    assert.equal(calls[0].init.method, 'DELETE');
  } finally {
    restore();
  }
});

test('a failed delete disarms the button rather than leaving it armed', async () => {
  const { calls, restore } = withFakeFetch([{ ok: false, status: 500, text: 'boom' }]);
  try {
    const btn = fakeButton();
    _wireDeleteButton(btn, 'ev1');
    btn.click(); // arm
    btn.click(); // confirm → the stubbed fetch rejects
    await new Promise((r) => setTimeout(r, 0)); // let the rejection's .catch run
    assert.equal(calls.length, 1);
    assert.equal(btn.classList.has('is-armed'), false);
  } finally {
    restore();
  }
});
