// ─── mediaview/_live-detect-teardown.js ────────────────────────────────────
// Everything closeLiveDetect has to undo, in the order it has to undo it:
// module state, timers, the viewport lock, the shared modal's chrome, the
// nodes this session added, and finally the shell — after the media wrap has
// been returned to its DOM home, never before.
//
// Split out of live-detect.js, which now only orchestrates. openLiveDetect
// calls closeLiveDetect first, so it imports the name from here for real —
// a re-export would not bind it in that file's scope.
import { byId } from '../core/dom.js';
import { S } from './live-detect-state.js';
import { _hideStallBanner } from './live-detect-stall.js';
import { unmountLdSkeleton } from './live-detect-skeleton.js';
import { stopSnapshotPrefetch } from './live-detect-debug/index.js';

// Module state first, and unconditionally: a half-mounted open must still
// leave nothing behind for the next one to inherit.
// Q2-4 · the snapshot <img> holds a per-tick data: URL — drop it so
// the decoded frame is released when the session closes. (No HLS /
// MJPEG stream to tear down anymore — the view is snapshot-only.)
function _clearSessionState() {
  S.session = null;
  S.traceLines = [];
  S.traceTicks = [];
  S.detBuffer = [];
  S.selectedLabel = null;
  const imgEl = byId('lightboxImg');
  if (imgEl) imgEl.removeAttribute('src');
}

function _stopSessionTimers(session) {
  try {
    session.abort?.abort();
  } catch {
    /* ignore */
  }
  if (session.tickHandle) clearTimeout(session.tickHandle);
  if (session.holdHandle) clearInterval(session.holdHandle);
}

// SIMU-FIX-01c · restore the pre-mount overflow + height values
  // on body and <html> so a subsequent recorded-clip open behaves
// normally. Empty string clears the inline style, letting the
// page stylesheet take over.
function _restoreViewport(session) {
  if (typeof session.prevBodyOverflow === 'string') {
    document.body.style.overflow = session.prevBodyOverflow;
  }
  if (typeof session.prevHtmlOverflow === 'string') {
    document.documentElement.style.overflow = session.prevHtmlOverflow;
  }
  if (typeof session.prevBodyHeight === 'string') {
    document.body.style.height = session.prevBodyHeight;
  }
  if (typeof session.prevHtmlHeight === 'string') {
    document.documentElement.style.height = session.prevHtmlHeight;
  }
}

// Restore prev/next chevrons so a subsequent recorded-clip open
// gets its navigation arrows back. Confirm + Delete are restored
// by lightbox.js's own teardown when openLightbox() runs.
function _restoreModalChrome() {
  const modal = byId('lightboxModal');
  if (modal) modal.classList.remove('lb-live-detect');
  const prevBtn = byId('lightboxPrev');
  if (prevBtn) prevBtn.style.display = '';
  const nextBtn = byId('lightboxNext');
  if (nextBtn) nextBtn.style.display = '';
}

// Every node this session put on the shared modal, plus the widgets that
// registered document-level listeners of their own.
function _removeLiveNodes(session) {
  const overlay = byId('lightboxLiveOverlay');
  if (overlay) overlay.remove();
  const trails = byId('lightboxLiveTrails');
  if (trails) trails.remove();
  // L1 · tear down the shared overlay-toggle bar (its document
  // touch-dismiss listener) before removing the row node.
  try {
    session.overlayToggles?.teardown?.();
  } catch {
    /* ignore */
  }
  try {
    session.modeCost?.teardown?.();
  } catch {
    /* ignore */
  }
  const toggleRow = byId('mvLiveToggles');
  if (toggleRow) toggleRow.remove();
  const simControls = byId('mvSimControls');
  if (simControls) simControls.remove();
  const diagStrip = byId('mvSimDiagStrip');
  if (diagStrip) diagStrip.remove();
  const livePill = byId('mvLiveScrubPill');
  if (livePill) livePill.remove();
  // Q2-5 · drop the stall banner if a teardown happens while stalled.
  _hideStallBanner();
  // SIMU-FIX-05c · stop the debug-snapshot pre-fetch loop so it
  // doesn't keep hitting the closed session's camId.
  stopSnapshotPrefetch();
  // SIMU-01 · tear down the skeleton/tab system so #lightboxSettings +
  // #lightboxBottomStack are re-parented back to #lightboxInner before the
  // shell is removed (shell mode) or the 5-zone container goes (legacy).
  unmountLdSkeleton();
}

// F · restore the reparented media wrap to its DOM home, THEN drop the
// shell — the wrap (with the snapshot <img>) must leave the shell before
// the shell root is removed, or it'd be detached with it.
function _restoreShell(session) {
  if (session.wrapHome) {
    const wrap = byId('lightboxMediaWrap');
    if (wrap) {
      try {
        session.wrapHome.parent?.insertBefore(wrap, session.wrapHome.next || null);
      } catch {
        /* ignore */
      }
    }
  }
  try {
    session.shell?.teardown();
  } catch {
    /* ignore */
  }
}

export function closeLiveDetect() {
  const session = S.session;
  _clearSessionState();
  if (!session) return;
  _stopSessionTimers(session);
  _restoreViewport(session);
  _restoreModalChrome();
  _removeLiveNodes(session);
  _restoreShell(session);
}
