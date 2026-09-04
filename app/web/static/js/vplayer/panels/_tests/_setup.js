// ─── vplayer/panels/_tests/_setup.js ───────────────────────────────────────
// Stub the one browser global the readiness face reaches, so its markup
// is provable under a bare `node --test`.
//
// _readiness-face.js imports the stage vocabulary from
// mediathek/_processing.js — the same words and the same seconds-in-
// stage the library tile prints, joined once rather than written twice.
// That module assigns onto `window` as a MODULE-LOAD side effect
// (`window._toggleProcTile = ...`), so `window` has to exist before
// anything that transitively imports it is imported. Hence a plain
// STATIC import, listed first, exactly as library/_tests/_setup.js does
// for the card builders: ES module evaluation runs a file's own imports
// depth-first, in declaration order, before its own top-level code, so
// a `globalThis.window = ...` statement in the test file itself would
// run far too late.
//
// Nothing under test ever READS the stub — procStateOf and fmtElapsed
// are pure — so it only has to exist.
globalThis.window = globalThis.window || {};
