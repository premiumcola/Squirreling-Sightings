// WHICH number the rail draws its roll bands from.
//
// „Wieso kein Vor und Nachlauf!???" — asked about a 2 s clip whose
// details fold said Vorlauf 3 s and Nachlauf 3 s.
//
// Both numbers exist on the event and they mean different things:
//
//   provenance.timing.pre_roll_s          what it was CONFIGURED as
//   recording_settings.pre_motion_seconds what the splice ACHIEVED
//
// `_finalize.py::_update_reencoded_event` writes `round(achieved_pre_s, 2)`
// into the second one after the pre-roll ring has been spliced onto the
// clip. Every clip in this archive reports 0.0 there — the ring
// contributes nothing — so reading the configured number first painted a
// 3 s band onto clips containing no pre-roll at all, and then my own
// „passt nicht in diesen Clip" caption fired on top of it.
//
// A source-text check, because the precedence lives in the composition
// file: index.js wires a live <video>, a fetch and a shell at import, so
// what is pinned here is the CONTRACT — the measurement is read first.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC = readFileSync(fileURLToPath(new URL('../index.js', import.meta.url)), 'utf8');

/** Source with comments stripped — this file's own subject matter is
 *  quoted inside index.js's comments, so scanning them would pass on the
 *  documentation rather than on the code. */
function code(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .map((l) => l.replace(/\/\/.*$/, ''))
    .join('\n');
}

test('der Vorlauf kommt aus der Messung, nicht aus der Einstellung', () => {
  const src = code(SRC);
  assert.match(src, /const preRoll = rs\.pre_motion_seconds \?\? timing\.pre_roll_s/);
  assert.equal(
    /timing\.pre_roll_s \?\? rs\.pre_motion_seconds/.test(src),
    false,
    'die Reihenfolge ist wieder umgedreht — die Absicht schlaegt die Messung',
  );
});

test('für den Nachlauf gilt dieselbe Reihenfolge', () => {
  const src = code(SRC);
  assert.match(src, /postRoll: rs\.post_motion_seconds \?\? timing\.post_roll_s/);
  assert.equal(/timing\.post_roll_s \?\? rs\.post_motion_seconds/.test(src), false);
});

test('?? und nicht ||, damit eine gemessene 0 eine 0 bleibt', () => {
  // Der Kern: jede Aufnahme hier meldet 0.0 erreichten Vorlauf. Mit `||`
  // waere genau dieser Wert wieder durch die konfigurierten 3 s ersetzt
  // worden — derselbe Fehler, den `resolve_pre_motion_seconds` auf der
  // Python-Seite ohnehin schon macht.
  const src = code(SRC);
  const line = src.split('\n').find((l) => l.includes('const preRoll ='));
  assert.ok(line, 'die Zeile muss auffindbar bleiben');
  assert.equal(line.includes('||'), false, 'mit || verschwindet die gemessene 0');
});
