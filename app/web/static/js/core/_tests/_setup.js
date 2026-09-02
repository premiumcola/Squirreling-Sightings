// ─── core/_tests/_setup.js ──────────────────────────────────────────────
// Stub just enough of the browser to import `core/action-registry.js`
// under plain Node. That module auto-wires on import (`_wire()` at the
// bottom of its body calls `document.addEventListener` four times), so
// `document` has to exist BEFORE it is imported — hence this file has to
// be a plain STATIC `import`, listed first, exactly the way
// `library/_tests/_setup.js` is (see that file's own header for why ES
// module evaluation order makes that sufficient).
//
// Unlike the library stub, this one has to REMEMBER the listeners: the
// registry's dispatcher is module-private, and capturing what it wired
// onto `document` is the only way to drive it from a test the way a real
// click does.
export const documentListeners = new Map();

globalThis.window = globalThis.window || {};
globalThis.document = globalThis.document || {
  addEventListener(type, fn) {
    if (!documentListeners.has(type)) documentListeners.set(type, []);
    documentListeners.get(type).push(fn);
  },
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
};

/** Drive the registry's real delegated listener with a synthetic event
 * whose target resolves to `el` — the same shape `_handle` reads:
 * `ev.target.closest('[data-action]')`. */
export function dispatch(type, el) {
  const ev = {
    target: { closest: (sel) => (sel === '[data-action]' ? el : null) },
    defaultPrevented: false,
    preventDefault() {
      ev.defaultPrevented = true;
    },
  };
  for (const fn of documentListeners.get(type) || []) fn(ev);
  return ev;
}

/** An element as `_handle` sees it: only `dataset` is ever read. */
export function actionEl(action, extra = {}) {
  return { dataset: { action, ...extra } };
}
