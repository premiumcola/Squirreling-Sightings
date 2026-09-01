// ─── lightbox.js ───────────────────────────────────────────────────────────
// Stage 4 + Stage 23 of the legacy.js → ES modules refactor.
//
// Stage 4 lifted the pure DOM helpers (_LB_* constants, _updateLbConfirmBtn,
// _lbClearDetections, _lbResetToPhoto, _lbShowError) — those live below.
// Stage 23 grew this module to own the cross-domain orchestration too:
//   * openLightbox / closeLightbox + photo/video player switch
//   * openTLPlayer / _tlNavItems for timelapse playback (now shell-routed)
//   * _lbHandleDeleteKey / _lbNavList / _lbShowSeekOverlay
//   * lightbox prev/next/close button wiring
//   * confirm + delete button onclicks (motion + timelapse paths)
//   * the resize listener that re-paginates the grid on viewport changes
//   * one-time runtime init lines (_updateLbConfirmBtn, lightboxDelete glyph,
//     fullscreen-button binding)
//
// R23 · the document keydown handler (Esc / arrows / space / 'f') and the
// touchstart swipe handler moved to mediaview/keyboard.js. This file
// installs both at module scope and passes their collaborators in, so
// keyboard.js never imports back into here.
//
// All window.openLightbox / window.closeLightbox / window.openTLPlayer
// bridges still live on the legacy.js side so router.js + inline onclicks
// + still-resident callers keep resolving until those domains migrate.
import { byId, esc } from './core/dom.js';
import { state } from './core/state.js';
import { j } from './core/api.js';
import { showToast } from './core/toast.js';
import { lbState } from './mediathek/state.js';
import { lbStopTrackingPlayback, lbClearTrackTimeline } from './mediathek/bbox-overlay/index.js';
import { openMediaView } from './mediaview/index.js';
import { unmountZoneOverlayForLightbox } from './mediaview/canvas/zone-overlay-mount.js';
import { _iosNativeVideoOpen } from './mediathek/ios-video.js';
import { prefersNativePlayer } from './mediaview/player/_pref.js';
import { closeLiveView } from './chrome/live-view.js';
import { _initFsBtn } from './chrome/fullscreen.js';
import { refreshTimelineAndStats } from './chrome/storage-stats.js';
import { installLightboxKeys, installLightboxSwipe } from './mediaview/keyboard.js';
import { applyFrameStep } from './mediaview/player/_frame-step.js';
import { applySpeedChange } from './mediaview/player/_speed.js';
import { toggleLoop } from './mediaview/player/_loop.js';
import { applyDetectionJump } from './mediaview/player/_detection-nav.js';
import { downloadSnapshot } from './mediaview/player/_snapshot.js';
import {
  calcItemsPerPage,
  renderMediaGrid,
  renderMediaPagination,
  closeMediaDrilldown,
} from './mediathek/orchestration.js';

// ── Stage-4 pure helpers ────────────────────────────────────────────────────
// N16 · moved to mediaview/panels/lb-helpers.js. R23 retired all but one
// of the back-compat re-exports: every other consumer now imports the
// helper straight from lb-helpers.js. _lbClearDetections still has one
// caller reaching for it through this module.
export { _lbClearDetections } from './mediaview/panels/lb-helpers.js';
import {
  _LB_TRASH_HTML,
  _updateLbConfirmBtn,
  _lbClearDetections,
  _lbResetToPhoto,
} from './mediaview/panels/lb-helpers.js';

// ── Full-screen video chrome (Stage 30) ─────────────────────────────────────
// openLightbox routes video items (motion clips + timelapses) through a
// dedicated full-screen layout: top bar with cam / ts / actions, video
// region, bottom panel with custom scrubber + per-class track timeline.
// The chrome is a class-toggle on #lightboxModal; the action buttons
// are physically relocated into the top bar so they sit naturally in a
// flex row instead of needing a parallel set of absolute-positioned
// rules.

// Returns true for any item whose lightbox should render in full-screen
// video mode — motion clips with video_relpath / video_url AND
// timelapses (which always have a video).
export function _isFullscreenVideoItem(item) {
  if (!item) return false;
  if (item.type === 'timelapse') return true;
  return !!(item.video_relpath || item.video_url);
}

// Scrubber + play-button + cursor wiring lives in
// mediathek/bbox-overlay.js now — that module owns the bottom-stack
// rendering, so co-locating the handlers there keeps the element-id
// lookups + DOM bindings in one place.

// Move the action buttons (Confirm, Delete, Close) into the top bar in
// the order [Confirm, Delete, Close] so X is the rightmost item.
// Photo events get the buttons restored back to their original parent
// (the media wrap) by _teardownVideoChrome.
function _relocateActionsTo(parentId) {
  const parent = byId(parentId);
  if (!parent) return;
  ['lightboxConfirm', 'lightboxDelete', 'lightboxClose'].forEach((id) => {
    const el = byId(id);
    if (el && el.parentNode !== parent) parent.appendChild(el);
  });
}

// F5 · _setupVideoChrome + _fmtVideoTimeDE removed. The full-screen video
// chrome they built (top bar, action relocation, scrubber+swimlane, panel
// tabs, fold) was the LEGACY recorded + live-detect path; both now ride the
// shared MediaView shell (recorded-mode.js · live-detect-chrome.js → E/F), so
// this DOM-mutating chrome builder has no callers left. _teardownVideoChrome
// stays — recorded-mode's photo branch + closeLightbox still use it to drop
// any lingering legacy chrome.
// Reverse _setupVideoChrome — called when navigating to a photo or
// closing the lightbox entirely. Exported so mediaview/recorded-mode.js
// can drive the same teardown the recorded open path needs.
export function _teardownVideoChrome() {
  const modal = byId('lightboxModal');
  if (!modal) return;
  modal.classList.remove('lb-fs-video');
  byId('lightboxTopBar').hidden = true;
  const setHost = byId('lightboxSettings');
  if (setHost) {
    setHost.hidden = true;
    setHost.innerHTML = '';
  }
  lbClearTrackTimeline();
  // Tear down the overlay-toggles bar so a subsequent photo-event
  // open doesn't show a stale "Bboxes / Trails / …" row.
  const togRow = byId('mvLiveToggles');
  if (togRow) togRow.remove();
  // Buttons return to the media wrap so the photo branch's existing
  // absolute-positioned CSS rules apply.
  _relocateActionsTo('lightboxMediaWrap');
}

// Show an error banner inside the lightbox media wrap (e.g. "Video
// nicht verfügbar", "Video wird verarbeitet…"). Hides the underlying
// img/video elements so the banner reads on a clean dark backdrop.
// Banner is created lazily on first call and reused thereafter.
export function _lbShowError(text) {
  let errEl = byId('lightboxErrorMsg');
  if (!errEl) {
    errEl = document.createElement('div');
    errEl.id = 'lightboxErrorMsg';
    errEl.style.cssText =
      'align-items:center;justify-content:center;width:100%;min-height:240px;max-height:80vh;color:rgba(255,255,255,.55);font-size:15px;font-weight:500;background:#080510;border-radius:18px';
    const wrap = byId('lightboxMediaWrap');
    if (wrap) wrap.appendChild(errEl);
  }
  errEl.textContent = text;
  errEl.style.display = 'flex';
  const imgEl = byId('lightboxImg');
  if (imgEl) imgEl.style.display = 'none';
  const videoEl = byId('lightboxVideo');
  if (videoEl) {
    videoEl.style.display = 'none';
    videoEl.pause();
    videoEl.src = '';
  }
}

// Render a clean error state for a broken event (video file gone,
// API 404, etc.) — clears the playbar/swimlanes from the previous
// clip so the user doesn't see stale chrome bleed through, and
// surfaces actionable buttons. "Nächste anzeigen" skip-traverses
// through unavailable neighbours (loop guard: max 5 attempts).
// "Schließen" just closes. Wetter tab content stays addressable
// because the event metadata is still valid — only the video
// file is gone.
export function resetLightboxToErrorState(msg) {
  // Clear playbar/swimlanes/scrubber so the previous clip's chrome
  // doesn't leak through.
  try {
    lbClearTrackTimeline();
  } catch {
    /* ignore */
  }
  // Replace the panel-tabs body so Nach-Erkennung disappears and the
  // operator can't fire a rescan against a missing video. Wetter +
  // Settings tabs the user opened previously stay accessible — they
  // re-mount on the next valid event.
  const setHost = byId('lightboxSettings');
  if (setHost) {
    setHost.innerHTML = `
      <div class="mv-broken-event">
        <div class="mv-broken-event-title">Diese Aufnahme ist nicht mehr verfügbar</div>
        <div class="mv-broken-event-msg">${esc(msg || 'Video-Datei fehlt oder Event wurde entfernt.')}</div>
        <div class="mv-broken-event-actions">
          <button type="button" class="mv-broken-event-next">→ Nächste anzeigen</button>
          <button type="button" class="mv-broken-event-close">✕ Schließen</button>
        </div>
      </div>`;
    setHost.hidden = false;
    setHost
      .querySelector('.mv-broken-event-next')
      ?.addEventListener('click', () => _lbSkipToValidNeighbour(+1));
    setHost
      .querySelector('.mv-broken-event-close')
      ?.addEventListener('click', () => closeLightbox());
  }
  _lbShowError(msg || 'Diese Aufnahme ist nicht mehr verfügbar.');
}

// Try to navigate to a valid neighbour by stepping `dir` (-1 prev,
// +1 next) up to MAX_HOPS times. A neighbour counts as "valid" when
// it carries either a video_relpath or a video_url — anything less
// hits the same broken-state path. If we run out of neighbours,
// surface the muted "Keine weiteren Aufnahmen verfügbar" note.
const _LB_SKIP_MAX_HOPS = 5;
function _lbSkipToValidNeighbour(dir) {
  const nav = _lbNavList();
  const startIdx = nav.findIndex((x) => x.event_id === lbState.item?.event_id);
  if (startIdx < 0) {
    closeLightbox();
    return;
  }
  for (let hop = 1; hop <= _LB_SKIP_MAX_HOPS; hop++) {
    const idx = startIdx + dir * hop;
    if (idx < 0 || idx >= nav.length) break;
    const candidate = nav[idx];
    if (candidate && (candidate.video_relpath || candidate.video_url)) {
      openLightbox(candidate);
      return;
    }
  }
  // Out of valid neighbours in this direction — soften the error
  // state with a muted note so the user knows there's nothing left.
  const setHost = byId('lightboxSettings');
  if (setHost) {
    const note = document.createElement('div');
    note.className = 'mv-broken-event-final';
    note.textContent = 'Keine weiteren Aufnahmen verfügbar.';
    const actions = setHost.querySelector('.mv-broken-event-actions');
    if (actions) actions.replaceWith(note);
  }
}

// ── Stage-23 orchestration ──────────────────────────────────────────────────
// _renderLbLabels (the label-correction bubbles) moved out to
// mediaview/panels/labels.js — it's now reachable from both the photo
// lightbox (recorded-mode.js) and the recorded-shell "Labels" tab
// (recorded-shell-compose.js), so it lives with the shell's other
// per-tab panel renderers rather than in this orchestration file.

function _lbHandleDeleteKey() {
  if (!lbState.item) return;
  if (lbState.item.confirmed && !lbState.deletePending) {
    lbState.deletePending = true;
    const btn = byId('lightboxDelete');
    if (btn) {
      btn.classList.add('confirm-delete');
      btn.innerHTML = '<span>🗑</span><span style="font-size:9px">↓ nochmal</span>';
    }
    return;
  }
  byId('lightboxDelete').click();
}

export function openLightbox(item) {
  if (item.type === 'timelapse') {
    openTLPlayer(item);
    return;
  }
  // Native hand-off — skip our shell entirely and give the platform its
  // own player. This used to fire on a UA sniff, which meant the SVG
  // detection overlay was unreachable on the exact device it was built
  // for: no DOM overlay can exist inside a native fullscreen <video>.
  // It is now the operator's remembered choice (mediaview/player/_pref.js),
  // default off, flipped from the Systemplayer control inside our player
  // and back from the toast that follows the native player's exit.
  const _hasVideoSrc = !!(item && (item.video_relpath || item.video_url));
  if (_hasVideoSrc && prefersNativePlayer()) {
    _iosNativeVideoOpen(item);
    return;
  }
  // Route through the mediaview shell entry — `recorded` mode renders
  // via mediaview/recorded-mode.js (H). The visible composition is the
  // same full-screen video chrome; the renderer just lives in the
  // mediaview tree now instead of inline here.
  return openMediaView({ mode: 'recorded', item });
}

function _tlNavItems() {
  // Timelapse + motion events share state._allMedia now — navigation is uniform.
  return state._allMedia || [];
}
// E · Timelapse now rides the SAME MediaView shell as motion clips —
// openRecorded (mode:'timelapse') handles the nav, page-jump, video src,
// scrubber, panel tabs + fold. openTLPlayer stays as the public entry
// (window.openTLPlayer + the openLightbox dispatch) and just delegates.
export function openTLPlayer(item) {
  return openMediaView({ mode: 'recorded', item });
}

export function closeLightbox() {
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    (document.exitFullscreen || document.webkitExitFullscreen || function () {})
      .call(document)
      .catch(() => {});
  }
  byId('lightboxModal').classList.add('hidden');
  document.body.style.overflow = '';
  // Halt the Phase-2 tracking-playback RAF loop. Done before clearing
  // lbState.item so the loop's null-check sees a consistent "lightbox
  // closed" state on its next tick.
  lbStopTrackingPlayback();
  // Stop the MediaView live-detect polling loop if it was the path
  // that opened this modal. No-op when nothing is live; cleared via
  // the window bridge so this file doesn't have to import the
  // live-detect module directly.
  try {
    window.closeLiveDetect?.();
  } catch {
    /* ignore */
  }
  // L1 · weather now rides this same #lightboxModal container (mv-modal
  // deleted). Tear its shell down too so Esc / backdrop close converge
  // here. No-op when nothing weather is open; guarded like the bridge
  // above so this file needn't import the weather module directly.
  try {
    window.closeWeatherMode?.();
  } catch {
    /* ignore */
  }
  // E · recorded/timelapse now ride the shared shell too — tear it down so
  // the reparented media wrap + relocated buttons are restored to their DOM
  // home before the next open / photo render. Idempotent; no-op when no
  // recorded shell is up.
  try {
    window.closeRecordedMode?.();
  } catch {
    /* ignore */
  }
  // Tear down the zone/mask overlay + its ResizeObserver. The
  // helper is idempotent; the next open re-mounts cleanly.
  try {
    unmountZoneOverlayForLightbox();
  } catch {
    /* ignore */
  }
  // Drop the full-screen video chrome so the next photo open returns
  // to the centred-modal layout without a flash of misplaced controls.
  _teardownVideoChrome();
  lbState.item = null;
  lbState.index = -1;
  const videoEl = byId('lightboxVideo');
  if (videoEl) {
    videoEl.pause();
    videoEl.src = '';
    videoEl.style.display = 'none';
  }
  byId('lightboxImg').style.display = '';
  _lbClearDetections();
  const confirmBtn = byId('lightboxConfirm');
  if (confirmBtn) confirmBtn.style.display = '';
}

// Lightbox navigation list — the merged-and-sorted global media list for
// BOTH motion and timelapse items. EventStore unifies the two kinds, so
// prev/next walks the global timeline regardless of the current page or
// item type. _tlNavItems() returns the same list (kept as an alias for
// historical reasons + the timelapse-only callers).
function _lbNavList() {
  return state._allMedia || [];
}

let _lbSeekOverlayTimer = null;
function _lbShowSeekOverlay(text) {
  const wrap = byId('lightboxMediaWrap');
  if (!wrap) return;
  let el = byId('lightboxSeekOverlay');
  if (!el) {
    el = document.createElement('div');
    el.id = 'lightboxSeekOverlay';
    el.style.cssText =
      'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(0,0,0,0.72);color:#fff;font-size:34px;font-weight:800;padding:14px 26px;border-radius:14px;pointer-events:none;z-index:5;backdrop-filter:blur(8px);opacity:0;transition:opacity .2s ease;letter-spacing:.02em';
    wrap.appendChild(el);
  }
  el.textContent = text;
  // force reflow so a rapid second press retriggers the fade-in
  el.style.opacity = '0';
  void el.offsetWidth;
  el.style.opacity = '1';
  clearTimeout(_lbSeekOverlayTimer);
  _lbSeekOverlayTimer = setTimeout(() => {
    el.style.opacity = '0';
  }, 600);
}

// ── DOM wiring (runs once on import) ────────────────────────────────────────
byId('lightboxClose').onclick = closeLightbox;
byId('lightboxModal').onclick = (e) => {
  const modal = byId('lightboxModal');
  if (e.target === modal) {
    closeLightbox();
  } else if (modal.classList.contains('lb-weather') && e.target === byId('lightboxInner')) {
    // L1 · in weather mode #lightboxInner fills the viewport (the shell
    // is a centred 980 px column), so a click on the side gutter lands
    // on the inner, not the modal — treat it as backdrop dismiss too.
    closeLightbox();
  }
};
// Step one item along the nav list. The chevron buttons and the
// ArrowLeft/ArrowRight shortcuts drive the same two functions — they used
// to carry a verbatim copy of this body each.
function _lbNavPrev() {
  const nav = _lbNavList();
  const i = nav.findIndex((x) => x.event_id === lbState.item?.event_id);
  if (i > 0) openLightbox(nav[i - 1]);
}
function _lbNavNext() {
  const nav = _lbNavList();
  const i = nav.findIndex((x) => x.event_id === lbState.item?.event_id);
  if (i >= 0 && i < nav.length - 1) openLightbox(nav[i + 1]);
}
byId('lightboxPrev').onclick = _lbNavPrev;
byId('lightboxNext').onclick = _lbNavNext;

// Document-level lightbox / drilldown shortcuts — Esc, Backspace,
// arrows, Space, F. Body lives in mediaview/keyboard.js; every
// collaborator is passed in so that module never imports this one.
installLightboxKeys({
  closeLiveView,
  closeMediaDrilldown,
  closeLightbox,
  navPrev: _lbNavPrev,
  navNext: _lbNavNext,
  handleDeleteKey: _lbHandleDeleteKey,
  showSeekOverlay: _lbShowSeekOverlay,
  // Transport v2 — same functions the on-picture control row
  // (mediaview/player/_transport-controls.js) calls, so a keyboard
  // shortcut and its matching button are never two implementations of
  // the same action.
  stepFrame: applyFrameStep,
  cycleSpeed: applySpeedChange,
  toggleLoop,
  jumpDetection: applyDetectionJump,
  snapshot: downloadSnapshot,
});

_updateLbConfirmBtn(false);
byId('lightboxDelete').innerHTML = _LB_TRASH_HTML;
// Desktop-only — the live modal is never shown on iOS
// (openLiveViewIosNative keeps it hidden and hands directly to
// the native iOS system player), so the FS button inside the
// modal is unreachable on iOS. No iOS gate needed here.
_initFsBtn('liveViewFsBtn', byId('liveViewWrap'), () => byId('liveViewWrap'));

// Swipe navigation on the lightbox media area (mobile) — installer in
// mediaview/keyboard.js.
installLightboxSwipe();

byId('lightboxConfirm').onclick = async () => {
  if (!lbState.item) return;
  const { camera_id, event_id } = lbState.item;
  if (!camera_id || !event_id) return;
  try {
    await j(
      `/api/camera/${encodeURIComponent(camera_id)}/events/${encodeURIComponent(event_id)}/confirm`,
      { method: 'POST' },
    );
    // update state.media in place
    const sIdx = (state.media || []).findIndex((x) => x.event_id === event_id);
    if (sIdx >= 0) state.media[sIdx].confirmed = true;
    _updateLbConfirmBtn(true);
    if (lbState.item) lbState.item.confirmed = true;
    // update card DOM
    const card = byId('mediaGrid').querySelector(`[data-event-id="${CSS.escape(event_id)}"]`);
    if (card) {
      card.classList.add('mmc-confirmed');
      const actions = card.querySelector('.mmc-actions');
      if (actions) actions.outerHTML = '<span class="media-confirmed-badge">✓</span>';
    }
    // auto-advance to next item (use fresh index)
    const ci = (state.media || []).findIndex((x) => x.event_id === event_id);
    const nextIdx = ci + 1;
    if (nextIdx > 0 && nextIdx < (state.media || []).length) openLightbox(state.media[nextIdx]);
    else closeLightbox();
  } catch (e) {
    showToast('Bestätigen fehlgeschlagen: ' + e.message, 'error');
  }
};

byId('lightboxDelete').onclick = async () => {
  if (!lbState.item) return;
  // Weather-sighting deletion (S04). `_openSightingInLightbox` in
  // weather/sightings.js synthesises a timelapse-shaped item with an
  // explicit `source: 'weather'` marker. The camera-timelapse DELETE
  // endpoint 404s on sighting ids, so route to the weather endpoint
  // and refresh the weather grid afterwards.
  if (lbState.item.source === 'weather') {
    if (!lbState.deletePending) {
      lbState.deletePending = true;
      const btn = byId('lightboxDelete');
      if (btn) {
        btn.classList.add('confirm-delete');
        btn.innerHTML =
          '<span style="font-size:15px;line-height:1;opacity:.75">↓</span><span style="font-size:11px">nochmal</span>';
      }
      return;
    }
    try {
      await j(`/api/weather/sightings/${encodeURIComponent(lbState.item.event_id)}`, {
        method: 'DELETE',
      });
      closeLightbox();
      if (typeof window.loadWeatherSightings === 'function') {
        try {
          await window.loadWeatherSightings();
        } catch {
          /* non-critical: grid will refresh on next user nav */
        }
      }
    } catch (e) {
      showToast('Löschen fehlgeschlagen: ' + e.message, 'error');
    }
    return;
  }
  // Timelapse deletion
  if (lbState.item.type === 'timelapse') {
    if (!lbState.deletePending) {
      lbState.deletePending = true;
      const btn = byId('lightboxDelete');
      if (btn) {
        btn.classList.add('confirm-delete');
        btn.innerHTML =
          '<span style="font-size:15px;line-height:1;opacity:.75">↓</span><span style="font-size:11px">nochmal</span>';
      }
      return;
    }
    const filename = lbState.item.filename || (lbState.item.relpath || '').split('/').pop();
    if (!filename) {
      showToast('Dateiname fehlt', 'error');
      return;
    }
    try {
      await j(
        `/api/camera/${encodeURIComponent(lbState.item.camera_id)}/timelapse/${encodeURIComponent(filename)}`,
        { method: 'DELETE' },
      );
      const deletedId = lbState.item.event_id;
      state.media = (state.media || []).filter((x) => x.event_id !== deletedId);
      state._allMedia = (state._allMedia || []).filter((x) => x.event_id !== deletedId);
      renderMediaGrid();
      const nav = _tlNavItems();
      const nextIdx = Math.min(lbState.index, nav.length - 1);
      if (nextIdx < 0) closeLightbox();
      else openLightbox(nav[nextIdx]);
      // Pulls /api/media/storage-stats + re-renders the filter pill
      // bar. Photo delete below already does this; the timelapse
      // branch used to skip it, so deleting the last timelapse left
      // the "Timelapse N" pill stuck on its pre-delete count.
      await refreshTimelineAndStats();
    } catch (e) {
      showToast('Löschen fehlgeschlagen: ' + e.message, 'error');
    }
    return;
  }
  // Photo event deletion
  const { camera_id, event_id } = lbState.item;
  if (!camera_id || !event_id) return;
  try {
    const imgEl = byId('lightboxImg');
    if (imgEl) {
      imgEl.style.transform = 'scale(0.88)';
      imgEl.style.opacity = '0';
    }
    await new Promise((r) => setTimeout(r, 200));
    if (imgEl) {
      imgEl.style.transform = '';
      imgEl.style.opacity = '';
    }
    await j(`/api/camera/${encodeURIComponent(camera_id)}/events/${encodeURIComponent(event_id)}`, {
      method: 'DELETE',
    });
    // Remove from client-side pool and re-paginate so the current page refills
    state._allMedia = (state._allMedia || []).filter((x) => x.event_id !== event_id);
    const ps_lb = calcItemsPerPage();
    state.mediaTotalPages = Math.max(1, Math.ceil(state._allMedia.length / ps_lb));
    state.mediaPage = Math.min(state.mediaPage || 0, state.mediaTotalPages - 1);
    state.media = state._allMedia.slice(state.mediaPage * ps_lb, (state.mediaPage + 1) * ps_lb);
    if (state.media.length === 0 && state.mediaPage > 0) {
      state.mediaPage--;
      state.media = state._allMedia.slice(state.mediaPage * ps_lb, (state.mediaPage + 1) * ps_lb);
    }
    renderMediaGrid();
    renderMediaPagination();
    lbState.index = Math.min(lbState.index, (state.media || []).length - 1);
    if (lbState.index < 0) closeLightbox();
    else openLightbox(state.media[lbState.index]);
    await refreshTimelineAndStats();
  } catch (e) {
    showToast('Löschen fehlgeschlagen: ' + e.message, 'error');
  }
};

// Resize listener — re-paginate the drilldown grid when the viewport
// size changes by enough to shift the column count.
let _mediaResizeTimer = 0;
window.addEventListener('resize', () => {
  clearTimeout(_mediaResizeTimer);
  _mediaResizeTimer = setTimeout(() => {
    if (byId('mediaDrilldown')?.style.display !== 'none') {
      const ns = calcItemsPerPage();
      if (Math.abs(ns - window._cachedPageSize) >= 4) {
        window._cachedPageSize = ns;
        state.mediaTotalPages = Math.max(1, Math.ceil((state._allMedia || []).length / ns));
        state.mediaPage = 0;
        state.media = (state._allMedia || []).slice(0, ns);
        renderMediaGrid();
        renderMediaPagination();
      }
    }
  }, 400);
});

// iOS Safari hard-pauses the lightbox <video> when the tab/PWA goes
// background. On resume the play() promise often rejects silently —
// re-arm by reloading + replaying. Cheap on desktop too (no-op when
// the video isn't open / isn't paused).
document.addEventListener('tamspy:viewport-resumed', () => {
  const v = byId('lightboxVideo');
  if (!v || v.style.display === 'none' || !v.src) return;
  if (v.paused) {
    v.load();
    v.play().catch(() => {});
  }
});

// ── window.* bridges (Stage 25 D) ───────────────────────────────────────────
// router.js + a couple of cam-edit save flows reach for these by
// global name; renderMediaGrid's _openMediaItem also looks up
// window.openLightbox at runtime.
window.openLightbox = openLightbox;
window.closeLightbox = closeLightbox;
window.openTLPlayer = openTLPlayer;
