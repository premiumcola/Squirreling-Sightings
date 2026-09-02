// ─── mediaview/_live-detect-consts.js ──────────────────────────────────────
// Every tunable number the live-detect cluster shares, and nothing else.
// A leaf: it imports nothing, so a sibling can read a threshold without
// pulling in live-detect.js — which touches `window` at module load and
// therefore cannot be loaded under node.
//
// live-detect.js re-exports all of these, so nothing outside the cluster
// had to change when they moved here.

// C84 · dynamic bbox hold-time scaffolding. The cycle EMA is
// populated by _scheduleNext on every cycle, then S.holdMsActive
// is derived from it (clamp(2*EMA, 800, 1500)). Both stay valid
// at module level so the CADENCE row from C73 can read them
// without late-binding gymnastics.
// 60 s sliding window for the swimlane. Detections older than this
// age out of the visible strip.
export const _LIVE_WINDOW_MS = 60_000;
export const _TRACE_CAP = 80;
// Q2-3 · the Trace tab groups the raw decision-trace BY TICK (one
// backend response = one block, newest on top). Keep the last 20 ticks
// — enough scroll-back to compare a few cycles without unbounded growth.
export const _TRACE_TICK_CAP = 20;
// Refresh interval for the hold-time fade. SIMU-02d removed the
// persistent "empty state" video banner — the absence of detections
// is now expressed via the empty Detections tab (SIMU-04+) instead
// of an overlay element that covered ~30% of the video.
// Fires at ~24 Hz; the actual bbox repaints are cheap (innerHTML
// of an SVG with < 10 elements) and only run while live-detect is
// mounted, so the cost is negligible vs. the smoothness gain.
export const _HOLD_REFRESH_MS = 250;

// Q2-5 · stall detection. The background is now the per-tick inference
// snapshot (Q2-4), so "no new frame for a while" == "no successful tick
// for a while". The threshold is ADAPTIVE: a healthy camera ticks fast
// but a slow twilight camera can legitimately take many seconds per
// cycle (the user's "Nut Bar" cam runs ~7.8 s avg), so a fixed 4-5 s
// would false-fire constantly there. We flag a stall only when the gap
// since the last frame exceeds max(5 s floor, 2.2 × the camera's own
// recent cadence) — responsive on fast cams, quiet on slow ones.
export const _STALL_FLOOR_MS = 5000;
export const _STALL_FACTOR = 2.2;
// Floor for the PACE notice ("Analyse läuft noch — 3×3 kostet 10
// Inferenzen je Bild"), which is informational and never aborts. It is
// deliberately NOT scaled by the mode's inference count: multiplying a
// 5 s floor by ten handed 3×3 a 50 s budget, so the notice written FOR
// the expensive modes could not appear in any of them. The steady state
// is still governed by `_STALL_FACTOR × cadence`, so a camera that
// genuinely ticks every 4 s does not sit under a permanent notice — this
// floor only decides how soon after a mode switch (which resets the
// cadence EMA) the operator is told why the picture is holding still.
export const _PACE_FLOOR_MS = 2500;
// Auto-retry backoff while stalled: 1 s → 2 s → 4 s → 8 s (capped).
export const _STALL_BACKOFF_START = 1000;
export const _STALL_BACKOFF_MAX = 8000;
// A request younger than this is never aborted, however stalled the view
// looks. Flask cannot cancel a request — the handler runs all its
// inferences to completion regardless — so an abort-and-retry does not
// free the server, it doubles its load. See live-detect-stall.js.
export const _INFLIGHT_ABORT_CEILING_MS = 30_000;
// How long a tick that found a request already in flight waits before
// looking again. The request is NOT aborted (see above) and no second
// one is issued, so this is a poll on someone else's work, not a retry.
export const _TICK_RETRY_WHILE_INFLIGHT_MS = 500;
