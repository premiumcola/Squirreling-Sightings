// Both debug exits were dead, and for one reason.
//
// „Debug copy button und button debug bundle funktionieren nicht :o"
//
// They were wired only when the caller happened to hand in `deps.ctx`
// and `deps.post`. The recorded entry point passes
// `{request, onSaved, onError}`; the live and simulation entry points in
// dashboard.js pass no `deps` at all — and this fold only ever appears
// on the live/sim panel. So `deps.ctx` was undefined, `_wireCopyBar`
// never ran, and the bundle listener was never attached. Two buttons
// rendered, neither reachable, no error anywhere.
//
// These are source-text checks: the fold binds DOM and imports the
// clipboard module at load, so what matters is the CONTRACT — that
// neither button's wiring is conditional on plumbing a caller has to
// remember.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC = readFileSync(fileURLToPath(new URL('../_debug-log.js', import.meta.url)), 'utf8');
const TRACKS = readFileSync(fileURLToPath(new URL('../_live-tracks.js', import.meta.url)), 'utf8');
const DASH = readFileSync(fileURLToPath(new URL('../../../dashboard.js', import.meta.url)), 'utf8');

/** Source with comments stripped — this file's own comments quote the
 *  broken shapes while explaining them. */
function code(src) {
  const noBlock = src.replace(/\/\*[\s\S]*?\*\//g, '');
  return noBlock
    .split('\n')
    .map((l) => l.replace(/\/\/.*$/, ''))
    .join('\n');
}

// ── neither button may depend on plumbing ────────────────────────────

test('die Kopie wird immer verdrahtet, nicht nur mit deps.ctx', () => {
  const src = code(SRC);
  assert.match(src, /_wireCopyBar\(fold\.body, _copyCtx\(/);
  assert.equal(
    /if \(deps\.ctx\)/.test(src),
    false,
    'die Verdrahtung hängt wieder an etwas, das der Aufrufer mitgeben muss',
  );
});

test('das Bundle wird immer verdrahtet, nicht nur mit deps.post', () => {
  const src = code(SRC);
  assert.equal(
    /typeof deps\.post === 'function'/.test(src),
    false,
    'der Knopf ist wieder daran gebunden, dass ein post-Helfer durchgereicht wurde',
  );
  assert.match(src, /bundleBtn\.addEventListener/);
});

test('ohne post-Helfer holt der Knopf sich den Endpunkt selbst', () => {
  const src = code(SRC);
  const fn = src.slice(src.indexOf('async function _requestBundle'));
  const body = fn.slice(0, fn.indexOf('\n}'));
  assert.match(body, /fetch\('\/api\/debug\/bundle', \{ method: 'POST' \}\)/);
});

// ── the context is the same one the legacy tab builds ────────────────

test('der Kontext kommt aus der geteilten Zustandsablage', () => {
  const src = code(SRC);
  const fn = src.slice(src.indexOf('function _copyCtx'));
  const body = fn.slice(0, fn.indexOf('\n}'));
  // Exactly the fields live-detect-tabs.js assembles for the legacy
  // debug tab — same shape, same source, one implementation.
  for (const field of ['tickState', 'session', 'holdMs', 'cycleEmaMs', 'fullData']) {
    assert.match(body, new RegExp(field), `${field} fehlt im Kontext`);
  }
  assert.match(src, /import \{ S \} from '\.\.\/\.\.\/mediaview\/live-detect-state\.js'/);
});

test('der Kontext trägt den Frame DIESES Ticks', () => {
  // Ohne ihn beschreibt die Kopie einen leeren Zustand statt des Bildes,
  // das der Betreiber gerade ansieht.
  const src = code(SRC);
  assert.match(src, /fullData: frame\?\.raw \|\| frame \|\| null/);
  assert.match(code(TRACKS), /log\?\.update\(f\?\.trace \|\| \[\], f\)/);
});

test('der Frame erreicht die Neuzeichnung, nicht nur den Mount', () => {
  const src = code(SRC);
  assert.match(src, /update: \(lines, frame\) => paint\(lines, frame\)/);
});

// ── the reason it was dead, pinned at the entry points ───────────────

test('die Simulation reicht weiterhin keine deps — und braucht es nicht mehr', () => {
  // Dieser Test hält den GRUND fest, nicht den Fehler: solange
  // dashboard.js keine deps mitgibt, darf keine Bedienung davon
  // abhängen. Wird das eines Tages nachgerüstet, darf dieser Test
  // ruhig fallen — die Knöpfe funktionieren dann trotzdem.
  const src = code(DASH);
  const sim = src.slice(src.indexOf("mode: 'sim'"));
  const call = sim.slice(0, sim.indexOf('});'));
  assert.equal(/deps:/.test(call), false, 'dann darf der Kommentar oben nicht mehr so stehen');
});
