// ─── mediaview/recorded-shell-compose.js ───────────────────────────────────
// Split out of recorded-mode.js's `_openRecordedVideoShell` — that
// function had grown to ~200 lines (well past the 60-line function /
// 400-line file ceilings) AND, more importantly, had a real gap in it:
// only the `mountMediaView(...)` call itself was covered by the
// "never let a mount failure hide the player silently" try/catch (see
// that fix's own history). Everything AFTER a successful mount — the
// legacy media-wrap reparent, the Behalten/Löschen button relocation,
// the <video> src + error-listener wiring, the zone/mask overlay mount —
// ran completely unguarded, with the modal's only `classList.remove
// ('hidden')` as the very last statement. A throw anywhere in that back
// half reproduced the exact "player never opens, nothing visible
// happens" bug the original fix was built to close, just one step
// further down where nothing was watching.
//
// This module owns the two pure/DOM-mutating halves of that
// composition — building the `mountMediaView` config (no side effects)
// and wiring the mounted shell into the DOM (all the side effects) —
// so `recorded-mode.js::_openRecordedVideoShell` can wrap BOTH in one
// try/catch instead of just the first. Extracting the two seams also
// means each function stays small enough to read as one thing.
import { byId } from '../core/dom.js';
import { isIOS } from '../core/ios-video.js';
import { lbState } from '../mediathek/state.js';
import { setBboxOverlayVisibility, setLbTimelineHost } from '../mediathek/bbox-overlay/index.js';
import { triggerManualReindex } from '../mediathek/bbox-overlay/reindex.js';
import { _lbShowError, resetLightboxToErrorState } from '../lightbox.js';
import { mountZoneOverlayForLightbox } from './canvas/zone-overlay-mount.js';
import { _LB_TRASH_HTML, _updateLbConfirmBtn, _lbResetToPhoto } from './panels/lb-helpers.js';
import { lbRenderSettingsPanel } from './panels/recording-settings.js';
import { renderWeatherPanel } from './panels/weather.js';
import { _renderLbLabels } from './panels/labels.js';

// Two snapshot shapes carry weather: item.weather (normalised) or
// item.api_snapshot (raw Open-Meteo). Mirrors panels/orchestration.js.
function _itemHasWeather(item) {
  return !!(
    (item.weather && typeof item.weather === 'object') ||
    (item.api_snapshot && typeof item.api_snapshot === 'object')
  );
}

// Exported: the unified player's branch in recorded-mode.js needs the
// same derivation, and two copies of a fallback chain drift.
export function _videoSrcOf(item) {
  return (
    (item.video_relpath ? `/media/${item.video_relpath}` : '') ||
    item.video_url ||
    item.url ||
    (item.relpath ? `/media/${item.relpath}` : '')
  );
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

/**
 * Pure `mountMediaView` config builder — no DOM side effects, so it can
 * throw on a genuinely malformed `item` without having touched anything
 * yet. `ctx` is whatever `_openRecordedVideoShell` already worked out:
 * `{ mode, isTL, cam, hasPrev, hasNext, list }`.
 */
export function buildRecordedShellConfig(item, ctx) {
  const { mode, isTL, cam, hasPrev, hasNext, list } = ctx;
  return {
    mode,
    item,
    // Read-only "angewandt: X" tiling badge top-right + grid (the shell
    // owns this now — the per-event tiling isn't stamped, so the cam's
    // current roi_mode is the best proxy, same as the legacy badge).
    appliedTiling: (cam.roi_mode || 'off').toLowerCase(),
    overlays: { bboxes: true, trails: true, zones: true, masks: true },
    // Aufnahme-Settings + Labels only for motion clips (timelapses
    // carry no recording_settings, and only the synthetic "timelapse"
    // pseudo-label — never a real classifier verdict to correct);
    // Wetter only when the item has a snapshot.
    panels: {
      ...(isTL ? {} : { settings: true, labels: true }),
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
      // _renderLbLabels reads the active item off lbState.item (set by
      // recorded-mode.js::openRecorded before this shell mounts), same
      // as the photo path — `it` isn't needed here.
      labels: (host) => _renderLbLabels(host),
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
  };
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

// Pending-state message, or the actual <video> src + error listener.
// Returns the resolved src ('' if none) so the caller knows whether to
// also kick off the tracks.json fetch.
function _wireRecordedVideoSrc(item) {
  const vidSrc = _videoSrcOf(item);
  const pendingMsg =
    item.status === 'recording'
      ? 'Video wird aufgenommen…'
      : item.status === 'processing'
        ? 'Video wird verarbeitet…'
        : null;
  if (pendingMsg) {
    _lbShowError(pendingMsg);
    return vidSrc;
  }
  if (!vidSrc) {
    _lbShowError('Video nicht verfügbar');
    return vidSrc;
  }
  const imgEl = byId('lightboxImg');
  if (imgEl) imgEl.style.display = 'none';
  const videoEl = byId('lightboxVideo');
  if (videoEl) {
    videoEl.style.display = 'block';
    videoEl.src = vidSrc;
    videoEl.muted = true;
    videoEl.loop = true;
    // Chrome (and other Chromium browsers) offer native Picture-in-
    // Picture — an auto-detach affordance in the browser's own Global
    // Media Controls popup — for any playing <video> by default. The
    // operator wants every recorded clip to stay inside OUR player on
    // desktop; only iOS keeps native video behaviour (its own established
    // exception elsewhere in this file — playsinline, webkitEnterFullscreen
    // in core/ios-video.js). Setting this also cleanly disables the
    // player's own PiP button on non-iOS: player/_pip.js::
    // canPictureInPicture already checks `videoEl.disablePictureInPicture`
    // and returns false, so the button simply never renders there — no
    // dangling control that would silently fail if tapped.
    videoEl.disablePictureInPicture = !isIOS;
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
  return vidSrc;
}

/**
 * Wire a just-mounted shell into the DOM: reparent the legacy media
 * wrap, relocate the Behalten/Löschen buttons, set their initial state,
 * wire the <video> src, mount the zone/mask overlay. Mutates
 * `mountRef.homes` (an array the caller already attached to `_recState`
 * before calling this) IN PLACE as each relocation happens, rather than
 * building a local array and returning it at the end — so a throw
 * partway through still leaves `_recState` (and therefore
 * `_teardownRecordedShell`) able to restore whatever WAS already moved,
 * instead of losing that bookkeeping along with the exception.
 *
 * Returns the resolved video src ('' if none) so the caller knows
 * whether to also kick off the tracks.json fetch.
 */
// Reparent the legacy media wrap + relocate the Behalten/Löschen buttons
// into the just-mounted shell, and set their initial state. Split out of
// wireRecordedShellPostMount purely to stay under the 60-line function
// ceiling — still runs inside the SAME try block as everything else.
function _reparentAndRelocate(mountRef, isTL) {
  const shell = mountRef.shell;
  // Reparent the legacy media wrap into the shell frame (keeps the painter,
  // zone overlay + scrubber bound to #lightboxVideo/#lightboxMediaWrap).
  const wrap = byId('lightboxMediaWrap');
  const frame = shell.root.querySelector('[data-slot="frame"]');
  if (wrap && frame) {
    mountRef.homes.push({ el: wrap, parent: wrap.parentNode, next: wrap.nextSibling });
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
    mountRef.homes.push(_relocate('lightboxConfirm', tbActions, firstAction));
  }
  mountRef.homes.push(_relocate('lightboxDelete', tbActions, firstAction));
}

export function wireRecordedShellPostMount(mountRef, item, isTL, modal, inner) {
  const shell = mountRef.shell;
  modal.classList.add('lb-recorded');
  inner.appendChild(shell.root);

  _reparentAndRelocate(mountRef, isTL);

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
  const vidSrc = _wireRecordedVideoSrc(item);

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
  return vidSrc;
}
