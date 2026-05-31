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
import { lbState } from '../mediathek/state.js';
import {
  lbLoadTracksForItem,
  setBboxOverlayVisibility,
  setLbTimelineHost,
} from '../mediathek/bbox-overlay/index.js';
import { triggerManualReindex } from '../mediathek/bbox-overlay/reindex.js';
import {
  calcItemsPerPage,
  renderMediaGrid,
  renderMediaPagination,
} from '../mediathek/orchestration.js';
import {
  _isFullscreenVideoItem,
  _teardownVideoChrome,
  _lbShowError,
  resetLightboxToErrorState,
  _renderLbLabels,
} from '../lightbox.js';
import {
  mountZoneOverlayForLightbox,
  unmountZoneOverlayForLightbox,
} from './canvas/zone-overlay-mount.js';
import { _LB_TRASH_HTML, _updateLbConfirmBtn, _lbResetToPhoto } from './panels/lb-helpers.js';
import { mountMediaView } from './shell.js';
import { lbRenderSettingsPanel } from './panels/recording-settings.js';
import { renderWeatherPanel } from './panels/weather.js';

// Module-singleton recorded-shell state. Tracks the mounted shell + how
// to restore the reparented media wrap and the relocated action buttons.
let _recState = null;

// Two snapshot shapes carry weather: item.weather (normalised) or
// item.api_snapshot (raw Open-Meteo). Mirrors panels/orchestration.js.
function _itemHasWeather(item) {
  return !!(
    (item.weather && typeof item.weather === 'object') ||
    (item.api_snapshot && typeof item.api_snapshot === 'object')
  );
}

function _videoSrcOf(item) {
  return (
    (item.video_relpath ? `/media/${item.video_relpath}` : '') ||
    item.video_url ||
    item.url ||
    (item.relpath ? `/media/${item.relpath}` : '')
  );
}

// Relocate a legacy action button into a new parent, remembering where it
// came from so teardown can put it back exactly. Idempotent per button.
function _relocate(id, newParent, beforeNode) {
  const el = byId(id);
  if (!el || !newParent) return null;
  const home = { el, parent: el.parentNode, next: el.nextSibling };
  newParent.insertBefore(el, beforeNode || null);
  return home;
}

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

  const shell = mountMediaView({
    mode,
    item,
    // Read-only "angewandt: X" tiling badge top-right + grid (the shell
    // owns this now — the per-event tiling isn't stamped, so the cam's
    // current roi_mode is the best proxy, same as the legacy badge).
    appliedTiling: (cam.roi_mode || 'off').toLowerCase(),
    overlays: { bboxes: true, trails: true, zones: true, masks: true },
    // Aufnahme-Settings only for motion clips (timelapses carry no
    // recording_settings); Wetter only when the item has a snapshot.
    panels: {
      ...(isTL ? {} : { settings: true }),
      ...(_itemHasWeather(item) ? { weather: true } : {}),
    },
    panelRenderers: {
      settings: (host, it) => {
        lbRenderSettingsPanel(it, host);
        // Auto-expand the inner collapsible (the user already chose the tab).
        const body = host.querySelector('.lbset-body');
        const header = host.querySelector('.lbset-header');
        if (body && header && body.hidden) {
          body.hidden = false;
          header.setAttribute('aria-expanded', 'true');
        }
      },
      weather: (host, it) => renderWeatherPanel(host, it),
    },
    initialTab: isTL ? 'weather' : 'settings',
    actions: {
      onPrev: hasPrev ? () => window.openLightbox?.(list[lbState.index - 1]) : undefined,
      onNext: hasNext ? () => window.openLightbox?.(list[lbState.index + 1]) : undefined,
      onClose: () => window.closeLightbox?.(),
      onDownload: () => _downloadItem(item),
      // Reuse the manual-reindex flow ("Neu erkennen"); for timelapses the
      // playbar's own empty-state "Nach-Erkennung starten" also exists.
      // triggerManualReindex(btn) reads the event/camera from lbState.item
      // internally — btn is optional (busy/disabled feedback only).
      onRetrigger: () => triggerManualReindex(),
      // Overlay-toggle pills → the existing layer-visibility setters (same
      // wiring the legacy _setupVideoChrome used).
      onOverlayChange: (id, on) => {
        if (id === 'zones' || id === 'masks') {
          window._setZoneOverlayVisibility?.({
            showZones: id === 'zones' ? on : undefined,
            showMasks: id === 'masks' ? on : undefined,
          });
        } else if (id === 'bboxes') {
          setBboxOverlayVisibility({ showBboxes: on });
        } else if (id === 'trails') {
          setBboxOverlayVisibility({ showTrails: on });
        }
      },
    },
  });

  const modal = byId('lightboxModal');
  const inner = byId('lightboxInner');
  if (!modal || !inner) return;
  modal.classList.add('lb-recorded');
  inner.appendChild(shell.root);

  // Reparent the legacy media wrap into the shell frame (keeps the painter,
  // zone overlay + scrubber bound to #lightboxVideo/#lightboxMediaWrap).
  const homes = [];
  const wrap = byId('lightboxMediaWrap');
  const frame = shell.root.querySelector('[data-slot="frame"]');
  if (wrap && frame) {
    homes.push({ el: wrap, parent: wrap.parentNode, next: wrap.nextSibling });
    frame.appendChild(wrap);
  }
  // Pin the timeline host to the shell's playbar so EVERY host-less
  // lbRenderTrackTimeline re-render (the async tracks-fetch, the
  // loadedmetadata rescale, manual reindex, rescan-poll) lands in the
  // visible playbar instead of the hidden legacy #lightboxBottomStack —
  // otherwise the populated swimlane + the scrubber wiring go off-screen.
  const playbar = shell.root.querySelector('[data-slot="playbar"]');
  setLbTimelineHost(playbar || null);
  // Relocate Behalten (motion only) + Löschen into the shell title bar so
  // their existing handlers (confirm toggle, delete two-step, auto-advance)
  // keep working verbatim.
  const tbActions = shell.root.querySelector('.mv-tb-actions');
  const firstAction = tbActions?.firstChild || null;
  if (!isTL) {
    homes.push(_relocate('lightboxConfirm', tbActions, firstAction));
  }
  homes.push(_relocate('lightboxDelete', tbActions, firstAction));

  _recState = { shell, homes };

  // Confirm/delete button initial state.
  if (!isTL) _updateLbConfirmBtn(item.confirmed);
  const delBtn = byId('lightboxDelete');
  if (delBtn) {
    delBtn.classList.remove('confirm-delete');
    delBtn.innerHTML = _LB_TRASH_HTML;
    delBtn.title = isTL
      ? 'Timelapse löschen'
      : item.confirmed
        ? 'Bestätigt — trotzdem löschen?'
        : 'Löschen';
  }

  // Wire the media element + start the painter/scrubber (same flow the
  // legacy recorded open used, just inside the reparented wrap).
  _lbResetToPhoto();
  // Timelapses can't be confirmed — _lbResetToPhoto just un-hid #lightboxConfirm,
  // and it's NOT relocated for TL, so it'd sit as a stray green Behalten check
  // inside the reparented wrap. Hide it (mirrors the legacy openTLPlayer).
  if (isTL) {
    const cb = byId('lightboxConfirm');
    if (cb) cb.style.display = 'none';
  }
  const vidSrc = _videoSrcOf(item);
  const pendingMsg =
    item.status === 'recording'
      ? 'Video wird aufgenommen…'
      : item.status === 'processing'
        ? 'Video wird verarbeitet…'
        : null;
  if (pendingMsg) {
    _lbShowError(pendingMsg);
  } else if (vidSrc) {
    const imgEl = byId('lightboxImg');
    if (imgEl) imgEl.style.display = 'none';
    const videoEl = byId('lightboxVideo');
    if (videoEl) {
      videoEl.style.display = 'block';
      videoEl.src = vidSrc;
      videoEl.muted = true;
      videoEl.loop = true;
      const _onVideoError = () => {
        if (videoEl._lbErrorBound !== _onVideoError) return;
        videoEl.removeEventListener('error', _onVideoError);
        videoEl._lbErrorBound = null;
        resetLightboxToErrorState('Video-Datei ist nicht mehr verfügbar.');
      };
      videoEl._lbErrorBound = _onVideoError;
      videoEl.addEventListener('error', _onVideoError);
      videoEl.load();
      videoEl.play().catch(() => {});
    }
  } else {
    _lbShowError('Video nicht verfügbar');
  }

  // Read-only zone/mask overlay on the reused media wrap.
  mountZoneOverlayForLightbox(item, { hideMasks: isTL });
  // Sync the four layers' initial visibility from the shell's toggle state
  // (persisted bboxes/trails; declared defaults for zones/masks).
  const initial = shell.components?.overlayToggles?.getState?.() || {};
  if ('zones' in initial || 'masks' in initial) {
    window._setZoneOverlayVisibility?.({ showZones: !!initial.zones, showMasks: !!initial.masks });
  }
  if ('bboxes' in initial || 'trails' in initial) {
    setBboxOverlayVisibility({ showBboxes: !!initial.bboxes, showTrails: !!initial.trails });
  }
  // Fetch tracks.json → lights up the bbox/trail overlay + the swimlane.
  if (vidSrc) lbLoadTracksForItem(item);

  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

// Trigger a browser download of the clip without leaving the player.
function _downloadItem(item) {
  const src = _videoSrcOf(item);
  if (!src) return;
  const a = document.createElement('a');
  a.href = src;
  a.download = (item.video_relpath || item.relpath || 'clip').split('/').pop();
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// Bridge for lightbox.closeLightbox (Esc / backdrop / close button) so they
// converge on the shell teardown that also restores the borrowed DOM.
if (typeof window !== 'undefined') {
  window.closeRecordedMode = closeRecordedMode;
}
