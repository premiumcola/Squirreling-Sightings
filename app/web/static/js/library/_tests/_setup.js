// ─── library/_tests/_setup.js ───────────────────────────────────────────
// Stub just enough of the browser to import the real card builders under
// plain Node (`node --test`, no bundler, no jsdom — this repo has no JS
// test runner today, see the package's own report for why `node:test`
// was chosen over adding one). `mediathek/_processing.js` assigns onto
// `window` as a MODULE-LOAD side effect (`window._toggleProcTile = ...`),
// so `window` has to exist before anything that transitively imports it
// is imported — hence this file has to be a plain STATIC `import`, listed
// first, in every test file that reaches `mediathek/_cards.js` or
// `weather/_feed.js`. ES module evaluation runs a file's own imports,
// depth-first, in declaration order, before its own top-level code — so
// `import './_setup.js'` ahead of the real module imports is enough; a
// `require`-style dynamic re-order is not needed.
//
// None of the card builders under test ever CALL `byId`/`qs`/`qsa` (they
// are pure string builders — see mediathek/_cards.js's own header
// comment: "no DOM reads, no state writes, no fetches"), so the stub
// only has to exist, not behave like a real DOM.
globalThis.window = globalThis.window || {};
globalThis.document = globalThis.document || {
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
};
