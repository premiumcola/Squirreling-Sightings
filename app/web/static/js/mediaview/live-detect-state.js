// ─── mediaview/live-detect-state.js ────────────────────────────────────────
// L5 · the single mutable-state container for the live-detect player.
// Every live-detect module imports this ONE object and mutates it by
// reference (S.session = …, S.detBuffer.push(…)), so the lifecycle,
// poll loop, overlay renderers, panels and trace all share one source
// of truth without a web of cross-module re-exports. Reset per session
// in openLiveDetect.
//
// (Module-level `let` bindings can't be shared across ES modules — a
// reassignment in one file wouldn't be visible in another. A single
// exported object sidesteps that: the binding `S` is constant, its
// properties are the mutable state.)
export const S = {
  // poll cadence
  cycleEmaMs: NaN,
  holdMsActive: NaN,
  // session + rolling buffers
  session: null,
  traceLines: [],
  traceTicks: [], // [{ts, lines:[…]}, …] — per-tick groups for the Trace tab
  detBuffer: [], // [{ms, label, score, bbox, verdict}, …]
  // stall watchdog (re-seeded in openLiveDetect; backoffMs floor = 1000)
  stallState: { active: false, backoffMs: 1000, nextRetryAt: 0, sinceMs: 0 },
  // overlay-layer visibility mirror (seeded from the shared toggle bar)
  overlays: { bboxes: true, trails: true, zones: false, masks: false },
  selectedLabel: null, // for detail-pill pin
  lastFullDataForDebug: null,
  legacyDebugKeysCleaned: false,
  // _positionSvgOverImage scratch (read by the legacy debug strip)
  lastMediaBranch: null,
  lastVideoRejected: null,
  lastImgRejected: null,
  // legacy in-modal debug strip state (no-op surface; _debugDiagOn=false)
  diagState: {
    bbox: null,
    trails: null,
    zonemask: null,
    media: null,
    tick: null,
    posFail: null,
    paintFail: null,
    mount: null,
    cadence: null,
  },
  // raw tick-loop state — owned by the poll loop, read by the Debug tab
  tickState: {
    lastTickAt: 0, // _tick() entered
    lastRespAt: 0, // last successful fetch resolved
    lastStatus: '—', // HTTP status code (200/503) or 'abort'/'neterr'
    nextTickAt: 0, // setTimeout deadline
    startedAt: 0, // openLiveDetect wall-clock
    startedWithCamId: '', // camId we attempted to start against
    tornDownPrev: false, // openLiveDetect torn down a prior session
  },
};
