// ─── vplayer/_data/status.js ───────────────────────────────────────────────
// The system status the live panel needs, and nothing else.
//
// One fact comes from here rather than from the frame: the TPU busy
// ratio. The detection endpoint reports which DEVICE ran a tick
// (`modes.inference.device`) but not how loaded it is; the utilisation
// counters live on the runtimes and are published by /api/status, which
// is where panels/_helpers.js::tpuFor already looks for them.
//
// Until this module existed the panel was handed a hard-coded `null` for
// status on every frame (`panel?.update(frame, null)`), so the TPU chip
// could never read anything but a placeholder — a defect entirely
// separate from the poll loop not running, and one that would have
// survived fixing it.
//
// NO SECOND POLLER. The obvious shape — a setInterval next to the
// detection loop — puts a second client on the same Flask worker the 1 Hz
// detection loop is already pacing itself against, for a number that
// changes slowly and only matters while frames are arriving anyway. So
// this rides the frame cadence instead: the caller asks on every tick,
// and the fetch actually goes out at most every `_MIN_GAP_MS`. No timer
// of its own means nothing to leak on teardown.

/** How stale the busy ratio may get. It is a ~10 s rolling window. */
const _MIN_GAP_MS = 8000;

let _cached = null;
let _lastAt = 0;
let _inflight = false;

/**
 * The last known status, refreshing it in the background when stale.
 *
 * Returns SYNCHRONOUSLY and possibly stale — deliberately. A panel
 * repainting at the detection cadence must never wait on a second
 * request to draw the frame it already has; the chip fills a moment
 * later, on the next tick, which for a slowly-moving ratio is
 * indistinguishable.
 *
 * @returns {object|null} the /api/status body, or null before the first
 *   answer lands. Null is what tpuFor already treats as "unknown", so a
 *   failed or pending fetch renders the placeholder rather than a zero —
 *   "no reading" and "idle" are different facts.
 */
export function liveStatus() {
  const now = Date.now();
  if (!_inflight && now - _lastAt > _MIN_GAP_MS) {
    _inflight = true;
    _lastAt = now;
    fetch('/api/status', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (body && typeof body === 'object') _cached = body;
      })
      .catch(() => {
        /* the chip keeps its last reading; a panel must still paint */
      })
      .finally(() => {
        _inflight = false;
      });
  }
  return _cached;
}

/** Drop the cache. Called when a player closes so the next open is fresh. */
export function resetLiveStatus() {
  _cached = null;
  _lastAt = 0;
}
