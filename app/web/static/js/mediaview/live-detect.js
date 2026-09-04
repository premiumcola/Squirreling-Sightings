// ─── mediaview/live-detect.js ──────────────────────────────────────────────
// Live-detect mount for the MediaView shell — reuses the recorded
// lightbox chrome end-to-end (Close-X relocated to the top bar,
// 16:9 wrap, scrubber + class-coloured swimlanes via
// lbRenderTrackTimeline, panel-tabs strip, fine-analysis fold) and
// adds the live-specific pieces: an MJPEG-frame <img> sourced from
// the 1 Hz test-detection snapshot, an SVG bbox overlay, an
// overlay-toggles row above the playbar, and an LIVE pill pinned to
// the right edge of the scrubber.
//
// Per-track data flows through synthetic _tracks payloads that mimic
// the tracks.json shape the recorded swimlane already renders. The
// live tracker's response does NOT expose per-track ids yet — we
// fall back to per-label grouping (one synthetic Track per label,
// detections accumulating as samples) per the cm-52 follow-up
// prompt's graceful-degradation rule.
//
// Lifecycle:
//   openLiveDetect({camId, cameraName})  — mount + start polling.
//   closeLiveDetect()                    — abort + stop + teardown.
// closeLightbox() in lightbox.js fires closeLiveDetect via the
// window bridge so any modal-close path tears the session down.
// L5 · live-detect.js is now the thin ENTRY: openLiveDetect / closeLiveDetect
// + the window bridges. The render/poll/chrome/overlay/panel/stall/diag
// bodies live in the sibling modules below; this file just orchestrates the
// session lifecycle.
import { byId } from '../core/dom.js';
import { S } from './live-detect-state.js';
import { _tick } from './live-detect-poll.js';
import { _setupLiveChrome, _mountPanels } from './live-detect-chrome.js';
import { _startHoldRefresh } from './live-detect-stall.js';
import { _renderDiagStrip } from './live-detect-diag.js';
import { state } from '../core/state.js';
// Imported for real, not re-exported: _tearDownForOpen calls it below.
import { closeLiveDetect } from './_live-detect-teardown.js';
export { closeLiveDetect } from './_live-detect-teardown.js';

// The four modes routes/cameras.py's _TUNING_ENUM_FIELDS accepts. A
// value outside this set means the stored config drifted from the
// backend's own enum — fall back to 'off' rather than sending the
// server something it will reject.
const _ROI_MODES = ['off', 'roi', '2x2', '3x3'];

/** The camera's configured roi_mode, or 'off' when unknown. */
function _configuredRoiMode(camId) {
  const cam = (state.cameras || []).find((c) => c.id === camId);
  const mode = cam && cam.roi_mode;
  return _ROI_MODES.includes(mode) ? mode : 'off';
}

// The cadence constants moved to _live-detect-cadence.js, next to the
// arithmetic written against them (and unit-tested there). Re-exported
// here so every existing importer keeps its `from './live-detect.js'`.
export {
  _TICK_FLOOR_SUB_MS,
  _TICK_FLOOR_MAIN_MS,
  _TICK_MAX_MS,
  _TICK_FACTOR,
  _HOLD_MS_CEILING,
  _HOLD_MS_FLOOR,
} from './_live-detect-cadence.js';

// Shared tunables live in a leaf module so a sibling can read a
// threshold without importing this file (which touches `window` at
// load). Re-exported here: every existing importer keeps working.
// A re-export does NOT bind the name locally, so anything used inside
// this file is imported for real as well — see _STALL_BACKOFF_START.
import { _STALL_BACKOFF_START } from './_live-detect-consts.js';
export {
  _LIVE_WINDOW_MS,
  _TRACE_CAP,
  _TRACE_TICK_CAP,
  _HOLD_REFRESH_MS,
  _STALL_FLOOR_MS,
  _STALL_FACTOR,
  _PACE_FLOOR_MS,
  _STALL_BACKOFF_START,
  _STALL_BACKOFF_MAX,
  _INFLIGHT_ABORT_CEILING_MS,
  _TICK_RETRY_WHILE_INFLIGHT_MS,
} from './_live-detect-consts.js';

// Q2-5 · stall watchdog state. `active` flips on when the frame gap
// crosses the adaptive threshold; `nextRetryAt` paces the backoff.
// L1 · overlay-layer visibility booleans. The shared overlay-toggles
// bar (overlay-toggles.js) owns the pills + their localStorage
// persistence; live seeds this mirror from the bar's getState() at
// mount (_setupLiveChrome) and the bar's onChange keeps it in sync.
// The SVG render code reads ONLY these booleans, never the pill DOM.

// B12 · capture whether a prior session was mounted BEFORE closeLiveDetect
// nulls it. Surfaced on the MOUNT row as torn_down_prev so a back-to-back
// cam switch is visible.
//
// Defensive: the shared #lightboxModal may be mid-weather or mid-recorded
// (one container for all modes) — tear those down + restore their borrowed
// DOM so two modes never coexist on one modal.
function _tearDownForOpen() {
  const tornDownPrev = !!S.session;
  closeLiveDetect();
  try {
    window.closeWeatherMode?.();
  } catch {
    /* ignore */
  }
  try {
    window.closeRecordedMode?.();
  } catch {
    /* ignore */
  }
  byId('lightboxModal')?.classList.remove('lb-weather', 'lb-recorded', 'lb-fs-video');
  return tornDownPrev;
}

// A fresh session plus every per-open counter reset. Nothing here touches
// the DOM — that is _mountChrome's job, and it must run after this so the
// renderers find a session to read.
//
// EXPORTED for live-detect-session.js, the headless producer the unified
// player starts. That module needs exactly this and nothing else from the
// legacy open path: seeding a session by hand there would be a second,
// drifting definition of the object every module in this package writes
// to — and _storeFrameState dereferences it with no optional chaining
// (_live-detect-frame.js), so a session missing a field is a TypeError
// mid-tick, not a degraded render.
export function _seedSession(camId, cameraName, tornDownPrev) {
  S.session = {
    camId,
    cameraName,
    abort: null,
    tickHandle: null,
    fold: null,
    startedMs: Date.now(),
    lastNonEmptyTickMs: 0,
    holdHandle: null,
    // C2/C3 · ephemeral sim controls (per-open, not persisted). Default
    // MAIN stream so the sim mirrors the production alarm pipeline.
    stream: 'main',
    // …and seed MODUS from what the camera actually runs, for the same
    // reason. This was hardcoded 'off', so opening the simulator on a
    // camera configured for 2x2 quietly diagnosed a pipeline the camera
    // does not use — one more way the panel disagreed with production.
    // Note the sim tiles EVERY tick while production tiles only as a
    // rescue; matching the MODE is the part that belongs here, and the
    // trace already states that cadence difference itself.
    detMode: _configuredRoiMode(camId),
  };
  S.traceLines = [];
  S.traceTicks = [];
  S.detBuffer = [];
  S.selectedLabel = null;
  S.stallState = { active: false, backoffMs: _STALL_BACKOFF_START, nextRetryAt: 0, sinceMs: 0 };
  // L1 · overlays are seeded from the shared toggle bar at mount
  // (_setupLiveChrome → renderOverlayToggles().getState()).
  // H2.a · reset the diag-strip state per session so the previous
  // open's last-known SVG dims don't bleed into the new one.
  S.diagState.bbox = null;
  S.diagState.trails = null;
  S.diagState.posFail = null;
  S.diagState.paintFail = null;
  S.diagState.tick = null;
  S.diagState.mount = null;
  S.diagState.cadence = null;
  // B7/B12 · reset tick lifecycle state. Keep startedAt fresh on
  // every open so the strip's mounted_ms_ago matches the user's
  // last action — not some half-finished prior session.
  S.tickState.lastTickAt = 0;
  S.tickState.lastRespAt = 0;
  S.tickState.lastContactAt = 0;
  S.tickState.lastStatus = '—';
  S.tickState.nextTickAt = 0;
  S.tickState.startedAt = Date.now();
  S.tickState.startedWithCamId = camId;
  S.tickState.ticksDroppedLate = 0;
  S.tickState.lastDropReason = null;
  S.tickState.tornDownPrev = tornDownPrev;
  S.tickState.lastTickError = null;
  S.tickState.lastCycleMs = NaN;
  S.tickState.lastFloorMs = NaN;
  S.tickState.lastDelayMs = NaN;
  // C84 · reset hold-time state per session so a fresh cam-open
  // doesn't inherit the previous camera's cadence as the seed EMA.
  S.cycleEmaMs = NaN;
  S.holdMsActive = NaN;
}

// B12' · always-on MOUNT row. Tracks every step of the mount path
// so a screenshot tells us at a glance whether chrome rendered,
// whether _tick() threw, and whether a first-tick setTimeout was
// actually scheduled. Healthy mounts paint muted; any error flips
// the row red and persists until the next successful mount.
function _mountChrome(camId, cameraName, tornDownPrev) {
  const mountRecord = {
    started_at: new Date(S.tickState.startedAt).toISOString(),
    started_with_camId: camId,
    torn_down_prev: tornDownPrev ? 'true' : 'false',
    chrome_mounted: 'false',
    first_tick_scheduled: 'false',
    error: '',
  };
  let chromeOk = false;
  let mountErr = null;
  try {
    _setupLiveChrome(camId, cameraName);
    _mountPanels();
    chromeOk = true;
  } catch (err) {
    mountErr = err;
  }
  mountRecord.chrome_mounted = chromeOk ? 'true' : 'false';
  if (chromeOk) {
    try {
      _tick();
    } catch (err) {
      mountErr = err;
    }
  }
  if (mountErr) {
    mountRecord.error = (mountErr && (mountErr.message || String(mountErr))) || 'unknown';
  }
  // Initial paint of the MOUNT row — success-muted or error-red.
  // first_tick_scheduled stays "false" here; the 250 ms watchdog
  // below promotes it to "true" once we observe a tickHandle.
  S.diagState.mount = { ...mountRecord, _err: !!mountErr };
  _renderDiagStrip();
  _startHoldRefresh();
}

// SIMU-FIX-01c · lock both <html> and <body> overflow + height
  // for the lifetime of the live-detect session so the viewport
  // itself never scrolls — only zone-detail does. Previous values
  // are saved on S.session so closeLiveDetect can restore them
  // verbatim (a recorded-clip lightbox might rely on body overflow:
  // scroll, for example). Explicit height:100dvh on both belt-and-
// suspenders against iOS Safari's address-bar-collapse viewport
// changes leaving body taller than the new viewport.
function _lockViewport() {
  S.session.prevBodyOverflow = document.body.style.overflow;
  S.session.prevHtmlOverflow = document.documentElement.style.overflow;
  S.session.prevBodyHeight = document.body.style.height;
  S.session.prevHtmlHeight = document.documentElement.style.height;
  document.body.style.overflow = 'hidden';
  document.documentElement.style.overflow = 'hidden';
  document.body.style.height = '100dvh';
  document.documentElement.style.height = '100dvh';
}

// B12' · 250 ms watchdog. ONE-SHOT — fires once, then cleared.
// Two outcomes: tickHandle present → mark first_tick_scheduled
// true (success path); tickHandle still null → promote MOUNT row
// to error with "no first-tick scheduled within 250ms".
function _armFirstTickWatchdog() {
  const expectedSessionStart = S.tickState.startedAt;
  setTimeout(() => {
    // Different session by now → leave its own MOUNT row alone.
    if (!S.session || S.tickState.startedAt !== expectedSessionStart) return;
    const scheduled = !!S.session.tickHandle;
    const rec = S.diagState.mount || {};
    rec.first_tick_scheduled = scheduled ? 'true' : 'false';
    if (!scheduled && !rec.error) {
      rec.error = 'no first-tick scheduled within 250ms';
      rec._err = true;
    }
    S.diagState.mount = rec;
    _renderDiagStrip();
  }, 250);
}

export function openLiveDetect({ camId, cameraName }) {
  if (!camId) return;
  const tornDownPrev = _tearDownForOpen();
  _seedSession(camId, cameraName, tornDownPrev);
  _mountChrome(camId, cameraName, tornDownPrev);
  _lockViewport();
  _armFirstTickWatchdog();
}


// gp384 — bbox hold + empty-banner refresh. Drives the per-frame
// opacity fade-out for held detections and the show/hide of the
// "Aktuell keine Detektionen" banner. setInterval rather than
// requestAnimationFrame so the rate is fixed (the detector tick is
// 1 Hz anyway — animating at 60 Hz would just burn CPU without
// any visible benefit).

window.closeLiveDetect = closeLiveDetect;
// SIMU-06c · live-detect-debug.js reads the current overlay-toggle
// snapshot via this bridge so the debug snapshot reflects exactly
// what the user has on screen at copy-time.
window._mvLdOverlaysSnapshot = function () {
  const parts = [];
  for (const [k, v] of Object.entries(S.overlays)) {
    parts.push(`${k}=${v ? 'on' : 'off'}`);
  }
  return parts.join(' · ');
};
