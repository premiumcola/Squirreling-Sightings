// ─── vplayer/_tests/relabel-repaint.test.js ────────────────────────────────
// A label correction has to reach the RAIL, not just the panel.
//
// „Wenn ich das Hund runter nehme dann ist die Spur immernoch so
// beschriftet und auch das Hundeicon ist noch da!"
//
// Everything up to the last step was already right: the backend
// neutralizes any detection row that carried the retracted class
// (event_relabel.py::_neutralize_disproven_detections), the reply
// carries the rewritten lists back, and core/label-patch.js lands them
// on the very item object the player holds. The lanes are built from
// exactly those rows (timeline/_basis.js) — but the basis was resolved
// ONCE, when the clip loaded, and nothing ever resolved it again. So the
// rail kept the disproven class until the clip was reopened.
//
// Two source-text contracts, because the wiring they live in mounts a
// shell and a <video> at import — the same reason roll-source.test.js
// next door reads the file rather than running it. What is pinned is
// that the repaint EXISTS and that it re-resolves the basis instead of
// just re-drawing the lanes it already had: a correction that empties
// the label set changes which rows there are, not only what they say.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const read = (rel) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

/** Source with comments stripped — this file's subject is quoted inside
 *  those comments, so scanning them would pass on the prose. */
function code(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .map((l) => l.replace(/\/\/.*$/, ''))
    .join('\n');
}

test('the rail exposes a repainter that re-resolves the basis', () => {
  const src = code(read('../_wire-recorded.js'));
  assert.match(src, /relanes\.run\s*=/, 'no repaint hook — a correction cannot reach the rail');
  const hook = src.slice(src.indexOf('relanes.run ='));
  assert.match(
    hook,
    /timelineBasis\(/,
    'the repaint must re-resolve the basis: an emptied label set changes ' +
      'which lanes exist, not just their names',
  );
});

test('the panel save path runs the repainter before it reports outward', () => {
  const src = code(read('../index.js'));
  const start = src.indexOf('const panelDeps');
  assert.ok(start > -1, 'the panel no longer wraps deps — the rail gets no repaint');
  const wrap = src.slice(start, start + 400);
  const runAt = wrap.indexOf('relanes.run()');
  const outwardAt = wrap.indexOf('cfg.deps?.onSaved');
  assert.ok(runAt > -1, 'the wrapper must repaint the rail');
  assert.ok(outwardAt > -1, "the wrapper must still call the caller's own hook");
  assert.ok(
    runAt < outwardAt,
    'the player the operator is looking at must not be the last surface to catch up',
  );
});

test('the repainter is optional — a live/sim player never fills the slot', () => {
  const src = code(read('../_wire-recorded.js'));
  assert.match(src, /if \(relanes\)/, 'an absent slot must not throw on a live clip');
});
