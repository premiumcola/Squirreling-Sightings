// ─── mediaview/_tests/live-detect-outage.test.js ───────────────────────────
// Every way the simulation can fail, and the answer the operator gets.
//
// TWO PROPERTIES, and the second is the one that decays:
//
//   1. each failure lands on its own verdict. A `busy` that classifies as
//      a connection fault sends someone to check the network cable while
//      the server is answering twice a second — that exact wrong message
//      is why the CONTACT/PACE watchdog split exists.
//   2. no two verdicts SAY the same thing. Ten distinct ids are worth
//      nothing if six of them read "Fehler bei der Erkennung"; the
//      pairwise check below is what stops the table collapsing back into
//      one apologetic sentence as it grows.
//
// The bodies are the real ones — routes/_sim_guard.py, _sim_frame.py's
// FramePick.failure() and coral_test_detection.py's own jsonify calls.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classifyOutage, describeHealth } from '../_live-detect-outage.js';

/** The endpoint's failure bodies, verbatim from the Python that writes them. */
const REAL = {
  busy: [
    429,
    {
      ok: false,
      code: 'busy',
      error: 'Simulation läuft noch — die vorherige Analyse ist nicht abgeschlossen.',
    },
  ],
  mode_too_expensive: [
    429,
    {
      ok: false,
      code: 'mode_too_expensive',
      error: '3×3 kostet auf dieser Hardware 10 Inferenzen pro Bild — geschätzt 5.4 s je Tick.',
      mode: '3x3',
      invokes: 10,
      ceiling_ms: 2000,
    },
  ],
  no_frame: [503, { ok: false, code: 'no_frame', error: 'Kamera liefert noch keine Frames' }],
  stale: [
    503,
    {
      ok: false,
      code: 'stale',
      error: 'Stream-Puffer hinkt zurück — kein frischer Frame innerhalb 2.5 s',
    },
  ],
  corrupt: [503, { ok: false, code: 'corrupt', error: 'Stream liefert nur korrupte Frames' }],
  coral_unavailable: [
    503,
    { ok: false, code: 'coral_unavailable', error: 'Coral nicht verfügbar (motion-only?)' },
  ],
  runtime_inactive: [
    503,
    { ok: false, code: 'runtime_inactive', error: 'Kamera-Runtime nicht aktiv (deaktiviert?)' },
  ],
  unknown_revision: [
    400,
    { ok: false, code: 'unknown_revision', error: 'Unbekannter Profil-Stand: evt_1' },
  ],
  inference_failed: [
    500,
    { ok: false, code: 'inference_failed', error: 'Inference fehlgeschlagen: boom' },
  ],
  camera_not_found: [404, { ok: false, code: 'camera_not_found', error: 'camera not found' }],
};

test('every failure body classifies as its own mode', () => {
  for (const [id, [status, data]] of Object.entries(REAL)) {
    assert.equal(classifyOutage({ kind: 'http', status, data }).id, id, `${id} misrouted`);
  }
});

test('the two transport-level failures are their own modes, not HTTP ones', () => {
  assert.equal(classifyOutage({ kind: 'neterr', message: 'Failed to fetch' }).id, 'neterr');
  assert.equal(classifyOutage({ kind: 'contact', gapMs: 7400 }).id, 'contact');
});

test('no two verdicts say the same thing', () => {
  const all = [
    ...Object.entries(REAL).map(([, [status, data]]) =>
      classifyOutage({ kind: 'http', status, data }),
    ),
    classifyOutage({ kind: 'neterr', message: 'Failed to fetch' }),
    classifyOutage({ kind: 'contact', gapMs: 7400 }),
    classifyOutage({ kind: 'pace', modeLabel: '3×3', invokes: 10 }),
    describeHealth({ cadenceMs: 900, invokes: 5 }),
    describeHealth({
      cadenceMs: 900,
      invokes: 5,
      device: 'cpu',
      reason: 'cpu_fallback (coral: x)',
    }),
  ];
  const titles = all.map((v) => v.title);
  const details = all.map((v) => v.detail);
  assert.equal(new Set(titles).size, titles.length, 'two verdicts share a title');
  assert.equal(new Set(details).size, details.length, 'two verdicts share a detail');
  for (const v of all) {
    assert.ok(v.title.length > 4 && v.detail.length > 12, `${v.id} is not an answer`);
  }
});

test('the TPU verdict says who is holding it and that the sim needs it alone', () => {
  const [status, data] = REAL.coral_unavailable;
  const v = classifyOutage({ kind: 'http', status, data });
  assert.match(v.detail, /genau einen Besitzer/);
  assert.match(v.detail, /exklusiv/);
  assert.match(v.hint, /Live-Instanz/);
  assert.equal(v.action.id, 'retry');
});

test('busy is not a fault: no connection language, no action to take', () => {
  const [status, data] = REAL.busy;
  const v = classifyOutage({ kind: 'http', status, data });
  assert.equal(v.tone, 'wait');
  assert.equal(v.action, null, 'busy resolves itself — offering a button invites a second request');
  assert.doesNotMatch(`${v.title} ${v.detail} ${v.hint}`, /Verbindung|Keine Antwort|unterbrochen/);
});

test('the mode refusal quotes the backend arithmetic and offers the way out', () => {
  const [status, data] = REAL.mode_too_expensive;
  const v = classifyOutage({ kind: 'http', status, data });
  assert.equal(v.detail, data.error, 'the estimate is the number worth screenshotting');
  assert.equal(v.action.id, 'mode-off');
  // The quoted body already names both remedies; a hint repeating them is
  // the duplication that pushed the button off a 375 px screen.
  assert.equal(v.hint, '');
});

test('a rejected fetch names the leg that failed — browser to server, not to the camera', () => {
  const v = classifyOutage({ kind: 'neterr', message: 'Failed to fetch' });
  assert.match(v.detail, /Browser/);
  assert.match(v.detail, /Failed to fetch/, 'the browserphrasing is the only clue there is');
  assert.doesNotMatch(v.detail, /Kamera liefert|Stream/);
});

test('the contact verdict counts the silence, so a live outage cannot look frozen', () => {
  assert.match(classifyOutage({ kind: 'contact', gapMs: 7400 }).detail, /Seit 7,4 s/);
  assert.match(classifyOutage({ kind: 'contact', gapMs: 31_000 }).detail, /Seit 31,0 s/);
});

test('an older container sending a bare 503 still reaches the right verdict', () => {
  // Neither body carried a `code` before this change, and a browser can
  // outlive one container restart. The message heuristic is the fallback.
  const coral = classifyOutage({
    kind: 'http',
    status: 503,
    data: { error: 'Coral nicht verfügbar (motion-only?)' },
  });
  assert.equal(coral.id, 'coral_unavailable');
  const runtime = classifyOutage({
    kind: 'http',
    status: 503,
    data: { error: 'Kamera-Runtime nicht aktiv (deaktiviert?)' },
  });
  assert.equal(runtime.id, 'runtime_inactive');
});

test('an unparseable body still produces a verdict rather than nothing', () => {
  // The traversal guard aborts with Flask's default HTML page, so
  // `r.json()` throws and the poll loop passes data=null.
  const v = classifyOutage({ kind: 'http', status: 404, data: null });
  assert.equal(v.id, 'camera_not_found');
  const weird = classifyOutage({ kind: 'http', status: 502, data: null });
  assert.equal(weird.id, 'server');
  assert.ok(weird.detail.length > 12);
});

test('an unknown input paints nothing rather than a shrug', () => {
  assert.equal(classifyOutage(null), null);
  assert.equal(classifyOutage({ kind: 'nonsense' }), null);
});

test('a 200 that ran on the CPU because the TPU was taken is still a finding', () => {
  // The failure mode with no failure response: the detector walks down to
  // its CPU tier and the endpoint answers a perfectly ordinary 200. On
  // screen that used to be a chip reading "CPU" and nothing else.
  const v = describeHealth({
    cadenceMs: 4200,
    invokes: 5,
    device: 'cpu',
    reason: 'cpu_fallback (coral: Failed to load delegate)',
  });
  assert.equal(v.id, 'cpu_fallback');
  assert.equal(v.tone, 'warn');
  assert.match(v.detail, /genau einen Besitzer/);
});

test('a CPU tick the operator ASKED for is not a finding', () => {
  const v = describeHealth({ cadenceMs: 4200, invokes: 1, device: 'cpu', reason: 'cpu_requested' });
  assert.equal(v.id, 'running');
  assert.equal(v.tone, 'ok');
});

test('the cadence is printed in the unit that carries the reading', () => {
  // "~0,0 s" for a 40 ms cycle says instant and unmeasured at once.
  assert.match(describeHealth({ cadenceMs: 40 }).detail, /Takt ~40 ms/);
  assert.match(describeHealth({ cadenceMs: 4200 }).detail, /Takt ~4,2 s/);
  assert.match(describeHealth({ cadenceMs: 900, invokes: 5 }).detail, /5 Inferenzen je Bild/);
});

test('before the first tick the healthy line says so instead of inventing a zero', () => {
  assert.match(describeHealth({ cadenceMs: Number.NaN, invokes: 1 }).detail, /erste Tick/);
});
