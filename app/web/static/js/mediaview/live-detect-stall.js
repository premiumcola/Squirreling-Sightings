// ─── mediaview/live-detect-stall.js ────────────────────────────────────────
// Adaptive stall watchdog + the hold-time refresh loop. _startHoldRefresh drives
// the per-frame bbox hold-fade and piggybacks the stall check; on a genuine
// stall it shows the reconnect banner and re-kicks _tick on a 1/2/4/8 s backoff.
// State via S.
import { byId } from '../core/dom.js';
import { S } from './live-detect-state.js';
import { zoneEl } from './live-detect-skeleton.js';
import { _tick } from './live-detect-poll.js';
import { _renderBboxOverlay } from './live-detect-bbox.js';
import { _debugDiagOn, _renderDiagStrip } from './live-detect-diag.js';
import {
  _STALL_FLOOR_MS,
  _STALL_FACTOR,
  _STALL_BACKOFF_START,
  _STALL_BACKOFF_MAX,
  _HOLD_REFRESH_MS,
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

// Q2-5 · adaptive stall watchdog. Runs every _HOLD_REFRESH_MS. Compares
// the time since the last painted frame against the camera's own recent
// cadence; on a genuine stall it surfaces the reconnect banner, logs a
// console diagnostic (visible in mobile-Safari Web Inspector), and
// re-kicks the tick loop on a 1/2/4/8 s backoff. Recovery (a fresh
// frame) clears the banner and resets the backoff.
export function _checkStall() {
  if (!S.session) return;
  const now = Date.now();
  const t = S.tickState;
  // Reference = last successful frame; before the first frame lands,
  // fall back to mount time so a never-connecting open also surfaces.
  const ref = t.lastRespAt || t.startedAt || now;
  const gap = now - ref;
  const expected = Math.max(S.cycleEmaMs || 0, t.lastDelayMs || 0);
  const stallMs = Math.max(_STALL_FLOOR_MS, Math.round(_STALL_FACTOR * expected));
  const stalled = gap > stallMs;
  if (stalled && !S.stallState.active) {
    S.stallState.active = true;
    S.stallState.sinceMs = ref;
    S.stallState.backoffMs = _STALL_BACKOFF_START;
    // console.warn is the lint-allowed diagnostic escape hatch.
    console.warn(
      `[sim-stall] no frame for ${gap} ms (threshold ${stallMs} ms) · ` +
        `lastFrame=${t.lastRespAt ? new Date(t.lastRespAt).toISOString() : 'none'} · ` +
        `now=${new Date(now).toISOString()}`,
    );
    _showStallBanner();
    _retryTickNow();
    S.stallState.nextRetryAt = now + S.stallState.backoffMs;
  } else if (stalled && S.stallState.active) {
    if (now >= S.stallState.nextRetryAt) {
      S.stallState.backoffMs = Math.min(_STALL_BACKOFF_MAX, S.stallState.backoffMs * 2);
      _retryTickNow();
      S.stallState.nextRetryAt = now + S.stallState.backoffMs;
    }
  } else if (!stalled && S.stallState.active) {
    console.warn(
      `[sim-stall] recovered after ${now - S.stallState.sinceMs} ms · ` +
        `frame=${new Date(t.lastRespAt || now).toISOString()}`,
    );
    S.stallState.active = false;
    S.stallState.backoffMs = _STALL_BACKOFF_START;
    _hideStallBanner();
  }
}

// Abort a possibly-hung in-flight fetch and fire a fresh tick now. The
// hung tick's fetch rejects with AbortError and returns without
// rescheduling, so we don't end up with two live loops.
export function _retryTickNow() {
  if (!S.session) return;
  try {
    S.session.abort?.abort();
  } catch {
    /* ignore */
  }
  if (S.session.tickHandle) {
    clearTimeout(S.session.tickHandle);
    S.session.tickHandle = null;
  }
  _tick();
}

export function _showStallBanner() {
  const host = zoneEl('video') || byId('lightboxMediaWrap');
  if (!host) return;
  let banner = byId('mvLiveStallBanner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'mvLiveStallBanner';
    banner.className = 'mv-ld-stall-banner';
    banner.innerHTML =
      '<div class="mv-ld-stall-inner">' +
      '<div class="mv-ld-stall-spinner" aria-hidden="true"></div>' +
      '<div class="mv-ld-stall-text">Verbindung zur Kamera unterbrochen — ' +
      'versuche erneut zu verbinden …</div>' +
      '<button type="button" class="mv-ld-stall-retry" data-action="stall-retry">' +
      'Erneut versuchen</button>' +
      '</div>';
    banner.querySelector('[data-action="stall-retry"]')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      console.warn('[sim-stall] manual retry');
      S.stallState.backoffMs = _STALL_BACKOFF_START;
      _retryTickNow();
    });
    host.appendChild(banner);
  }
  banner.style.display = 'flex';
}

export function _hideStallBanner() {
  const banner = byId('mvLiveStallBanner');
  if (banner) banner.remove();
}
