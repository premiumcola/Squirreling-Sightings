// ─── mediaview/live-detect-stall.js ────────────────────────────────────────
// Adaptive stall watchdog + the hold-time refresh loop. _startHoldRefresh drives
// the per-frame bbox hold-fade and piggybacks the stall check.
//
// TWO watchdogs, because "the camera is gone" and "this mode is expensive"
// are different facts and used to share one message:
//
//   * CONTACT  — nothing answered at all. Keyed on `lastContactAt`, which
//     any HTTP response updates (200, 429, 503 alike). Threshold is
//     mode-INDEPENDENT: a reachable server answers promptly whatever it
//     answers. This one, and only this one, shows the reconnect banner and
//     re-kicks the loop.
//   * PACE     — answers arrive but frames are slow. Keyed on `lastRespAt`
//     and scaled by the mode's inference count, so 3×3 gets ten times the
//     budget of "Aus". It shows an informational notice and never aborts.
//
// The old single watchdog compared the frame gap against a threshold
// seeded from the cadence measured BEFORE the mode switch. Picking 3×3
// therefore aborted the first tick at 5 s — a tick that was going to
// succeed at 8 — and re-issued it into a handler Flask cannot cancel, so
// each retry added another ten-inference job. The EMA never learned the
// new cost because no tick ever completed: a bootstrap deadlock that
// looked, on screen, exactly like a dead camera.
import { byId, esc } from '../core/dom.js';
import { S } from './live-detect-state.js';
import { zoneEl } from './live-detect-skeleton.js';
import { _tick } from './live-detect-poll.js';
import { _renderBboxOverlay } from './live-detect-bbox.js';
import { _debugDiagOn, _renderDiagStrip } from './live-detect-diag.js';
import { mvModeInvokes, mvModeLabel } from './mode-indicator.js';
import {
  _STALL_FLOOR_MS,
  _STALL_FACTOR,
  _PACE_FLOOR_MS,
  _STALL_BACKOFF_START,
  _STALL_BACKOFF_MAX,
  _HOLD_REFRESH_MS,
  _INFLIGHT_ABORT_CEILING_MS,
} from './live-detect.js';

export function _startHoldRefresh() {
  if (!S.session) return;
  if (S.session.holdHandle) clearInterval(S.session.holdHandle);
  S.session.holdHandle = setInterval(() => {
    if (!S.session) return;
    _renderBboxOverlay();
    // B7 · piggyback the tick-row refresh on the existing 250 ms
    // hold loop so the on-screen deltas stay current even when the
    // tick loop is wedged (no _renderFrame call would otherwise
    // drive _renderDiagStrip). Cheap — _renderDiagStrip is a no-op
    // when the Debug pill is OFF.
    if (_debugDiagOn()) _renderDiagStrip();
    // Q2-5 · piggyback the stall watchdog on the same fixed-rate loop.
    _checkStall();
  }, _HOLD_REFRESH_MS);
}

// Budget for "a frame should have landed by now", in ms.
//
// P5 · this used to be `_STALL_FLOOR_MS * invokes`, which handed 3×3 a
// 50 000 ms budget — the notice written to explain the expensive modes
// could not fire in any of them, and the operator watched a frozen
// picture with no text for the whole of a slow tick. The mode's cost
// belongs in the MESSAGE, not in the threshold: what makes a wait worth
// explaining is its length in seconds, which does not change because the
// reason for it does. The adaptive half (`_STALL_FACTOR × the camera's
// own cadence`) still keeps a legitimately slow camera quiet once its
// EMA has caught up — the floor only governs the first ticks after a
// mode switch, which is exactly when the operator is asking why.
function _paceBudgetMs() {
  const expected = Math.max(S.cycleEmaMs || 0, S.tickState.lastDelayMs || 0);
  return Math.max(_PACE_FLOOR_MS, Math.round(_STALL_FACTOR * expected));
}

// Contact is (re-)established: drop the stall state and take down the
// disconnect banner — and ONLY that banner. A busy / refused / pace
// notice put up by the poll loop describes the current truth and must
// survive; blanket-hiding here is what made the two paths fight.
function _clearContactStall() {
  if (S.stallState.active) {
    console.warn(`[sim-stall] recovered after ${Date.now() - S.stallState.sinceMs} ms`);
    S.stallState.active = false;
    S.stallState.backoffMs = _STALL_BACKOFF_START;
  }
  const el = byId('mvLiveStallBanner');
  if (el && el.dataset.tone === 'warn') el.remove();
}

export function _checkStall() {
  if (!S.session) return;
  const now = Date.now();
  const t = S.tickState;
  const started = t.startedAt || now;
  // CONTACT — the honest disconnect signal. `lastContactAt` is stamped on
  // ANY response, so a server that is steadily returning 503 or 429 never
  // trips this. It used to key off lastRespAt (successes only), which made
  // an answering-but-refusing backend indistinguishable from a dead one.
  // A 429 refusal already explains itself on screen (mode too expensive,
  // or a previous analysis still running). Painting a watchdog banner over
  // that message would replace the real reason with a guess.
  //
  // P6 · but it must clear the stall state on the way out. This branch
  // used to `return` ABOVE the recovery block, and the only way to reach
  // it was through the disconnect path: a >30 s tick painted "Keine
  // Antwort vom Server", _retryTickNow aborted and re-issued, the aborted
  // handler still held the backend's single slot, and the replacement
  // request came back 429 busy — which then returned early, forever, with
  // the disconnect banner frozen on top of a server that was answering
  // every 500 ms. Wrong message, and unclearable.
  if (t.lastStatus === 429) {
    _clearContactStall();
    return;
  }
  const contactRef = t.lastContactAt || started;
  const contactGap = now - contactRef;
  // An OPEN request IS contact. The socket is up and the server is working;
  // only a request older than the abort ceiling counts as hung. Without
  // this, a legitimately slow 3×3 tick tripped the disconnect banner at
  // 5 s — the exact wrong message, on a perfectly healthy camera.
  const inflightMs = S.session.inflightSince ? now - S.session.inflightSince : 0;
  const pending = inflightMs > 0 && inflightMs < _INFLIGHT_ABORT_CEILING_MS;
  const contactStalled =
    !pending &&
    contactGap > Math.max(_STALL_FLOOR_MS, Math.round(_STALL_FACTOR * (S.cycleEmaMs || 0)));
  if (contactStalled) {
    _handleContactStall(now, contactGap, contactRef);
    return;
  }
  _clearContactStall();
  // PACE — contact is fine, frames are just slow. Informational only.
  const frameGap = now - (t.lastRespAt || started);
  if (frameGap > _paceBudgetMs()) _showPaceNotice();
  else if (!t.lastTickError) _hideStallBanner();
}

// Contact watchdog body — kept out of _checkStall so neither function
// crosses the 60-line ceiling.
function _handleContactStall(now, gap, ref) {
  const t = S.tickState;
  if (!S.stallState.active) {
    S.stallState.active = true;
    S.stallState.sinceMs = ref;
    S.stallState.backoffMs = _STALL_BACKOFF_START;
    // console.warn is the lint-allowed diagnostic escape hatch.
    console.warn(
      `[sim-stall] no response for ${gap} ms · ` +
        `lastContact=${t.lastContactAt ? new Date(t.lastContactAt).toISOString() : 'none'}`,
    );
    _showStallBanner();
    _retryTickNow();
    S.stallState.nextRetryAt = now + S.stallState.backoffMs;
    return;
  }
  if (now >= S.stallState.nextRetryAt) {
    S.stallState.backoffMs = Math.min(_STALL_BACKOFF_MAX, S.stallState.backoffMs * 2);
    _retryTickNow();
    S.stallState.nextRetryAt = now + S.stallState.backoffMs;
  }
}

// Abort a hung in-flight fetch and fire a fresh tick now.
//
// The abort is CONDITIONAL. Aborting a request that is still running is
// free for us and expensive for the server: Flask has no request
// cancellation, so the handler runs every one of its inferences to
// completion and only notices the closed socket at the final write. A
// request younger than the ceiling is left alone and we simply wait.
export function _retryTickNow() {
  if (!S.session) return;
  const inflightMs = S.session.inflightSince ? Date.now() - S.session.inflightSince : Infinity;
  if (inflightMs < _INFLIGHT_ABORT_CEILING_MS) return;
  try {
    S.session.abort?.abort();
  } catch {
    /* ignore */
  }
  // The aborted request is given up on HERE, synchronously — its own
  // rejection handler lands a microtask later and would otherwise clear
  // the stamp of the replacement request issued below.
  S.session.inflightSince = 0;
  if (S.session.tickHandle) {
    clearTimeout(S.session.tickHandle);
    S.session.tickHandle = null;
  }
  _tick();
}

// One banner element, two tones. `data-tone="warn"` is the genuine
// no-contact case; `data-tone="info"` is "slow, still running" and must
// never read as a connection fault — that wrong message is the whole
// reason this file was rewritten.
function _banner(tone, html) {
  const host = zoneEl('video') || byId('lightboxMediaWrap');
  if (!host) return null;
  let el = byId('mvLiveStallBanner');
  if (!el) {
    el = document.createElement('div');
    el.id = 'mvLiveStallBanner';
    el.className = 'mv-ld-stall-banner';
    host.appendChild(el);
  }
  if (el.dataset.tone !== tone || el.dataset.body !== html) {
    el.dataset.tone = tone;
    el.dataset.body = html;
    el.innerHTML = html;
    el.querySelector('[data-action="stall-retry"]')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      console.warn('[sim-stall] manual retry');
      S.stallState.backoffMs = _STALL_BACKOFF_START;
      S.session && (S.session.inflightSince = 0);
      _retryTickNow();
    });
  }
  el.style.display = 'flex';
  return el;
}

export function _showStallBanner() {
  _banner(
    'warn',
    '<div class="mv-ld-stall-inner">' +
      '<div class="mv-ld-stall-spinner" aria-hidden="true"></div>' +
      '<div class="mv-ld-stall-text">Keine Antwort vom Server — ' +
      'versuche erneut zu verbinden …</div>' +
      '<button type="button" class="mv-ld-stall-retry" data-action="stall-retry">' +
      'Erneut versuchen</button>' +
      '</div>',
  );
}

// Slow-but-alive. Names the cost so the number explains the wait.
function _showPaceNotice() {
  const mode = S.session?.detMode || 'off';
  const n = mvModeInvokes(mode);
  _banner(
    'info',
    '<div class="mv-ld-stall-inner">' +
      '<div class="mv-ld-stall-spinner" aria-hidden="true"></div>' +
      `<div class="mv-ld-stall-text">Analyse läuft noch — ${esc(mvModeLabel(mode))} ` +
      `kostet ${n} Inferenzen je Bild.</div>` +
      '</div>',
  );
}

// The backend still owns its single slot from the previous request
// (429 · busy). Flask cannot cancel that handler, so the honest thing to
// say is that it is finishing — not that the camera is unreachable.
export function _showBusyNotice() {
  _banner(
    'info',
    '<div class="mv-ld-stall-inner">' +
      '<div class="mv-ld-stall-spinner" aria-hidden="true"></div>' +
      '<div class="mv-ld-stall-text">Vorherige Analyse läuft noch — ' +
      'der Server rechnet den letzten Tick zu Ende.</div>' +
      '</div>',
  );
}

// The backend refused the mode outright (429 · mode_too_expensive). Not a
// stall and not a camera fault: show the arithmetic and offer the way out.
export function _showModeRefusedBanner(text, onFallback) {
  const el = _banner(
    'refused',
    '<div class="mv-ld-stall-inner">' +
      `<div class="mv-ld-stall-text">${esc(text)}</div>` +
      '<button type="button" class="mv-ld-stall-retry" data-action="mode-fallback">' +
      'Auf „Aus“ zurückschalten</button>' +
      '</div>',
  );
  el?.querySelector('[data-action="mode-fallback"]')?.addEventListener('click', (ev) => {
    ev.stopPropagation();
    onFallback?.();
  });
}

export function _hideStallBanner() {
  const banner = byId('mvLiveStallBanner');
  if (banner) banner.remove();
}
