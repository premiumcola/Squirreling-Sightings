// ─── vplayer/panels/_replay.js ─────────────────────────────────────────────
// "Nachsimulieren": run THIS recording back through detection and show
// what a different settings set would have made of it.
//
// The point of storing a provenance snapshot with every clip is being
// able to ask that question later. Until the replay endpoint existed
// this fold could only offer "Neu erkennen" (re-index with whatever the
// settings are NOW, overwriting the sidecar) and "Kamera simulieren"
// (the LIVE camera, not this clip) — neither of which answers it.
//
// Both buttons here run the same clip; they differ only in which
// settings set the backend replays it with. Nothing is overwritten:
// the result comes back for reading and is archived under the event as
// its own history, so the clip's own detections stay what the camera
// actually reported.
//
// The answer is rendered INLINE in the fold. A second window would put
// the comparison somewhere the thing being compared is not.

import { esc } from '../../core/dom.js';
import { kvRowsHtml, replaySummaryRows, replayVerdict } from './_helpers.js';

const LABELS = {
  stored: 'Mit diesen Settings nachsimulieren',
  current: 'Mit aktuellem Profil nachsimulieren',
};

/**
 * The preflight: what a replay WOULD run with.
 *
 * Cheap and side-effect-free, so the fold can label the buttons and
 * refuse a pointless run before spending a minute of CPU proving that
 * two identical settings sets produce identical results.
 *
 * @returns {{url: string, method: string}|null}
 */
export function preflightRequestFor(item) {
  if (!item?.event_id) return null;
  return {
    url:
      `/api/event/${encodeURIComponent(item.event_id)}/replay` +
      `?camera_id=${encodeURIComponent(item.camera_id || '')}`,
    method: 'GET',
  };
}

/**
 * The run itself.
 *
 * @param {object} item
 * @param {'stored'|'current'} mode
 * @returns {{url: string, method: string, body: object}|null}
 */
export function replayRequestFor(item, mode) {
  const pre = preflightRequestFor(item);
  if (!pre || (mode !== 'stored' && mode !== 'current')) return null;
  return { url: pre.url, method: 'POST', body: { settings: mode } };
}

/**
 * The simulation glyph: a frame with an arrow running back around it.
 *
 * „simulations icon in der grün farbe des players!" — so it is drawn in
 * `currentColor` and the stylesheet gives it `--vp-accent`, the same
 * green the playhead and the rail fill already wear. One accent, used
 * for the things this player DOES, so a control that re-runs the clip
 * reads as part of the same object as the control that plays it.
 *
 * While a run is in flight the glyph turns — the arrow is the moving
 * part, which is what makes the rotation mean "this is going round
 * again" rather than a generic spinner parked next to a label.
 */
const _SIM_ICON =
  `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ` +
  `stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
  `<path d="M20 12a8 8 0 1 1-2.34-5.66"/><polyline points="20,3.5 20,7.5 16,7.5"/>` +
  `<polygon points="10.2,9.2 15,12 10.2,14.8" fill="currentColor" stroke="none"/></svg>`;

/** One button, disabled with a reason or ready to fire. */
function _btnHtml(mode, { disabled, hint, busy }) {
  const label = hint ? `${LABELS[mode]} — ${hint}` : LABELS[mode];
  return (
    `<button type="button" class="vp-pnl-btn vp-pnl-btn--sim${busy ? ' is-running' : ''}" ` +
    `data-replay="${mode}"${disabled ? ' disabled' : ''}>` +
    `<span class="vp-pnl-btn-icon">${_SIM_ICON}</span>` +
    `<span class="vp-pnl-btn-label">${esc(label)}</span></button>`
  );
}

function _barHtml(state) {
  const busy = state.busy !== null;
  const identical = state.preflight?.identical === true;
  return (
    `<div class="vp-pnl-replay-bar">` +
    _btnHtml('stored', { disabled: busy, busy: state.busy === 'stored' }) +
    _btnHtml('current', {
      disabled: busy || identical,
      hint: identical ? 'identisch mit den gespeicherten' : '',
      busy: state.busy === 'current',
    }) +
    `</div>`
  );
}

/**
 * The output area: progress while a run is in flight, then the result.
 *
 * aria-live so the answer is announced when it lands — the run takes
 * long enough that nobody is watching this region when it changes.
 */
function _outHtml(state) {
  if (state.busy) {
    const which = LABELS[state.busy] || '';
    // A SWEEP, not a percentage. The backend walks the clip and reports
    // once at the end, so any number here would be invented — but the
    // run takes long enough that a static line reads as a hung panel.
    // An indeterminate bar says "working" and claims nothing else.
    return (
      `<div class="vp-pnl-replay-out" aria-live="polite">` +
      `<div class="vp-pnl-replay-busy">Läuft — ${esc(which)}…</div>` +
      `<div class="vp-pnl-replay-sweep" aria-hidden="true"><i></i></div></div>`
    );
  }
  if (state.error) {
    return (
      `<div class="vp-pnl-replay-out" aria-live="polite">` +
      `<div class="vp-pnl-replay-verdict is-warn">${esc(state.error)}</div></div>`
    );
  }
  if (!state.result) return `<div class="vp-pnl-replay-out" aria-live="polite"></div>`;
  const verdict = replayVerdict(state.result);
  return (
    `<div class="vp-pnl-replay-out" aria-live="polite">` +
    `<div class="vp-pnl-replay-verdict is-${verdict.tone}">${esc(verdict.text)}</div>` +
    kvRowsHtml(replaySummaryRows(state.result)) +
    `</div>`
  );
}

/** Fire one replay and fold its outcome back into `state`. */
async function _run(state, deps, paint, mode) {
  const req = replayRequestFor(state.item, mode);
  if (!req || state.busy) return;
  state.busy = mode;
  state.error = null;
  state.result = null;
  paint();
  try {
    const res = await deps.request(req.url, {
      method: req.method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.body),
    });
    if (!state.alive) return;
    state.result = res;
  } catch (e) {
    if (!state.alive) return;
    state.error = 'Nachsimulation fehlgeschlagen: ' + (e?.message || e);
    deps.onError?.(state.error);
  } finally {
    if (state.alive) {
      state.busy = null;
      paint();
    }
  }
}

/** Ask what the two settings sets are, to label the buttons. */
async function _preflight(state, deps, paint, item) {
  const req = preflightRequestFor(item);
  state.preflight = null;
  if (!req) return;
  try {
    const res = await deps.request(req.url, { method: req.method });
    // The clip may have been navigated away from while this was in
    // flight; a stale answer must not relabel the new clip's buttons.
    if (state.alive && state.item?.event_id === item.event_id) {
      state.preflight = res;
      paint();
    }
  } catch {
    // A failed preflight only costs the "identical" hint. Leaving the
    // buttons enabled is the safe direction: the worst case is one run
    // that turns out to change nothing.
  }
}

/**
 * Mount the replay actions and their inline result.
 *
 * @param {HTMLElement} host  a container this owns outright
 * @param {object} deps
 * @param {(url, opts) => Promise} deps.request  the shared api helper,
 *   which throws on any non-2xx
 * @param {(msg) => void} [deps.onError]
 * @returns {{update: (item) => void, teardown: () => void}|null}
 */
export function renderReplay(host, deps = {}) {
  if (!host) return null;
  // `busy` holds the MODE in flight, so the buttons and the progress
  // line read one source rather than two booleans that can drift.
  // `alive` lives here too so a request that outlives the teardown
  // resolves into a bag nobody paints from.
  const state = {
    item: null,
    preflight: null,
    result: null,
    error: null,
    busy: null,
    alive: true,
  };

  const paint = () => {
    host.innerHTML = _barHtml(state) + _outHtml(state);
    host.querySelectorAll('[data-replay]').forEach((btn) => {
      btn.addEventListener('click', () => _run(state, deps, paint, btn.dataset.replay));
    });
  };

  return {
    update: (item) => {
      const changed = item?.event_id !== state.item?.event_id;
      state.item = item || null;
      if (changed) {
        state.result = null;
        state.error = null;
        state.preflight = null;
      }
      paint();
      if (changed && item?.event_id) _preflight(state, deps, paint, item);
    },
    teardown: () => {
      state.alive = false;
      host.innerHTML = '';
    },
  };
}
