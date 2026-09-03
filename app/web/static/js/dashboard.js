// ─── dashboard.js ──────────────────────────────────────────────────────────
// Stage 3a of the legacy.js → ES modules refactor — pure dashboard
// helpers that have no external behavioural dependency on the rest of
// the legacy file. Each function is referenced only by other dashboard
// code (renderDashboard, showCameraReloadAnimation, the live-update
// poll) which still lives in legacy.js for now; once those move out
// in stage 3b, this module becomes the single home for the camera-tile
// feature surface.
//
// Nothing in here mutates state.cameras or other global stores —
// they're all stateless rendering helpers, the dead-id snapshot poll
// suppression Map, and the surveil-mode classification. The legacy
// bridge for window._camImgRetry stays so inline onclick handlers in
// renderDashboard's template strings (onerror="_camImgRetry(this)")
// keep resolving.
import { state } from './core/state.js';
import { byId, esc } from './core/dom.js';
import { j, apiPost } from './core/api.js';
import { getCameraIcon, getCameraColor, OBJ_LABEL } from './core/icons.js';
import { isIOS } from './core/ios-video.js';
import { openLiveViewIosNative } from './chrome/live-view.js';
import { initNetPanels } from './netz/index.js';
import { isTuneDragging } from './netz/_tune_drag.js';

// ── Snapshot polling — moved to dashboard/snapshot-poll.js (N15) ───────────
// Re-export every name so existing imports of these from '../dashboard.js'
// resolve unchanged; window.* bridges below carry the inline-onclick path.
export {
  _failedSnapshotIds,
  _resetFailedSnapshotIds,
  _isSnapshotIdDead,
  _camIdFromImg,
  _camImgRetry,
  _cvImgLoaded,
} from './dashboard/snapshot-poll.js';
import {
  _camIdFromImg,
  _isSnapshotIdDead,
  _camImgRetry as _camImgRetryFn,
  _cvImgLoaded as _cvImgLoadedFn,
} from './dashboard/snapshot-poll.js';
window._camImgRetry = _camImgRetryFn;
window._cvImgLoaded = _cvImgLoadedFn;

// SURVEIL_ACC / SURVEIL_LABEL / _surveilMode / _surveilEyeSvg went with
// the `.cv-surveil` bottom-overlay they described: no renderer in this
// repo ever emits that markup (only live-update.js and camedit's
// _flashDetection still QUERY for `.cv-surveil-tgt`, and both find
// nothing), and nothing imported the four symbols.

// ── Camera-tile placeholders ───────────────────────────────────────────────
// Moved to dashboard/_placeholders.js. Re-exported so existing importers
// of these names from '../dashboard.js' resolve unchanged; a re-export
// alone does NOT bind the names in this file, so the ones used locally
// (renderDashboard, showCameraReloadAnimation) are imported for real
// below.
export {
  _makeOfflinePlaceholder,
  _makeConnectingPlaceholder,
  _restorePlaceholder,
} from './dashboard/_placeholders.js';
import {
  _makeOfflinePlaceholder as _makeOfflinePlaceholderFn,
  _makeConnectingPlaceholder as _makeConnectingPlaceholderFn,
  _restorePlaceholder as _restorePlaceholderFn,
} from './dashboard/_placeholders.js';

// ── E2 · adaptive overlay palette ──────────────────────────────────────────
// Moved to dashboard/_bg-luminance.js. Only main.js's boot path calls
// this, via loadAll(), so a plain re-export is enough — nothing in this
// file uses it locally.
export { startBgLuminanceMonitor } from './dashboard/_bg-luminance.js';

// ── Stage 3b — dashboard rendering + live state ────────────────────────────
// HD-stream toggle state. _hdCards holds camera ids whose tile is
// currently showing the high-bitrate stream_hd.mjpg endpoint instead of
// the 5 fps snapshot.jpg cycle. Lives at module scope so the live-pill
// refresh and the preview-refresh loop see the same set.
export const _hdCards = new Set();
let _previewRefreshInterval = null;

// 5 fps preview-refresh interval. While the tab is foreground, every
// 200 ms each visible non-HD .cv-img gets its src timestamp bumped so
// the browser fetches a fresh snapshot.jpg. HD tiles refresh themselves
// via the MJPEG stream and are skipped. Dead post-rename ids
// (_isSnapshotIdDead) are skipped too, suppressing the post-rename
// 404 storm we saw earlier in the session.
export function startPreviewRefresh() {
  if (_previewRefreshInterval) clearInterval(_previewRefreshInterval);
  _previewRefreshInterval = setInterval(() => {
    if (document.hidden) return;
    const grid = byId('cameraCards');
    if (!grid) return;
    grid.querySelectorAll('.cv-img.loaded').forEach((img) => {
      if (img.dataset.hdMode === '1') return;
      const camId = _camIdFromImg(img);
      if (_isSnapshotIdDead(camId)) return;
      const base = img.src.split('?')[0];
      img.src = base + '?t=' + Date.now();
    });
  }, 200);
}

// HD-stream toggle on the cv-cog area's HD button. Flips the cv-img
// element between snapshot.jpg cache-busted polling and the live
// stream_hd.mjpg endpoint, then asks the live-pill to repaint so the
// "Stream-Modus" line reflects the new state without waiting for the
// next 3 s status poll.
//
// Also arms (or clears) the 10-min idle timer for that camera —
// cm-52 task #5c keeps HD from running indefinitely when the user
// walks away from the tab. Toggling OFF clears the timer; toggling
// ON arms a fresh 10-min countdown. Manual interaction with the tile
// (click on any of HD/FS/SIM/cog, hover on desktop) resets the
// countdown via the grid-level pointerdown listener installed below.
export function toggleCardHd(camId, btn) {
  const card = btn.closest('.cv-card');
  const img = card?.querySelector('.cv-img');
  if (!img) return;
  if (_hdCards.has(camId)) {
    _hdCards.delete(camId);
    btn.classList.remove('active');
    img.dataset.hdMode = '0';
    img.src = `/api/camera/${encodeURIComponent(camId)}/snapshot.jpg?t=${Date.now()}`;
    _clearHdIdleTimer(camId);
  } else {
    _hdCards.add(camId);
    btn.classList.add('active');
    img.dataset.hdMode = '1';
    img.src = `/api/camera/${encodeURIComponent(camId)}/stream_hd.mjpg`;
    _armHdIdleTimer(camId);
  }
  _refreshLivePillForCard(camId);
}

// ── HD idle timeout (cm-52 task #5c) ────────────────────────────────────
// Per-tile setTimeout that flips HD → SD after _HD_IDLE_TIMEOUT_MS of
// no interaction. Quiet — just the stream switches and the HD button
// visual de-activates. Tab-visibility suspends/resumes the countdown
// so a backgrounded tab doesn't burn through the timer in silence.
// jt719 — HD auto-revert. The previous 10-min timer was effectively
// "never" for the kind of peek-at-HD-and-walk-away pattern users
// actually hit. 120 s is the new default: long enough for an active
// inspection, short enough that a forgotten HD stream stops eating
// CPU + bandwidth quickly. Any interaction with the tile resets the
// countdown; the visual ring under the badge shrinks from full to
// zero over the same duration so the user sees the timer instead of
// being surprised when HD flips back to SD.
const _HD_IDLE_TIMEOUT_MS = 120 * 1000;
const _hdIdleTimers = new Map(); // camId → { handle, deadline, paused, remaining }

function _refreshHdRing(_camId) {
  // J1 · the visual countdown bar (jt719) was removed because it
  // read as a rendering artefact on iPhone. The 120 s auto-revert
  // timer still fires via _armHdIdleTimer below; this function is
  // kept as a no-op so existing call sites stay valid without
  // pulling apart the timer-arm flow. _hdDur + data-hd-running
  // stamps are gone too — the DOM no longer carries inert state.
}

function _armHdIdleTimer(camId) {
  _clearHdIdleTimer(camId);
  _refreshHdRing(camId);
  if (document.hidden) {
    // jt719 — was "pause until tab visible". New spec: revert
    // immediately. Backgrounding the tab is a strong "I'm done
    // looking at this" signal; carrying HD across an unbounded
    // hidden period wastes bandwidth for no user benefit.
    _onHdIdleTimeout(camId);
    return;
  }
  const deadline = Date.now() + _HD_IDLE_TIMEOUT_MS;
  const handle = setTimeout(() => _onHdIdleTimeout(camId), _HD_IDLE_TIMEOUT_MS);
  _hdIdleTimers.set(camId, {
    handle,
    deadline,
    paused: false,
    remaining: _HD_IDLE_TIMEOUT_MS,
  });
}

function _clearHdIdleTimer(camId) {
  const entry = _hdIdleTimers.get(camId);
  if (!entry) return;
  if (entry.handle) clearTimeout(entry.handle);
  _hdIdleTimers.delete(camId);
}

function _onHdIdleTimeout(camId) {
  _hdIdleTimers.delete(camId);
  if (!_hdCards.has(camId)) return;
  const card = byId('cameraCards')?.querySelector(`[data-camid="${CSS.escape(camId)}"]`);
  const hdBtn = card?.querySelector('.cv-hd-badge');
  if (hdBtn) toggleCardHd(camId, hdBtn);
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) return;
  // jt719 — backgrounded tab → revert every active HD session.
  // Spec: "When the tab becomes visible again, resume on sub
  // unless the user explicitly re-clicks HD." Auto-revert handles
  // the "resume on sub" part by switching the stream now; the
  // re-click requirement falls out for free because nothing
  // re-arms automatically.
  for (const camId of Array.from(_hdCards)) {
    _onHdIdleTimeout(camId);
  }
});

// Grid-level pointerdown listener — installed once. Resets the HD idle
// timer on any user-initiated press inside an HD-active tile (HD/FS/
// SIM/cog buttons, or even a tap on the inert tile body). Re-armed
// listener survives renderDashboard's innerHTML rebuilds because it's
// bound to the parent #cameraCards element.
let _hdIdleWired = false;
function _wireHdIdleReset() {
  if (_hdIdleWired) return;
  const grid = byId('cameraCards');
  if (!grid) return;
  const reset = (e) => {
    const card = e.target.closest('.cv-card[data-camid]');
    if (!card) return;
    const camId = card.dataset.camid;
    if (_hdCards.has(camId)) _armHdIdleTimer(camId);
  };
  grid.addEventListener('pointerdown', reset, { passive: true });
  if (window.matchMedia && window.matchMedia('(hover:hover)').matches) {
    // Desktop hover resets too — match the prompt's "any interaction"
    // intent. Touch devices skip this so a stray hover-emulation
    // event on iOS doesn't fight with the pointerdown reset.
    grid.addEventListener('pointerenter', reset, { passive: true, capture: true });
  }
  _hdIdleWired = true;
}

// Re-paint the expanded LivePill row values for one card based on
// current HD state. Used by both toggleCardHd() and the 3 s polling
// loop in legacy.js so the pill never shows sub-stream values while
// HD-Stream is active.
export function _refreshLivePillForCard(camId) {
  const card = byId('cameraCards')?.querySelector(`[data-camid="${CSS.escape(camId)}"]`);
  if (!card) return;
  const livePill = card.querySelector('.cv-pill-live-wrap');
  if (!livePill) return;
  const c = (state.cameras || []).find((x) => x.id === camId) || {};
  const hdOn = _hdCards.has(camId);
  const modeEl = livePill.querySelector('.cv-stream-mode');
  if (modeEl) {
    if (hdOn) {
      modeEl.textContent = '● HD-Stream';
      modeEl.className = 'cv-stream-mode cv-mode-hd';
    } else {
      const mode = c.stream_mode || 'baseline';
      modeEl.textContent = mode === 'live' ? '● Live' : '○ Vorschau';
      modeEl.className = 'cv-stream-mode ' + (mode === 'live' ? 'cv-mode-live' : 'cv-mode-base');
    }
  }
  const fpsEl = livePill.querySelector('.cv-lp-fps-val');
  if (fpsEl)
    fpsEl.textContent = hdOn ? '—' : (c.preview_fps || 0) > 0 ? c.preview_fps + ' fps' : '—';
  const fpsSubEl = livePill.querySelector('.cv-lp-fps-sub');
  if (fpsSubEl) fpsSubEl.textContent = hdOn ? 'Main-Stream aktiv' : 'Gemessen (Sub-Stream)';
  const resEl = livePill.querySelector('.cv-lp-res-val');
  if (resEl) resEl.textContent = hdOn ? 'Main-Stream' : c.preview_resolution || c.resolution || '—';
}

// cm-52: the tile body is inert — the article-level onclick was
// dropped (task 2 of the dashboard restructure). Each tile carries
// three explicit buttons: HD (inline with title), FS (top-right),
// SIM (bottom-right). The legacy openLiveView modal stays available
// as window.openLiveView for any external caller; the dashboard
// itself no longer reaches for it.
//
// ── FS button — native fullscreen on the tile's .cv-img-wrap ────────────
// Reuses the requestFullscreen + .fake-fullscreen pattern that
// chrome/fullscreen.js + chrome/live-view.js already exercise for
// the legacy modal, retargeted at the per-tile media wrap.
//
// _hdAtFsEntry snapshots which cameras had HD on at FS-enter so the
// fullscreenchange exit handler can tell "user turned HD on inside
// FS" (drop back to SD) from "HD was on before FS started" (leave it).
const _hdAtFsEntry = new Set();

export function _cvEnterFullscreen(camId) {
  const card = byId('cameraCards')?.querySelector(`[data-camid="${CSS.escape(camId)}"]`);
  const wrap = card?.querySelector('.cv-img-wrap');
  if (!wrap) return;
  // P1 · iOS-only path. openLiveViewIosNative keeps the app's live
  // modal entirely hidden — only a minimal Matrix-mono loading
  // overlay shows while HLS warms up, then the native iOS system
  // player takes over via webkitEnterFullscreen. Dismissing the
  // native player returns straight to the all-cams home (no app
  // modal chrome is rendered at any point on iOS). Desktop falls
  // through to the wrap-level requestFullscreen + .fake-fullscreen
  // fallback below.
  if (isIOS) {
    openLiveViewIosNative(camId);
    return;
  }
  // Snapshot HD state at FS-enter — drives the auto-drop rule below.
  if (_hdCards.has(camId)) _hdAtFsEntry.add(camId);
  else _hdAtFsEntry.delete(camId);
  const req = wrap.requestFullscreen || wrap.webkitRequestFullscreen || wrap.mozRequestFullScreen;
  if (req) {
    // J3.a · stamp `is-fs` IMMEDIATELY on the success path instead
    // of waiting for the fullscreenchange event to fire. On Chrome
    // / Safari Desktop the event can land late (or, on some Edge
    // builds, after a higher-specificity :fullscreen UA rule has
    // already painted the wrong icon). The fullscreenchange handler
    // below is idempotent — toggling here just makes the swap fire
    // at the same instant the browser enters FS rather than one
    // event-loop turn later. The CSS in 03-dashboard.css also
    // mirrors via the :fullscreen pseudo-class so this is belt +
    // suspenders.
    req
      .call(wrap)
      .then(() => wrap.classList.add('is-fs'))
      .catch(() => {
        wrap.classList.add('fake-fullscreen');
        wrap.classList.add('is-fs');
      });
  } else {
    wrap.classList.add('fake-fullscreen');
    wrap.classList.add('is-fs');
  }
  // .fake-fullscreen has its own dismiss path — tap-outside the
  // wrap returns to normal. The native API exits via Esc / browser
  // controls / iOS swipe.
  if (wrap.classList.contains('fake-fullscreen')) {
    const dismiss = (ev) => {
      if (!wrap.contains(ev.target)) {
        wrap.classList.remove('fake-fullscreen');
        wrap.classList.remove('is-fs');
        document.removeEventListener('keydown', escDismiss);
        document.removeEventListener('click', dismiss, true);
        _runHdDropOnFsExit();
      }
    };
    const escDismiss = (ev) => {
      if (ev.key === 'Escape') {
        wrap.classList.remove('fake-fullscreen');
        wrap.classList.remove('is-fs');
        document.removeEventListener('keydown', escDismiss);
        document.removeEventListener('click', dismiss, true);
        _runHdDropOnFsExit();
      }
    };
    setTimeout(() => {
      document.addEventListener('click', dismiss, true);
      document.addEventListener('keydown', escDismiss);
    }, 0);
  }
}

// Drop HD on tiles whose FS session involved a user-initiated HD
// toggle. Walks every visible cv-card so the rule applies whether
// FS ended via the native API, the .fake-fullscreen dismiss path, or
// a user navigation. Quiet — no toast, just the stream and the HD
// button visual flip back. Used by both fullscreenchange + the
// fake-fullscreen click/Esc handlers above.
function _runHdDropOnFsExit() {
  // jt719 — was "drop HD only if the user turned it on DURING
  // fullscreen". New spec: always drop HD on FS exit. Leaving FS
  // is a strong "done with this view" signal; the user can re-
  // click HD if they really want it back on the dashboard tile.
  const grid = byId('cameraCards');
  if (!grid) return;
  grid.querySelectorAll('.cv-card[data-camid]').forEach((card) => {
    const camId = card.dataset.camid;
    if (!_hdCards.has(camId)) return;
    const hdBtn = card.querySelector('.cv-hd-badge');
    if (hdBtn) toggleCardHd(camId, hdBtn);
  });
  _hdAtFsEntry.clear();
}

function _onFullscreenChange() {
  const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
  // .is-fs drives the FS-button icon swap (task mx918) and any other
  // chrome that needs to know "this wrap is the FS target right now".
  // Walk every wrap on the page so stale .is-fs from a previous exit
  // can't linger after a navigation.
  document.querySelectorAll('.cv-img-wrap').forEach((w) => {
    w.classList.toggle('is-fs', w === fsEl || w.classList.contains('fake-fullscreen'));
  });
  if (fsEl) return; // entered (or transitioning into) FS — wait for exit.
  // Exited fullscreen — defensive cleanup + auto-drop HD per cm-52 task #5b.
  document.querySelectorAll('.cv-img-wrap.fake-fullscreen').forEach((w) => {
    w.classList.remove('fake-fullscreen');
    w.classList.remove('is-fs');
  });
  _runHdDropOnFsExit();
}
document.addEventListener('fullscreenchange', _onFullscreenChange);
document.addEventListener('webkitfullscreenchange', _onFullscreenChange);

window._cvEnterFullscreen = _cvEnterFullscreen;

// jh742 — second click on the FS button must exit FS. The previous
// wiring only ever called _cvEnterFullscreen, so the icon flipped to
// the minimize-pattern (driven by .is-fs on the wrap) but clicking
/**
 * Expand a camera tile onto the unified player.
 *
 * Per the mockup, Live is Simulation with the detection panel and the
 * overlays hidden — one controller, configured differently, rather than
 * a second one. The picture is the same MJPEG stream the tile shows, so
 * expanding is genuinely "the same thing, bigger".
 *
 * The iOS handoff is preserved and its silent failure is fixed on the
 * way past: openLiveViewIosNative returns FALSE when the browser has no
 * webkitEnterFullscreen, and the old call site ignored that return — so
 * on such a browser the arrow did nothing at all, with no feedback.
 * Here a false return falls through to our own player.
 */
function _cvOpenLive(camId) {
  // The tile button is a toggle: a second tap closes what the first
  // opened, the way the fullscreen path behaved.
  if (isVideoPlayerOpen()) {
    closeVideoPlayer();
    return;
  }
  if (isIOS && openLiveViewIosNative(camId)) return;
  const cam = (state.cameras || []).find((c) => c.id === camId);
  openVideoPlayer({
    mode: 'live',
    camId,
    cameraName: cam?.name || camId,
    source: {
      type: 'mjpeg',
      url: `/api/camera/${encodeURIComponent(camId)}/stream_hd.mjpg`,
      frameSize:
        cam?.main_w && cam?.main_h ? { w: cam.main_w, h: cam.main_h } : { w: 1920, h: 1080 },
    },
  });
}

// it did nothing. _cvToggleFullscreen branches: if the wrap is in
// real or fake fullscreen, exit; otherwise enter via the existing
// helper. The fake-fullscreen exit path mirrors the dismiss/escape
// handlers that _cvEnterFullscreen installs on iOS so HD drops and
// classes are cleaned up the same way.
function _cvToggleFullscreen(camId) {
  if (vplayerEnabled('live')) {
    _cvOpenLive(camId);
    return;
  }
  const card = byId('cameraCards')?.querySelector(`[data-camid="${CSS.escape(camId)}"]`);
  const wrap = card?.querySelector('.cv-img-wrap');
  if (!wrap) return;
  const inFs =
    wrap.classList.contains('is-fs') ||
    document.fullscreenElement === wrap ||
    document.webkitFullscreenElement === wrap;
  if (inFs) {
    if (wrap.classList.contains('fake-fullscreen')) {
      wrap.classList.remove('fake-fullscreen');
      wrap.classList.remove('is-fs');
      _runHdDropOnFsExit();
    } else if (document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    } else if (document.webkitExitFullscreen) {
      document.webkitExitFullscreen();
    }
    return;
  }
  _cvEnterFullscreen(camId);
}
window._cvToggleFullscreen = _cvToggleFullscreen;

// ── SIM button — open MediaView in live-detect mode for this camera ─────
// Routes to the unified MediaView shell so the user sees the SAME
// chrome as a recorded clip (lb-fs-video top bar, 16:9 wrap, panel-
// tabs strip, fine-analysis fold OPEN by default), driven by the
// 1 Hz test-detection polling implemented in mediaview/live-detect.js.
// Prev/next nav + confirm/delete/download actions are nulled — live
// mode has no recorded-item navigation surface.
import { openMediaView } from './mediaview/index.js';
import { vplayerEnabled } from './vplayer/_flag.js';
import { closeVideoPlayer, isVideoPlayerOpen, openVideoPlayer } from './vplayer/index.js';

export function _cvOpenSim(camId) {
  const cam = (state.cameras || []).find((c) => c.id === camId);
  if (!cam) return;
  try {
    // Simulation is the first surface onto the unified player: one
    // entry point, no prev/next, no delete or confirm semantics, no
    // deep links, and it already owns the snapshot transport — so
    // nothing new has to be plumbed to try it. With the flag off the
    // call below runs exactly as it always has.
    if (vplayerEnabled('sim')) {
      openVideoPlayer({
        mode: 'sim',
        camId,
        cameraName: cam.name || camId,
        source: {
          type: 'mjpeg',
          url: `/api/camera/${encodeURIComponent(camId)}/stream_hd.mjpg`,
          frameSize:
            cam.main_w && cam.main_h ? { w: cam.main_w, h: cam.main_h } : { w: 1920, h: 1080 },
        },
      });
      return;
    }
    openMediaView({
      mode: 'live-detect',
      source: {
        type: 'mjpeg',
        url: `/api/camera/${encodeURIComponent(camId)}/stream_hd.mjpg`,
        frameSize:
          cam.main_w && cam.main_h ? { w: cam.main_w, h: cam.main_h } : { w: 1920, h: 1080 },
      },
      item: {
        camera_id: camId,
        camera_name: cam.name || camId,
      },
      actions: {
        onClose: () => {}, // shell handles its own teardown via closeLightbox
        onPrev: null,
        onNext: null,
        onConfirm: null,
        onDelete: null,
        onDownload: null,
      },
    });
  } catch (err) {
    // Diagnostic only — surface a quiet toast via the window bridge
    // so a missing showToast import (the module-level binding isn't
    // pulled in here) doesn't ReferenceError the SIM button.
    window.showToast?.(`Live-Erkennung fehlgeschlagen: ${err?.message || err}`, 'error');
  }
}
window._cvOpenSim = _cvOpenSim;

// zg531 — currentColor SVG glyphs for the bottom-left class pills.
// ── Tile chrome + notification-channel cluster ─────────────────────────────
// Moved to dashboard/_tile-chrome.js. _isInScheduleWindow went with it —
// _channelState is its only caller, and leaving it here would have made
// the two modules import each other. Re-exported for outside importers;
// the names renderDashboard uses are imported for real below, since a
// re-export does not bind them in this file.
export { _isInScheduleWindow } from './dashboard/_tile-chrome.js';
import {
  _chromeClassSvg,
  _channelState,
  _channelCluster,
  _CHROME_COG_SVG,
  _CHROME_SIM_SVG,
  _CHROME_EXPAND_SVG,
  _CHROME_MINIMIZE_SVG,
} from './dashboard/_tile-chrome.js';

// Camera-tile grid renderer. Builds every visible cv-card from
// state.cameras. The template string carries inline onclick handlers
// (_cvCardClick / toggleCardHd / editCamera / _camImgRetry); each name
// is reachable on window via the bridge block at the bottom of this
// module + the window.editCamera bridge that still lives in legacy.js.
export function renderDashboard() {
  // A radar drag (netz/_tune_drag.js) sets a pointer capture on an SVG
  // node inside a .cam-net-slot; the innerHTML rebuild below would tear
  // that node out from under the finger and strand the drag. The poll
  // that drives most renderDashboard() calls fires every 3 s, comfortably
  // longer than any real drag — skipping this one tick and picking the
  // camera-tile refresh back up on the next is the same trade the resize
  // handler in netz/index.js already makes.
  if (isTuneDragging()) return;
  const cams = state.cameras;
  const grid = byId('cameraCards');
  // Each camera's Erkennungsprofil panel (netz/_panel.js) lives in the
  // slot right after its tile, but OUTSIDE the render cycle below — it
  // repaints only on its own interactions, never as a side effect of the
  // 3 s camera-tile poll (an open Verlauf list or a staged-but-not-saved
  // value must survive a poll tick untouched). Since the innerHTML reset
  // below detaches every child regardless, existing slots are captured
  // here and spliced back into their freshly-templated replacement so
  // their content survives the rebuild.
  const savedSlots = new Map();
  grid.querySelectorAll('.cam-net-slot').forEach((slot) => {
    if (slot.firstElementChild) savedSlots.set(slot.dataset.camid, slot);
  });
  grid.className = 'camera-grid';
  grid.innerHTML = cams
    .map((c) => {
      const hdOn = _hdCards.has(c.id);
      const snapUrl = hdOn
        ? `/api/camera/${esc(c.id)}/stream_hd.mjpg`
        : `/api/camera/${esc(c.id)}/snapshot.jpg?t=${Date.now()}`;
      const isActive = c.status === 'active';
      const fps = c.frame_interval_ms ? Math.round(1000 / c.frame_interval_ms) : null;
      const previewFps = (c.preview_fps || 0) > 0 ? c.preview_fps : null;
      const streamMode = c.stream_mode || 'baseline';
      // Class-filter pills (object_filter list). class_severity === "off"
      // renders the pill muted (opacity .38, no tint). After B3, these
      // sit in the bottom-right cluster alongside the new Telegram /
      // MQTT pills and the Simulieren / cog buttons.
      const _clsSev = c.class_severity || {};
      const _classPills = (c.object_filter || [])
        .map((cls) => {
          const muted = _clsSev[cls] === 'off';
          const lbl = OBJ_LABEL[cls] || cls;
          return (
            `<span class="cv-class-pill" data-cls="${esc(cls)}"` +
            (muted ? ' data-state="muted"' : '') +
            ` style="color:var(--class-${esc(cls)})"` +
            ` title="${esc(lbl)}${muted ? ' — stumm' : ''}">` +
            `${_chromeClassSvg(cls)}</span>`
          );
        })
        .join('');
      // Telegram + MQTT channel pills. Both render as expandable
      // Live-pill clones (see _channelPill) — pulsing dot + label +
      // chevron, click to expand. The schedule window that used to
      // float above as a separate label now lives inside the pill's
      // detail panel (B3 — see Alarmfenster row in _channelPill).
      const _chanState = _channelState(c);
      const _tgBadge = c.telegram_enabled ? _channelCluster(c, 'tg', _chanState) : '';
      const _mqttBadge = c.mqtt_enabled ? _channelCluster(c, 'mqtt', _chanState) : '';
      // Live-pill collapsed body — extracted as a local so the v17
      // top-left zone can stack it under the camera name without
      // duplicating the detail-panel template. Hidden entirely while
      // the camera isn't active (E1 spec: only icon + name remain).
      const _livePill = isActive
        ? `<div class="cv-pill-live-wrap cv-live-active">
            <span class="cv-pdot"></span>
            <span class="cv-live-label">Live</span>
            ${previewFps ? `<span class="cv-live-fps">${previewFps} fps</span>` : ''}
            <svg class="cv-live-arrow" width="8" height="8" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 4.5l3 3 3-3"/></svg>
            <div class="cv-live-detail">
              <div class="cv-live-detail-header">
                <span class="cv-pdot"></span>
                <span>Livestream aktiv</span>
              </div>
              <div class="cv-lp-row"><span>Stream-Modus</span><strong class="cv-stream-mode ${hdOn ? 'cv-mode-hd' : streamMode === 'live' ? 'cv-mode-live' : 'cv-mode-base'}">${hdOn ? '● HD-Stream' : streamMode === 'live' ? '● Live' : '○ Vorschau'}</strong></div>
              <div class="cv-lp-row"><span>Preview-FPS</span><strong class="cv-lp-fps-val">${previewFps != null ? previewFps + ' fps' : '—'}</strong></div>
              <div class="cv-lp-row"><span>Auflösung</span><strong class="cv-lp-res-val">${hdOn ? esc(c.main_resolution || c.preview_resolution || c.resolution || '—') : esc(c.preview_resolution || c.resolution || '—')}</strong></div>
              <div class="cv-lp-row"><span>Analyse-Framerate</span><strong>${fps != null ? fps + ' fps' : '—'}</strong></div>
            </div>
          </div>`
        : '';
      return `<article class="cv-card${c.armed ? '' : ' cv-card--muted'}" data-camid="${esc(c.id)}" data-cam-name="${esc(c.name || c.id)}">
  <div class="cv-frame">
    <div class="cv-img-wrap">
      <div class="cv-loading-placeholder">${isActive ? _makeConnectingPlaceholderFn() : _makeOfflinePlaceholderFn()}</div>
      <img class="cv-img cam-snap" src="${snapUrl}" alt="${esc(c.name)}" data-hd-mode="${hdOn ? '1' : '0'}"
        onload="_cvImgLoaded(this)"
        onerror="_camImgRetry(this)" />
      <div class="cv-grad-bot"></div>
      <div class="cv-chrome-top-left cv-overlay-region" data-region="identity" data-bg="dark">
        <span class="cv-cam-title-icon" aria-hidden="true" style="--cam-color:${getCameraColor(c)}">${getCameraIcon(c.name)}</span>
        <div class="cv-tl-stack">
          <div class="cv-name">${esc(c.name)}</div>
          ${_livePill}
        </div>
      </div>
${
  isActive
    ? `
      <div class="cv-chrome-top-right">
        ${c.rtsp_url ? `<button class="cv-chrome-btn cv-hd-badge has-text${hdOn ? ' active' : ''}" type="button" data-cam="${esc(c.id)}" onclick="event.stopPropagation();toggleCardHd('${esc(c.id)}',this)" title="HD-Vorschau" aria-label="HD-Vorschau ein/aus">HD</button>` : ''}
        ${c.rtsp_url ? `<button class="cv-chrome-btn cv-fs-btn" type="button" data-cam="${esc(c.id)}" onclick="event.stopPropagation();window._cvToggleFullscreen && window._cvToggleFullscreen('${esc(c.id)}')" title="Vollbild" aria-label="Vollbild"><span class="fs-icon-expand">${_CHROME_EXPAND_SVG}</span><span class="fs-icon-minimize">${_CHROME_MINIMIZE_SVG}</span></button>` : ''}
      </div>
      <div class="cv-chrome-bottom-left">
        ${_tgBadge || _mqttBadge ? `<div class="cv-channel-row cv-overlay-region" data-region="telegram" data-bg="dark">${_tgBadge}${_mqttBadge}</div>` : ''}
        ${_classPills ? `<div class="cv-class-cluster cv-overlay-region" data-region="classicons" data-bg="dark">${_classPills}</div>` : ''}
      </div>
      <div class="cv-chrome-bottom-right">
        ${c.rtsp_url ? `<button class="cv-chrome-btn cv-sim-btn has-text" type="button" data-cam="${esc(c.id)}" onclick="event.stopPropagation();window._cvOpenSim && window._cvOpenSim('${esc(c.id)}')" title="Erkennung jetzt simulieren" aria-label="Simulieren">${_CHROME_SIM_SVG}<span class="cv-sim-full">Simulieren</span><span class="cv-sim-abbr" aria-hidden="true">SIM</span></button>` : ''}
        <button class="cv-chrome-btn cv-cog" type="button" onclick="event.stopPropagation();editCamera('${esc(c.id)}')" title="Einstellungen" aria-label="Einstellungen">${_CHROME_COG_SVG}</button>
      </div>
`
    : ''
}
    </div>
  </div>
</article><div class="cam-net-slot" data-camid="${esc(c.id)}"></div>`;
    })
    .join('');
  // Splice preserved panel DOM back into its camera's fresh (empty) slot.
  // A camera that is new this render (or whose panel hasn't mounted yet)
  // simply keeps the empty placeholder — netz/_panel.js fills those in.
  grid.querySelectorAll('.cam-net-slot').forEach((slot) => {
    const saved = savedSlots.get(slot.dataset.camid);
    if (saved) slot.replaceWith(saved);
  });
  // Wire the live-pill hover/touch open/close per card (one set of
  // listeners per render; innerHTML wipes prior listeners). The
  // touch-outside handler closes any open pill when the user taps
  // somewhere else on the page.
  // One-shot wiring of the HD idle-timer reset listener (cm-52
  // task #5c). The listener attaches to the parent grid element so
  // it survives the innerHTML rebuild above; the wired-flag inside
  // the helper prevents double-binding across re-renders.
  _wireHdIdleReset();
  _wirePillOpenClose();
  // Mount/refresh the Erkennungsprofil panels for whatever camera list
  // just rendered. Cheap on repeat calls (see initNetPanels' own doc) —
  // fire-and-forget so a slow /api/netz/state fetch never blocks the
  // camera-tile paint above.
  initNetPanels();
}

// Open/close wiring for every expandable pill on the dashboard —
// Live-pill + Telegram pill + MQTT pill share the .cv-lp-open class
// and the same click pattern. Delegated via #cameraCards so the
// listener survives renderDashboard's innerHTML rebuilds; the
// _pillWired flag (same idea as _hdIdleWired above) means we only
// bind once per page lifetime. Only ONE pill per tile may be open at
// a time — opening a new pill closes any open sibling in the same
// card (B3 spec: "if Telegram is open and the user clicks Live,
// Telegram collapses first"). A document-level outside-click handler
// closes every open pill when the user taps elsewhere; same
// wire-once guard.
const _PILL_SELECTOR = '.cv-pill-live-wrap';
let _pillWired = false;
function _wirePillOpenClose() {
  if (_pillWired) return;
  const grid = byId('cameraCards');
  if (!grid) return;
  const togglePill = (el) => {
    const wasOpen = el.classList.contains('cv-lp-open');
    const card = el.closest('.cv-card');
    if (card)
      card.querySelectorAll('.cv-lp-open').forEach((other) => {
        if (other !== el) other.classList.remove('cv-lp-open');
      });
    el.classList.toggle('cv-lp-open', !wasOpen);
  };
  grid.addEventListener('click', (e) => {
    const pill = e.target.closest(_PILL_SELECTOR);
    if (!pill || !grid.contains(pill)) return;
    e.stopPropagation();
    togglePill(pill);
  });
  const closeAllOutside = (e) => {
    if (e.target.closest(_PILL_SELECTOR)) return;
    document.querySelectorAll('.cv-lp-open').forEach((p) => p.classList.remove('cv-lp-open'));
  };
  document.addEventListener('click', closeAllOutside);
  document.addEventListener('touchstart', closeAllOutside, { passive: true });
  _pillWired = true;
}

// Reload-state animation. Either targets a single camera by id (after
// a "Verbinden" click on a row, after a save that triggered a runtime
// rebuild) or every visible tile (after a global reload). Polls
// /api/cameras every 2 s up to 15 attempts, swapping the placeholder
// to the blue VERBINDE… while waiting and re-rendering on the first
// status==='active' return.
export function showCameraReloadAnimation(camId) {
  const cameraCards = byId('cameraCards');
  // Scoped to .cv-card: #cameraCards also holds a same-camId
  // .cam-net-slot sibling per tile (the Erkennungsprofil panel), which
  // has no .cv-loading-placeholder/.cv-img of its own to animate.
  const cards = camId
    ? [cameraCards?.querySelector(`.cv-card[data-camid="${CSS.escape(camId)}"]`)]
    : [...(cameraCards?.querySelectorAll('.cv-card[data-camid]') || [])];
  cards.filter(Boolean).forEach((card) => {
    const placeholder = card.querySelector('.cv-loading-placeholder');
    const img = card.querySelector('.cv-img');
    if (placeholder && !placeholder.querySelector('.cv-ph--blue'))
      placeholder.innerHTML = _makeConnectingPlaceholderFn();
    if (img) {
      img.classList.remove('loaded');
      img.style.opacity = '0';
    }
    const targetCamId = card.dataset.camid;
    let attempts = 0;
    const poll = setInterval(async () => {
      attempts++;
      if (attempts > 15) {
        clearInterval(poll);
        _restorePlaceholderFn(card);
        return;
      }
      try {
        const r = await j('/api/cameras');
        const cam = (r.cameras || []).find((c) => c.id === targetCamId);
        if (cam?.status === 'active') {
          clearInterval(poll);
          state.cameras = r.cameras || state.cameras;
          renderDashboard();
        }
      } catch {}
    }, 2000);
  });
}

export async function reloadCamera(camId) {
  showCameraReloadAnimation(camId);
  await apiPost(`/api/camera/${encodeURIComponent(camId)}/reload`).catch(() => {});
}

// ── Legacy global bridges ──────────────────────────────────────────────────
// Inline onclick handlers inside renderDashboard's template strings
// reach these via window. `_cvCardClick` was retired in cm-52 (tile
// body became inert); the FS + SIM handlers attach lazily from
// dedicated modules.
window.toggleCardHd = toggleCardHd;
window._refreshLivePillForCard = _refreshLivePillForCard;
window.reloadCamera = reloadCamera;
