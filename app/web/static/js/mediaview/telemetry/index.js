// ─── mediaview/telemetry/index.js ──────────────────────────────────────────
// "Analyse & Auslastung" — the one data source behind two surfaces:
//
//   * a single cost line under the mode switch, because that is the moment
//     the question "can I afford 3×3?" is actually asked, and
//   * Debug-tab Cluster 6, which shows the comparison the line is one row of.
//
// The two never repeat each other: the line carries the selected mode's
// number, the cluster carries the table and the time breakdown.
//
// Refresh is its own 5 s timer, NOT the sim tick. Every number here is a
// ~20 s rolling mean over 60 samples; redrawing it twice a second would
// only imply a precision it does not have.
import { esc } from '../../core/dom.js';
import { mvModeLabel } from '../mode-indicator.js';
import { renderDeviceBlock } from './_device.js';
import { renderDutyBlock } from './_duty.js';
import { renderProjectionBlock, modeRow } from './_projection.js';

const _REFRESH_MS = 5000;
const _URL = '/api/telemetry/inference';

let _data = null;
let _fetchedAt = 0;
let _inflight = null;
const _listeners = new Set();

/** Last payload, or null before the first successful fetch. */
export function telemetryData() {
  return _data;
}

/**
 * Fetch (or reuse) the telemetry payload. Coalesces concurrent callers
 * onto one request so several open surfaces cost one round-trip.
 */
export async function fetchTelemetry(force = false) {
  const now = Date.now();
  if (!force && _data && now - _fetchedAt < _REFRESH_MS) return _data;
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      const r = await fetch(_URL);
      const j = await r.json();
      if (j && j.ok) {
        _data = j;
        _fetchedAt = Date.now();
      }
    } catch (err) {
      console.warn('[telemetry] fetch failed:', err && (err.message || err));
    } finally {
      _inflight = null;
    }
    for (const fn of _listeners) {
      try {
        fn(_data);
      } catch {
        /* a broken listener must not stop the others */
      }
    }
    return _data;
  })();
  return _inflight;
}

/** Subscribe to payload refreshes. Returns an unsubscribe function. */
export function onTelemetry(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

/**
 * Mount the one-line cost hint under the mode switch.
 *
 * @param {HTMLElement} host
 * @param {Function} getMode  () => current mode id
 * @returns {{ render(mode): void, teardown(): void }}
 */
export function mountModeCost(host, getMode) {
  if (!host) return null;
  const el = document.createElement('div');
  el.className = 'mv-tele-cost';
  host.appendChild(el);
  const paint = (mode) => {
    el.innerHTML = _costLine(mode || getMode());
  };
  const off = onTelemetry(() => paint(getMode()));
  const timer = setInterval(() => fetchTelemetry(), _REFRESH_MS);
  paint(getMode());
  fetchTelemetry();
  return {
    render: paint,
    teardown: () => {
      clearInterval(timer);
      off();
      el.remove();
    },
  };
}

// One line, for ONE mode. Falls back to the static inference count while
// no measurement has arrived — a cost that is known without hardware
// should not wait for a fetch to be shown.
function _costLine(mode) {
  const row = modeRow(_data, mode);
  if (!row) return '';
  // `invokes` is prod_invokes — TILES ONLY, because production reuses the
  // full-frame pass and spends the tiles on a rescue. It was labelled
  // "Inferenzen/Bild", which is wrong twice over: they are not per frame,
  // and the simulator's own per-tick cost is tiles + 1. Naming the unit
  // "Kacheln je Rettung" makes it agree with the "+N ms je Rettung" it
  // has always sat next to.
  const invokes = row.invokes ? row.invokes[1] : 1;
  // Short by design: at 11.5 px monospace a 375 px phone holds ~53
  // characters, and the old wording ran past 60 — so the projection, the
  // one thing this line exists to show, was the part that got ellipsised.
  const parts = [esc(mvModeLabel(mode))];
  if (row.duty && _data?.projection?.basis === 'tpu') {
    parts.push(`${Math.round(row.duty[1] * 100)} % TPU`);
  }
  if (invokes > 0) {
    parts.push(`${invokes} Kacheln/Rettung`);
  }
  if (row.stall_ms && row.stall_ms[1] > 0) {
    parts.push(`+${row.stall_ms[1]} ms`);
  }
  const tone = row.verdict || 'ok';
  return (
    `<span class="mv-tele-cost-line" data-tone="${esc(tone)}">${parts.join(' · ')}</span>`
  );
}

/**
 * Debug-tab Cluster 6 body. Pure HTML — the caller owns the cluster
 * shell (header, collapse state) so this matches the other five.
 */
export function renderTelemetryBody() {
  if (!_data) {
    return '<div class="mv-ld-empty-row">Telemetrie wird geladen …</div>';
  }
  return (
    renderDutyBlock(_data) + renderProjectionBlock(_data) + renderDeviceBlock(_data)
  );
}

/** Header hint for Cluster 6 — the one-glance verdict. */
export function telemetryHeaderHint() {
  if (!_data) return { tone: 'mute', text: '· wird geladen' };
  const p = _data.projection || {};
  const basis = p.basis === 'tpu' ? 'TPU' : 'CPU';
  const invoke = p.invoke_ms || 0;
  if (!invoke) return { tone: 'mute', text: `· ${basis} · noch keine Messwerte` };
  const worst = (p.modes || []).find((m) => m.mode === '3x3');
  if (worst && worst.verdict === 'over') {
    return { tone: 'warn', text: `⚠ ${basis} · 3×3 überlastet (${invoke} ms je Inferenz)` };
  }
  return { tone: 'ok', text: `· ${basis} · ${invoke} ms je Inferenz` };
}
