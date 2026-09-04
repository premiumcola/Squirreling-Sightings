// ─── mediaview/live-detect-session.js ──────────────────────────────────────
// The detection poll loop as a PRODUCER you start and stop, with no DOM.
//
// WHY THIS EXISTS. The loop was only ever startable through
// `openLiveDetect()`, which seeds the session, mounts a whole legacy
// chrome into the shared #lightboxModal, and only then calls `_tick()`.
// When the unified player took the simulation over, `_cvOpenSim` began
// opening the new player and RETURNING — so nothing called
// `openLiveDetect` any more, nothing seeded a session, and nothing ever
// ticked. `vplayer/_data/live.js` dutifully subscribed to a loop that
// had never been started. The picture kept playing, because it is an
// independent MJPEG stream, so the surface looked alive while its panel
// sat on "Warte auf ersten Tick …" for ever. Measured before this
// module existed: 0 requests to /test-detection in three seconds.
//
// The consumer was migrated and the producer was not. This is the
// producer.
//
// ── What a headless start must include, and what it must not ──────────
//
// MUST: `_seedSession`. `_storeFrameState` writes `S.session.lastFrameSize`
// with no optional chaining, so a tick without a seeded session is a
// TypeError thrown BEFORE the observer fan-out — the new player would
// silently miss that frame, which looks exactly like the bug this fixes.
//
// MUST: `_startHoldRefresh`. It reads like a cosmetic bbox fade and is
// not: it carries `_checkStall`, the only CONTACT watchdog and the only
// path that re-kicks a wedged loop. Any cycle that ends without
// rescheduling — a response that outlived its session, an AbortError —
// stops the loop permanently and silently without it.
//
// MUST NOT: the legacy render fan-out. Those renderers do not throw when
// their chrome is absent, but they are not inert either: every tick
// would paint a base64 JPEG into the static #lightboxImg, create overlay
// SVGs inside #lightboxMediaWrap, overwrite #lightboxBottomStack (the
// RECORDED player's swimlane host, fingerprint and all) and pin
// `--play-pct: 1` on any .lb-time-stack in the document. All of that is
// the legacy player's furniture, and a headless session must not touch
// it. `_renderFrame` therefore branches on `session.headless`.
//
// MUST NOT: `closeLiveDetect()` as the stop. It is safe from throwing,
// but it calls `unmountLdSkeleton()`, which unconditionally re-appends
// #lightboxBottomStack and #lightboxSettings to #lightboxInner with no
// "did we ever move these" flag — permanently reordering nodes a
// headless session never touched, and pushing #lightboxMeta above the
// scrubber stack for the rest of the page session. The stop below is the
// two steps that actually stop things.

import { S } from './live-detect-state.js';
import { _seedSession } from './live-detect.js';
import { _tick } from './live-detect-poll.js';
import { _startHoldRefresh } from './live-detect-stall.js';
import { teardownVerdict } from './live-detect-verdict.js';

/** Is the loop currently owned by a headless producer? */
export function isHeadlessLiveSession() {
  return !!S.session?.headless;
}

/**
 * Stop whatever session is running, touching only this producer's own node.
 *
 * The one exception to "no DOM" is the verdict band, because this producer
 * is what puts it there: it is mounted into the PLAYER's panel slot, never
 * into the legacy chrome (live-detect-verdict.js refuses the legacy host
 * for a headless session), so removing it takes back exactly what this
 * module added and nothing else.
 *
 * These are the two steps of `closeLiveDetect` that do the stopping —
 * see this file's header for why the other five must not run here.
 * Nulling `S.session` is what makes every re-arm path in
 * live-detect-poll.js refuse: `_tick` bails, a late response is dropped,
 * and `_scheduleNext` will not re-arm.
 *
 * Safe to call twice, and safe to call when nothing is running.
 */
export function stopHeadlessLiveSession() {
  const session = S.session;
  S.session = null;
  // The ONE node this producer paints. It lives in the player's panel, so
  // a camera switch that keeps the player open must not leave the previous
  // camera's outage standing over the new one's numbers.
  teardownVerdict();
  S.traceLines = [];
  S.traceTicks = [];
  S.detBuffer = [];
  S.selectedLabel = null;
  if (!session) return;
  try {
    session.abort?.abort();
  } catch {
    /* an aborted controller that was already aborted */
  }
  if (session.tickHandle) clearTimeout(session.tickHandle);
  if (session.holdHandle) clearInterval(session.holdHandle);
}

/**
 * Start the poll loop for one camera, with no chrome.
 *
 * @param {{camId: string, cameraName?: string}} opts
 * @returns {boolean} false when there is nothing to start
 */
export function startHeadlessLiveSession({ camId, cameraName } = {}) {
  if (!camId) return false;
  // Whatever held the loop before — a legacy sim, or an earlier headless
  // open — loses it now. One loop, one owner: the session object IS the
  // ownership token every re-arm path compares against.
  const tornDownPrev = !!S.session;
  stopHeadlessLiveSession();
  _seedSession(camId, cameraName || camId, tornDownPrev);
  // Read by `_renderFrame` to skip the legacy fan-out. Set after the
  // seed, because the seed replaces the whole session object.
  S.session.headless = true;
  _tick();
  _startHoldRefresh();
  return true;
}
