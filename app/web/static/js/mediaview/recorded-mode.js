// ─── mediaview/recorded-mode.js ────────────────────────────────────────────
// E · The recorded (Mediathek) player now rides the shared MediaView
// shell (mountMediaView, mode:'recorded'/'timelapse') instead of the
// legacy _setupVideoChrome / #lightboxModal chrome.
//
// Why reuse-by-REPARENT rather than mountCanvasSource: the recorded bbox
// + trail painter (bbox-overlay/renderer.js _lbDrawDetections), the
// zone/mask overlay, the RAF redraw loop, and the scrubber (time-axis.js)
// are ALL bound to #lightboxVideo / #lightboxMediaWrap / #lightboxDetections
// and their auto-redraw listeners are wired at module-load. #lightboxVideo
// can't be duplicated (live-detect still rides it until F). So the safest
// full-parity path is to keep the legacy media wrap + its painter intact
// and REPARENT it into the shell's frame slot — the shell supplies the new
// chrome layout around the reused, unchanged media body. On teardown the
// wrap (and the relocated Behalten/Löschen buttons) are restored to their
// original DOM home so the legacy live-detect + photo paths still find them.
//
// Photos keep the legacy centred-modal bubble-row layout (no shell) — only
// motion clips + timelapses get the full video shell.
//
// Circular import note: this module imports mountMediaView from ./shell.js
// and call-time helpers from ../lightbox.js; both cycles are SAFE because
// every imported binding is used only inside the open/teardown functions
// (call time), never at module-eval time.

import { byId, esc } from '../core/dom.js';
import { state } from '../core/state.js';
import { showToast } from '../core/toast.js';
import { lbState } from '../mediathek/state.js';
import { lbLoadTracksForItem, setLbTimelineHost } from '../mediathek/bbox-overlay/index.js';
import {
  calcItemsPerPage,
  renderMediaGrid,
  renderMediaPagination,
} from '../mediathek/orchestration.js';
import { _isFullscreenVideoItem, _teardownVideoChrome, _lbShowError } from '../lightbox.js';
import { unmountZoneOverlayForLightbox } from './canvas/zone-overlay-mount.js';
import { _LB_TRASH_HTML, _updateLbConfirmBtn, _lbResetToPhoto } from './panels/lb-helpers.js';
import { _renderLbLabels } from './panels/labels.js';
import { mountMediaView } from './shell.js';
import { buildRecordedShellConfig, wireRecordedShellPostMount } from './recorded-shell-compose.js';

// Module-singleton recorded-shell state. Tracks the mounted shell + how
// to restore the reparented media wrap and the relocated action buttons.
let _recState = null;

// Restore everything the shell borrowed, then drop the shell. Order
// matters: move the media wrap + buttons OUT of the shell BEFORE removing
// it, or they'd be detached with it.
function _teardownRecordedShell() {
  if (!_recState) return;
  const st = _recState;
  _recState = null;
  // Stop pinning the timeline host to the (now-gone) shell playbar — the
  // legacy #lightboxBottomStack default takes over again for live-detect.
  setLbTimelineHost(null);
  try {
    unmountZoneOverlayForLightbox();
  } catch {
    /* ignore */
  }
  // Restore in REVERSE push order: the relocated buttons go back into the
  // media wrap (still in the shell frame) BEFORE the wrap itself moves home,
  // so each button's saved nextSibling reference still resolves and the
  // buttons travel with the wrap instead of being detached with the shell.
  for (let i = st.homes.length - 1; i >= 0; i--) {
    const home = st.homes[i];
    if (!home) continue;
    try {
      home.parent?.insertBefore(home.el, home.next || null);
    } catch {
      /* ignore */
    }
  }
  try {
    st.shell?.teardown();
  } catch {
    /* ignore */
  }
  const modal = byId('lightboxModal');
  if (modal) modal.classList.remove('lb-recorded');
}

// Idempotent close bridge — closeLightbox (lightbox.js) calls this via the
// window bridge so Esc / backdrop / the close button converge on one
// teardown that also restores the borrowed DOM.
export function closeRecordedMode() {
  _teardownRecordedShell();
}

// Render a recorded motion-clip / photo / timelapse event.
// Photo path: legacy centred-modal layout (no shell, bubble-row labels).
// Video / timelapse path: the shared shell (top bar, stage with the reused
// media + painter, status-legend band, scrubber + swimlane, panel tabs,
// fold).
export function openRecorded(item) {
  // Defensive: this shared #lightboxModal may be mid-weather or mid-live —
  // tear those down + drop their classes so the recorded chrome shows.
  try {
    window.closeWeatherMode?.();
  } catch {
    /* ignore */
  }
  try {
    window.closeLiveDetect?.();
  } catch {
    /* ignore */
  }
  byId('lightboxModal')?.classList.remove('lb-weather', 'lb-live-detect', 'lb-fs-video');

  // Index into the GLOBAL list (state._allMedia) so prev/next can cross
  // pagination boundaries — the page-slice (state.media) is a render
  // optimisation, not a navigation boundary.
  const globalList = state._allMedia || [];
  lbState.index = globalList.findIndex((x) => x.event_id === item.event_id);
  if (lbState.index === -1) {
    lbState.index = 0;
    lbState.item = item;
  } else {
    lbState.item = globalList[lbState.index];
  }
  // Jump the grid's page so the thumbnails behind the lightbox match.
  const ps = window._cachedPageSize || calcItemsPerPage();
  if (window._cachedPageSize && globalList.length > 0) {
    const targetPage = Math.floor(lbState.index / ps);
    if (targetPage !== state.mediaPage) {
      state.mediaPage = targetPage;
      const offset = targetPage * ps;
      state.media = globalList.slice(offset, offset + ps);
      try {
        renderMediaGrid();
        renderMediaPagination();
      } catch (_) {}
    }
  }
  lbState.deletePending = false;

  if (_isFullscreenVideoItem(lbState.item)) {
    _openRecordedVideoShell(lbState.item);
  } else {
    _openRecordedPhoto(lbState.item);
  }
}

// ── Photo branch — legacy centred-modal layout (no shell) ────────────────
function _openRecordedPhoto(item) {
  _teardownRecordedShell();
  _teardownVideoChrome();
  _lbResetToPhoto();
  const delBtn = byId('lightboxDelete');
  if (delBtn) {
    delBtn.classList.remove('confirm-delete');
    delBtn.innerHTML = _LB_TRASH_HTML;
    delBtn.title = item.confirmed ? 'Bestätigt — trotzdem löschen?' : 'Löschen';
  }
  _updateLbConfirmBtn(item.confirmed);
  const imgSrc = item.snapshot_relpath
    ? `/media/${item.snapshot_relpath}`
    : item.snapshot_url || '';
  const hasVideoLabel = (item.labels || []).some((l) =>
    ['motion', 'car', 'person', 'cat', 'bird', 'dog', 'squirrel'].includes(l),
  );
  if (!imgSrc && (hasVideoLabel || item.encode_error)) {
    _lbShowError('Video nicht verfügbar');
  } else {
    byId('lightboxImg').src = imgSrc;
  }
  byId('lightboxMeta').innerHTML = `
    <span class="badge">${esc(item.camera_id || '')}</span>
    <span class="badge">${esc(item.time || '')}</span>
    ${item.confirmed ? `<span style="background:#166534;color:#4ade80;border-radius:999px;padding:3px 10px;font-size:11px;font-weight:700">✓ Behalten</span>` : ''}`;
  _renderLbLabels();
  byId('lightboxPrev').style.opacity = lbState.index > 0 ? '1' : '0.2';
  byId('lightboxNext').style.opacity =
    lbState.index < (state._allMedia || []).length - 1 ? '1' : '0.2';
  byId('lightboxModal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

// ── Video / timelapse branch — the shared MediaView shell ────────────────
function _openRecordedVideoShell(item) {
  // Always start from a clean recorded shell (handles video→video nav too).
  _teardownRecordedShell();

  const isTL = item.type === 'timelapse';
  const mode = isTL ? 'timelapse' : 'recorded';
  const cam = (state.cameras || []).find((c) => c.id === item.camera_id) || {};
  const list = state._allMedia || [];
  const hasPrev = lbState.index > 0;
  const hasNext = lbState.index >= 0 && lbState.index < list.length - 1;
  const modal = byId('lightboxModal');
  const inner = byId('lightboxInner');
  if (!modal || !inner) return;

  // The WHOLE composition — mount + DOM reparenting + video/overlay wiring
  // (recorded-shell-compose.js) — shares ONE safety net. It used to stop
  // at mountMediaView(...) (see this function's git history): everything
  // after a successful mount ran completely unguarded, with the modal's
  // only `classList.remove('hidden')` as the very last statement. A
  // throw ANYWHERE in that back half reproduced the exact "player never
  // opens, nothing visible happens" bug the original fix was built to
  // close, just one step further down where nothing was watching. Fail
  // loud everywhere in this composition now, not just in the first half.
  let mountRef = null;
  try {
    const shell = mountMediaView(
      buildRecordedShellConfig(item, { mode, isTL, cam, hasPrev, hasNext, list }),
    );
    mountRef = { shell, homes: [] };
    // Registered BEFORE wiring finishes (not after) so a throw partway
    // through wiring still leaves `_teardownRecordedShell` able to
    // restore whatever homes were already pushed by then.
    _recState = mountRef;
    const vidSrc = wireRecordedShellPostMount(mountRef, item, isTL, modal, inner);
    // Fetch tracks.json → lights up the bbox/trail overlay + the swimlane.
    if (vidSrc) lbLoadTracksForItem(item);
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  } catch (err) {
    console.error('[mediaview] recorded shell failed to mount:', err);
    _recoverFromShellFailure(mountRef);
    // Force the reveal LAST, outside the guarded recovery steps, so it
    // survives even if every one of those also threw.
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }
}

// Best-effort cleanup after ANY failure in the recorded-shell mount/wire
// composition, then surface something visible to the operator — each
// step independently guarded so a throw in the cleanup or the messaging
// itself can never undo the forced modal reveal the caller does next.
function _recoverFromShellFailure(mountRef) {
  try {
    _teardownRecordedShell();
  } catch {
    /* ignore */
  }
  // _recState (== mountRef, if it got that far) was only fully wired at
  // the very end — an earlier throw can leave a mounted-but-not-yet-
  // tracked shell.root behind. Drop it directly so a half-built player
  // doesn't linger in the DOM under the error state.
  try {
    mountRef?.shell?.root?.remove?.();
  } catch {
    /* ignore */
  }
  try {
    _lbShowError('Player konnte nicht geöffnet werden.');
  } catch {
    /* ignore */
  }
  try {
    showToast('Player konnte nicht geöffnet werden.', 'error');
  } catch {
    /* ignore */
  }
}

// Bridge for lightbox.closeLightbox (Esc / backdrop / close button) so they
// converge on the shell teardown that also restores the borrowed DOM.
if (typeof window !== 'undefined') {
  window.closeRecordedMode = closeRecordedMode;
}
