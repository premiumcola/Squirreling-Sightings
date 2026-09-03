// ─── weather/suntltest/_state.js ───────────────────────────────────────────
// Local UI state for the Sun-Timelapse TEST subtab — survives re-renders
// within a single tab visit, reset when a new run starts.
//
// A plain mutable object rather than a set of exported `let`s: an ES
// module's live bindings can only be REASSIGNED inside the module that
// declares them, so `import { _selCam }` elsewhere would have handed out
// a read-only view and every write would have had to come back here.
// One object with fields keeps the writes where they belong.

export const S = {
  cam: null,
  phase: 'sunset',
  duration: 1200,
  targetLength: 10,
  pollTimer: null,
  // G3 · per-slot event cache. Keyed by slot index so the heatmap can
  // render `expected_frames` cells where each cell looks up its event
  // (if any) in O(1). `lastEventTs` feeds the ?since=<float> query so
  // the poll ships the delta only.
  lastEventTs: 0,
  eventBySlot: new Map(),
};

export function resetEventCache() {
  S.eventBySlot = new Map();
  S.lastEventTs = 0;
}
