// ─── mediaview/_tests/live-detect-verdict.test.js ──────────────────────────
// WHERE the message goes. The bug was never the wording.
//
// `live-detect-stall.js::_banner` hosted every failure message in
// `zoneEl('video') || #lightboxMediaWrap` — the legacy 5-zone modal. The
// unified player builds its own DOM under `.vp-root` and never touches
// those ids (vplayer/index.js says so in its own header), so during a real
// outage the band was created, filled with correct German, and appended to
// a node that is not on screen. The panel sat there looking idle.
//
// Every test below is about that choice: the player's panel wins when it
// exists, the legacy host is only for the legacy player, and a headless
// producer with no player mounted writes nowhere at all rather than into
// the recorded player's furniture.
//
// The stub DOM answers exact selector strings and does not parse them —
// see _dom-stub.js. Proof that those selectors match a real browser is the
// screenshot harness: `node scripts/uishot/run.mjs vplayer-sim-tpu-taken`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { installStubDom } from './_dom-stub.js';

const dom = installStubDom();

// After the stub is installed, so core/dom.js's `document` reads resolve.
const { S } = await import('../live-detect-state.js');
const { showOutage, showHealth, clearOutage, teardownVerdict, VERDICT_ID } =
  await import('../live-detect-verdict.js');

const SIM_PANEL = '.vp-root[data-mode="sim"] [data-slot="panel"]';
const LIVE_PANEL = '.vp-root[data-mode="live"] [data-slot="panel"]';

/** A fresh world: no player, no legacy modal, no session. */
function reset() {
  dom.reset();
  dom.selector(SIM_PANEL, null);
  dom.selector(LIVE_PANEL, null);
  S.session = null;
  teardownVerdict();
}

/** Mount a stand-in for the unified player's panel slot. */
function mountPlayerPanel(selector = SIM_PANEL) {
  const panel = dom.el('div');
  dom.selector(selector, panel);
  return panel;
}

/** Mount a stand-in for the legacy modal's media wrap. */
function mountLegacyWrap() {
  const wrap = dom.el('div');
  dom.byId('lightboxMediaWrap', wrap);
  return wrap;
}

const TPU_TAKEN = {
  kind: 'http',
  status: 503,
  data: { ok: false, code: 'coral_unavailable', error: 'Coral nicht verfügbar (motion-only?)' },
};

test('a failing poll puts a visible message in the NEW panel', () => {
  reset();
  const panel = mountPlayerPanel();
  showOutage(TPU_TAKEN);
  const band = panel.querySelector(`#${VERDICT_ID}`);
  assert.ok(band, 'no band was mounted into the player panel');
  assert.match(band.renderedText, /TPU belegt/);
  assert.match(band.renderedText, /genau einen Besitzer/);
  assert.equal(band.dataset.tone, 'bad');
});

test('the band is the FIRST thing in the panel — the verdict reads before the evidence', () => {
  reset();
  const panel = mountPlayerPanel();
  const chips = dom.el('div');
  panel.appendChild(chips);
  showOutage(TPU_TAKEN);
  assert.equal(panel.children[0].id, VERDICT_ID);
  assert.equal(panel.children[1], chips);
});

test('with the player up, NOTHING is written into the legacy modal', () => {
  // The regression, stated as an assertion: the legacy wrap exists in the
  // document (index.html always ships it) and must not be chosen.
  reset();
  const panel = mountPlayerPanel();
  const legacy = mountLegacyWrap();
  showOutage(TPU_TAKEN);
  assert.ok(panel.querySelector(`#${VERDICT_ID}`));
  assert.equal(legacy.querySelector(`#${VERDICT_ID}`), null);
});

test('the live surface gets the band too — it polls the same loop', () => {
  reset();
  const panel = mountPlayerPanel(LIVE_PANEL);
  showOutage(TPU_TAKEN);
  assert.ok(panel.querySelector(`#${VERDICT_ID}`));
});

test('without the player, the legacy host still gets it — ?vplayer=off is a real path', () => {
  reset();
  const legacy = mountLegacyWrap();
  showOutage(TPU_TAKEN);
  assert.match(legacy.querySelector(`#${VERDICT_ID}`).renderedText, /TPU belegt/);
});

test('a HEADLESS session with no player writes nowhere at all', () => {
  // live-detect-session.js's header: a headless producer owns no chrome,
  // and #lightboxMediaWrap belongs to the recorded player, which may well
  // be mounted. Saying nothing beats saying it into someone else's DOM.
  reset();
  const legacy = mountLegacyWrap();
  S.session = { headless: true };
  showOutage(TPU_TAKEN);
  assert.equal(legacy.querySelector(`#${VERDICT_ID}`), null);
  S.session = null;
});

test('each failure mode paints its own text into the panel', () => {
  const cases = [
    [{ kind: 'http', status: 429, data: { code: 'busy', error: 'x' } }, /Analyse läuft noch/],
    [
      { kind: 'http', status: 429, data: { code: 'mode_too_expensive', error: '3×3 kostet 10' } },
      /3×3 kostet 10/,
    ],
    [{ kind: 'http', status: 503, data: { code: 'no_frame' } }, /keine Bilder/],
    [{ kind: 'http', status: 503, data: { code: 'stale' } }, /hinkt zurück/],
    [TPU_TAKEN, /TPU belegt/],
    [{ kind: 'neterr', message: 'Failed to fetch' }, /Keine Verbindung zum Server/],
    [{ kind: 'contact', gapMs: 7400 }, /Keine Antwort vom Server/],
  ];
  const seen = new Set();
  for (const [input, expected] of cases) {
    reset();
    const panel = mountPlayerPanel();
    showOutage(input);
    const text = panel.querySelector(`#${VERDICT_ID}`).renderedText;
    assert.match(text, expected);
    assert.ok(!seen.has(text), 'two failure modes painted identical text');
    seen.add(text);
  }
});

test('a healthy tick replaces the outage instead of stacking a second band', () => {
  reset();
  const panel = mountPlayerPanel();
  showOutage(TPU_TAKEN);
  showHealth({ cadenceMs: 900, invokes: 5 });
  assert.equal(panel.children.length, 1);
  const band = panel.querySelector(`#${VERDICT_ID}`);
  assert.equal(band.dataset.tone, 'ok');
  assert.match(band.renderedText, /Simulation läuft/);
  assert.doesNotMatch(band.renderedText, /TPU belegt/);
});

test('clearing one verdict must not wipe a different one that is standing', () => {
  // The CONTACT watchdog recovers four times a second. Letting it clear
  // whatever happens to be up is how the busy notice and the disconnect
  // banner used to fight over the same element.
  reset();
  const panel = mountPlayerPanel();
  showOutage({ kind: 'http', status: 429, data: { code: 'busy' } });
  clearOutage('contact', { cadenceMs: 900 });
  assert.match(panel.querySelector(`#${VERDICT_ID}`).renderedText, /Analyse läuft noch/);
  clearOutage('busy', { cadenceMs: 900 });
  assert.match(panel.querySelector(`#${VERDICT_ID}`).renderedText, /Simulation läuft/);
});

test('teardown takes the band away, so the next camera starts clean', () => {
  reset();
  const panel = mountPlayerPanel();
  showOutage(TPU_TAKEN);
  teardownVerdict();
  assert.equal(panel.querySelector(`#${VERDICT_ID}`), null);
});

test('the German is escaped, not injected — a backend message is untrusted text', () => {
  reset();
  const panel = mountPlayerPanel();
  showOutage({
    kind: 'http',
    status: 500,
    data: { code: 'inference_failed', error: '<img src=x onerror=alert(1)>' },
  });
  const html = panel.querySelector(`#${VERDICT_ID}`).innerHTML;
  assert.ok(!html.includes('<img'), 'a backend string reached innerHTML unescaped');
  assert.ok(html.includes('&lt;img'));
});
