// ─── mediaview/_live-detect-frame.js ───────────────────────────────────────
// What ONE test-detection response turns into: the painted snapshot, the
// session's frame state, the swimlane buffer, and the fan-out to every
// overlay/panel renderer. Split out of live-detect-poll.js, which keeps the
// loop itself (_tick, _scheduleNext) — this file is the "consume a frame"
// half and touches no timers, no AbortController and no cadence.
//
// The steps below run in a load-bearing order: state before render (the
// renderers read S.session), and _appendTrace before the Detections panel
// (see the comment at its call site). Keep _renderFrame's call order.
import { byId } from '../core/dom.js';
import { S } from './live-detect-state.js';
import { _renderBboxOverlay } from './live-detect-bbox.js';
import { _renderTrailsOverlay } from './live-detect-overlays.js';
import { _renderDetectionsPanel, _renderLiveSwimlane, _appendTrace } from './live-detect-panels.js';
import { _renderDebugTab, _renderDiagPanel } from './live-detect-tabs.js';
import { _notifyFrameObservers } from './_live-detect-frame-observers.js';
import { _LIVE_WINDOW_MS } from './live-detect.js';

export function _logSimDiag() {
  if (!S.session || S.session._diagLogged) return;
  S.session._diagLogged = true;
  const imgEl = byId('lightboxImg');
  const wrap = byId('lightboxMediaWrap');
  const bboxSvg = byId('lightboxLiveOverlay');
  const trailSvg = byId('lightboxLiveTrails');
  const _rect = (el) => {
    if (!el) return '0x0';
    const r = el.getBoundingClientRect();
    return `${Math.round(r.width)}x${Math.round(r.height)}`;
  };
  const _z = (el) => (el ? window.getComputedStyle(el).zIndex : 'n/a');
  const _disp = (el) => (el ? window.getComputedStyle(el).display : 'n/a');
  const _vb = (el) => (el ? el.getAttribute('viewBox') || 'n/a' : 'n/a');
  const imgSrc = imgEl ? imgEl.src || '<empty>' : '<missing>';
  console.warn(`[sim-diag] imgEl: src=${imgSrc} display=${_disp(imgEl)} rect=${_rect(imgEl)}`);
  console.warn(
    `[sim-diag] bboxSvg: viewBox=${_vb(bboxSvg)} rect=${_rect(bboxSvg)} display=${_disp(bboxSvg)} z-index=${_z(bboxSvg)}`,
  );
  console.warn(
    `[sim-diag] trailSvg: viewBox=${_vb(trailSvg)} rect=${_rect(trailSvg)} display=${_disp(trailSvg)} z-index=${_z(trailSvg)}`,
  );
  console.warn(`[sim-diag] wrap: rect=${_rect(wrap)}`);
  console.warn(
    `[sim-diag] S.session.lastDetections.length=${(S.session.lastDetections || []).length}`,
  );
}

// Q2-4 · paint the exact frame inference ran on as the background.
// data.snapshot is a base64 JPEG whose pixels are in the SAME
// coordinate space as the bbox coords + frame_size used by the SVG
// overlay below — so the box and the picture are guaranteed to match
// (see _setupLiveChrome for why we abandoned the live stream here).
// Setting .src fires the <img> load event → _installLiveOverlayRefresh
// repaints the overlays once decoded; the synchronous repaints later
// in the frame cover the common case.
function _paintSnapshot(data) {
  if (!data.snapshot) return;
  const imgEl = byId('lightboxImg');
  if (imgEl && imgEl.getAttribute('src') !== data.snapshot) {
    imgEl.src = data.snapshot;
    if (imgEl.style.display === 'none') imgEl.style.display = 'block';
  }
}

// Everything the renderers below read off S.session. Written before any
// of them runs, and before the buffer is appended to.
function _storeFrameState(data) {
  // Frame state for the bbox + zone/mask overlays.
  S.session.lastFrameSize = data.frame_size || { w: 1920, h: 1080 };
  S.session.lastDetections = data.detections || [];
  // D52 · cache the full backend response so an out-of-band toggle
  // (e.g. tapping the "<n> verworfen" hint) can re-render the panel
  // without waiting for the next tick.
  S.session.lastFullData = data;
  // A3 · explicit coord-space disclosure from the backend (added in
  // diag by routes/coral_test_detection.py). The debug strip's bbox
  // row reads these to surface bbox_space + source/snap dims; if
  // bbox_space disagrees with the viewBox space (lastFrameSize),
  // the strip flags SPACE MISMATCH so the user sees the regression
  // immediately. All three fall back to undefined on older backends.
  const _diag = data.diag || {};
  S.session.lastBboxSpace = _diag.bbox_space || null;
  S.session.lastSourceFrameSize = _diag.source_frame_size || null;
  S.session.lastSnapshotFrameSize = _diag.snapshot_frame_size || null;
  // S3 · diag.parity declares which gates this endpoint does NOT run.
  // The backend has been assembling that list since the parity change
  // landed and NOTHING read it — a "writes a value nobody reads" bug
  // sitting inside the alarm diagnostics themselves. The Trace tab
  // renders it above the verdict so the operator can tell which half of
  // the answer is measured and which half is simply unchecked.
  S.session.lastParity = _diag.parity || null;
  // C73 · remember which stream the backend served this frame from
  // so _scheduleNext can pick the right floor on the NEXT cycle.
  // Falls back to undefined when an older backend didn't send the
  // field — _scheduleNext treats that as 'unknown' → safe 1 s floor.
  if (_diag.frame_src) S.session.lastFrameSrc = _diag.frame_src;
}

// F2.b · one-shot per-session payload diagnostic. Answers the
// "did the response actually carry detections" question without
// requiring a tcpdump or the docker logs. Counts by verdict so
// the user can spot a serialisation drop between Flask and the
// frontend (rare but possible if response shaping went sideways).
// Single-line console.warn (lint-allowed escape hatch).
function _logFrameDiagOnce(data) {
  if (!S.session || S.session._frameDiagLogged) return;
  S.session._frameDiagLogged = true;
  const dets = S.session.lastDetections;
  const np = dets.filter((d) => d.verdict === 'pass').length;
  const nb = dets.filter((d) => d.verdict === 'tentative').length;
  const nf = dets.filter((d) => d.verdict === 'filtered').length;
  const fs = S.session.lastFrameSize;
  const gates = data.diag?.gates || {};
  console.warn(
    `[sim-frame] dets=${dets.length} pass=${np} below=${nb} filtered=${nf} ` +
      `frame_size=${fs.w}x${fs.h} diag.raw=${gates.raw ?? '?'} ` +
      `outcome=${data.ok ? 'ok' : '?'}`,
  );
}

// The counters the panels read, plus the black-screen one-shot.
function _stampFrameCounters(data) {
  // F2 · track the latest raw count from the backend's diag block.
  // Read by the debug strip + (later) the Detections tab summary
  // line. SIMU-02d removed the in-video banner that used to gate on
  // this value; the field stays for downstream consumers.
  S.session.lastRawCount = Number(data.diag?.gates?.raw ?? data.detections?.length ?? 0);
  // Last-seen marker for the no-detection state. Reset on every
  // tick that brings at least one detection. Read by the Detections
  // tab + Trace tab consumers; the in-video banner that used to
  // depend on this was removed in SIMU-02d.
  if (S.session.lastDetections.length) S.session.lastNonEmptyTickMs = Date.now();
  // vh729 — one-shot diagnostic. Fires once per Simulieren open
  // (right after the first tick lands real data) and prints the
  // state of every visual layer the user can't see when the
  // modal looks black. Single source of truth that answers
  // "which surface is broken" without needing DevTools.
  // console.warn is the lint-allowed escape hatch
  // (eslint no-console: { allow: ['warn', 'error'] }).
  _logSimDiag();
}

// Buffer detections for the swimlane window (one entry per detection
// per tick; per-track id would be ideal here but the live tracker
// doesn't expose ids — group by label instead).
function _bufferDetections(data) {
  const now = Date.now();
  for (const d of data.detections || []) {
    S.detBuffer.push({
      ms: now,
      label: d.label,
      score: d.score,
      bbox: d.bbox,
      verdict: d.verdict,
      // SIMU-02e · track_num is the monotonically-assigned display
      // number from the backend's per-cam test-tracker. May be null
      // on the very first detection of a fresh session if association
      // happened to fail; the renderer then skips the badge.
      track_num: d.track_num,
    });
  }
  // Drop entries older than the window.
  const cutoff = now - _LIVE_WINDOW_MS;
  S.detBuffer = S.detBuffer.filter((e) => e.ms >= cutoff);
}

function _renderFrameLayers(data) {
  _renderBboxOverlay();
  _renderTrailsOverlay();
  // SIMU-FIX-05d · append trace lines BEFORE rendering the
  // Detections tab — its Track-Ereignisse section reads from
  // `S.traceLines` and was previously seeing the PREVIOUS tick's
  // trace (empty on the very first tick → "Noch keine Track-
  // Ereignisse" while the Trace tab simultaneously showed SPAWN
  // events from the same response).
  _appendTrace(data.decision_trace || []);
  _renderDetectionsPanel(data);
  _renderLiveSwimlane();
  _renderDiagPanel(data.diag || null);
  _renderDebugTab(data);
  _notifyFrameObservers(data);
}

// A HEADLESS session (live-detect-session.js) owns no chrome and must not
// touch the legacy player's. Skipping the render fan-out is not an
// optimisation — those renderers do not throw without their chrome, but
// they are far from inert: _paintSnapshot writes a base64 JPEG into the
// STATIC #lightboxImg every tick, _ensureOverlayLayer creates SVGs inside
// #lightboxMediaWrap, _renderLiveSwimlane overwrites #lightboxBottomStack
// — the RECORDED player's swimlane host — and stamps its fingerprint, and
// _pinScrubberRight sets --play-pct: 1 on every .lb-time-stack in the
// document. Subscribers still get their frame; that is the whole point.
//
// The legacy sequence below is deliberately byte-identical to what it has
// always been. The two branches bracket it rather than reordering it.
export function _renderFrame(data) {
  const headless = !!S.session?.headless;
  if (!headless) _paintSnapshot(data);
  _storeFrameState(data);
  _logFrameDiagOnce(data);
  _stampFrameCounters(data);
  _bufferDetections(data);
  if (headless) {
    _notifyFrameObservers(data);
    return;
  }
  _renderFrameLayers(data);
}
