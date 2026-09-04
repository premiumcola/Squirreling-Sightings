// ─── mediaview/live-detect-poll.js ─────────────────────────────────────────
// The 1 Hz test-detection poll loop: _tick fetches a frame and _scheduleNext
// paces the adaptive cadence + hold EMA. State via S.
//
// The pure parts were lifted into siblings so they can be unit-tested with no
// DOM, session or socket — this file keeps every decision, they keep the
// arithmetic behind it:
//   _live-detect-cadence.js          cadence floors, delay, cycle EMA, hold
//   _live-detect-tick-status.js      in-flight age/pending + ok=false verdicts
//   _live-detect-frame-observers.js  the onLiveFrame registry
//   _live-detect-frame.js            what ONE response turns into on screen
import { S } from './live-detect-state.js';
import { _refreshCadenceRow } from './live-detect-diag.js';
import { _healthInfo } from './live-detect-stall.js';
import { showOutage, showHealth, registerVerdictAction } from './live-detect-verdict.js';
import { mvModeInvokes } from './mode-indicator.js';
import { _cadenceForCycle, _nextCycleEma, _holdMsFromEma } from './_live-detect-cadence.js';
import {
  _inflightAgeMs,
  _isInflightPending,
  _classifyTickFailure,
} from './_live-detect-tick-status.js';
import { _renderFrame } from './_live-detect-frame.js';
export { onLiveFrame } from './_live-detect-frame-observers.js';
import { _INFLIGHT_ABORT_CEILING_MS, _TICK_RETRY_WHILE_INFLIGHT_MS } from './live-detect.js';

// L1 · the toggle-pill glyphs, _TOGGLES dict and the hover/long-press
// tooltip popover were lifted into the shared overlay-toggles.js (which
// uses core/tooltip.js for the popover). Live now mounts that one bar in
// _setupLiveChrome — see the renderOverlayToggles call there.

// C2/C3 · re-tick immediately when the operator changes a sim control so
// the new stream / mode takes visible effect on the next frame instead of
// waiting out the current cadence delay.

// P7 · the in-flight contract, enforced for EVERY caller and not only in
// the stall watchdog. `_tick` used to abort at its head unconditionally,
// which made the documented "a request younger than 30 s is never
// aborted" false for the path the operator uses most: _forceImmediateTick
// (mode or stream change) calls straight in here. The threshold itself is
// _isInflightPending — see _live-detect-tick-status.js for why waiting
// beats racing. Here we only act on its verdict: say so on screen (the
// busy notice) and re-arm.
//
// Returns true when the caller must stand down; it has re-armed itself.
function _deferWhileInflight(session) {
  const inflightMs = _inflightAgeMs(session.inflightSince, Date.now());
  if (!_isInflightPending(inflightMs, _INFLIGHT_ABORT_CEILING_MS)) return false;
  if (session.tickHandle) clearTimeout(session.tickHandle);
  session.tickHandle = setTimeout(_tick, _TICK_RETRY_WHILE_INFLIGHT_MS);
  return true;
}

// B23' · an ok=false response. Stash the code+message for the fold's
// "Letzter Tick" line, and paint the verdict band.
//
// The band is the fix for the outage being INVISIBLE. Only two of the
// endpoint's ten failure bodies used to reach a surface at all, and both
// reached the legacy modal's host — a node the unified player does not
// render, so nothing was on screen. Everything now goes through one
// classifier (_live-detect-outage.js) and one band, so a mode that
// nobody wrote a special case for still says what it is instead of
// leaving the panel looking idle.
//
// The fold keeps its own copy deliberately: it is the scroll-back, and
// the band only ever shows the CURRENT truth.
function _handleTickFailure(status, data) {
  const { text } = _classifyTickFailure(status, data);
  S.tickState.lastTickError = text;
  S.session?.fold?.setLastError?.(text);
  showOutage({ kind: 'http', status, data });
}

// The way out of a mode this hardware cannot sustain. Registered rather
// than passed to the banner: the verdict band owns no knowledge of the
// loop, and the loop owns no knowledge of the band's markup.
registerVerdictAction('mode-off', () => _fallbackToOff());

// Supersede whatever was in flight and stamp the new request's clock.
// Returns the controller this tick must be judged against — every later
// `session.abort === controller` check asks "am I still the current one".
//
// PRECONDITION: the caller has already cleared _deferWhileInflight(session),
// i.e. nothing younger than _INFLIGHT_ABORT_CEILING_MS is in flight. The
// abort below is only safe under that gate — Flask cannot cancel a running
// handler, so aborting a young request doubles the server's load instead of
// freeing it. _tick is the only caller, and it checks first.
function _beginTick(session) {
  S.tickState.lastTickAt = Date.now();
  // Safe only because _deferWhileInflight(session) already stood down
  // anything younger than _INFLIGHT_ABORT_CEILING_MS — see above.
  try {
    session.abort?.abort();
  } catch {
    /* ignore */
  }
  session.abort = new AbortController();
  // When this request went out. The stall watchdog refuses to abort a
  // request younger than _INFLIGHT_ABORT_CEILING_MS — aborting one only
  // adds load, it never removes any (Flask runs the handler to the end).
  session.inflightSince = Date.now();
  return session.abort;
}

// custom: AbortController for the live-detect polling loop —
// each tick supersedes the previous in-flight request when the
// camera changes or the loop stops. apiPost has no signal hook.
// Q2-4 · no_snapshot is intentionally OFF now: the simulation view
// paints the exact frame inference ran on (data.snapshot) as the
// background so the bbox overlay and the picture are one and the
// same frame. See _setupLiveChrome for the full rationale.
// C2/C3 · pass the ephemeral sim controls — which stream to inspect
// (main|sub) and the detection mode (off|roi|2x2|3x3).
function _requestFrame(session, controller) {
  const _params = new URLSearchParams({
    stream: session.stream || 'main',
    mode: session.detMode || 'off',
    // Sim only; unset on live, which always runs the real profile.
    ...(session.revision ? { revision: session.revision } : {}),
  });
  return fetch(`/api/cameras/${encodeURIComponent(session.camId)}/test-detection?${_params}`, {
    method: 'POST',
    signal: controller.signal,
  });
}

// Returns false when the caller must return WITHOUT re-scheduling: a
// response that outlived its session is dropped, not paced.
async function _consumeResponse(r, session, controller) {
  S.tickState.lastStatus = r.status;
  // P2 · contact is contact, whatever the status. A backend answering
  // 429 or 503 promptly is NOT a disconnected camera, and stamping this
  // only on ok=true is what made a refusing endpoint show
  // "Verbindung zur Kamera unterbrochen" indefinitely.
  S.tickState.lastContactAt = Date.now();
  // B31 / B31' · late-tick guard. The session can be replaced
  // or nulled by a concurrent stopLive / cam switch between
  // fetch-issue and fetch-resolve. We count the drop and stash
  // the reason ("session_null" when nothing is mounted now,
  // "cam_mismatch" when a different cam was opened in between)
  // so a STUCK-looking TICK row + dropped=N + drop_reason tells
  // the user "responses ARE arriving, they're just landing too
  // late" — a very different fix from "loop isn't running".
  if (S.session !== session) {
    S.tickState.ticksDroppedLate = (S.tickState.ticksDroppedLate || 0) + 1;
    S.tickState.lastDropReason = S.session === null ? 'session_null' : 'cam_mismatch';
    return false;
  }
  let data = null;
  try {
    data = await r.json();
  } catch {
    /* keep null */
  }
  if (data?.ok) {
    S.tickState.lastRespAt = Date.now();
    S.tickState.lastTickError = null;
    // B23' · a successful tick clears any error banner the fold
    // may have been showing. _renderFrame's _appendTrace path
    // will repopulate the trace lines anyway, but the explicit
    // clear protects against an empty-trace ok=true response.
    S.session?.fold?.setLastError?.(null);
    _renderFrame(data);
    // AFTER the frame, because the healthy verdict reads the device this
    // tick actually ran on — which _renderFrame is what stores. A tick
    // that succeeded on the CPU because the TPU was taken is still a
    // finding, and it is the one the panel used to swallow whole.
    showHealth(_healthInfo());
  } else {
    _handleTickFailure(r?.status, data);
  }
  if (session.abort === controller) session.inflightSince = 0;
  return true;
}

// Returns false when the caller must return WITHOUT re-scheduling: an
// aborted request was superseded on purpose, and its replacement owns
// the cadence from here.
function _handleTickError(err, session, controller) {
  // Only the CURRENT request may clear the stamp: an abandoned one
  // rejects late, after a replacement has already gone out.
  if (session.abort === controller) session.inflightSince = 0;
  if (err?.name === 'AbortError') {
    S.tickState.lastStatus = 'abort';
    return false;
  }
  S.tickState.lastStatus = 'neterr';
  const why = (err && (err.message || String(err))) || 'unknown';
  const text = `neterr · ${why}`;
  S.tickState.lastTickError = text;
  S.session?.fold?.setLastError?.(text);
  // A rejected fetch never reached the server, so nothing on the box can
  // report it — this band is the only place the operator can learn that
  // the browser, not the camera, is the one that lost contact.
  showOutage({ kind: 'neterr', message: why });
  return true;
}

export async function _tick() {
  const session = S.session;
  if (!session) return;
  if (_deferWhileInflight(session)) return;
  const controller = _beginTick(session);
  const cycleStart = performance.now();
  try {
    const r = await _requestFrame(session, controller);
    if (!(await _consumeResponse(r, session, controller))) return;
  } catch (err) {
    if (!_handleTickError(err, session, controller)) return;
  }
  _scheduleNext(session, performance.now() - cycleStart);
}

export function _scheduleNext(session, lastCycleMs) {
  if (S.session !== session) return;
  // The floor/delay arithmetic (C73's per-stream floor, P5's mode-scaled
  // ceiling) and the C84 cycle EMA + hold clamp live in
  // _live-detect-cadence.js. Order of the writes below is load-bearing for
  // the CADENCE diag row, which reads all four together.
  const { floor, cycleMs, delay } = _cadenceForCycle(
    lastCycleMs,
    session.lastFrameSrc || 'unknown',
    mvModeInvokes(session.detMode || 'off'),
  );
  S.tickState.nextTickAt = Date.now() + delay;
  S.tickState.lastCycleMs = cycleMs;
  S.tickState.lastFloorMs = floor;
  S.tickState.lastDelayMs = delay;
  S.cycleEmaMs = _nextCycleEma(S.cycleEmaMs, cycleMs);
  S.holdMsActive = _holdMsFromEma(S.cycleEmaMs);
  session.tickHandle = setTimeout(_tick, delay);
  _refreshCadenceRow();
}

// Drop back to the whole-frame single pass and re-tick. Used when the
// backend refuses the selected mode: leaving the operator on a mode that
// cannot run would just keep the refusal on screen.
function _fallbackToOff() {
  if (!S.session) return;
  S.session.detMode = 'off';
  S.cycleEmaMs = NaN;
  S.session.shell?.components?.setDetMode?.('off');
  if (S.session.tickHandle) {
    clearTimeout(S.session.tickHandle);
    S.session.tickHandle = null;
  }
  _tick();
}
