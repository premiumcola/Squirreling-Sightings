// ─── mediaview/live-detect-chrome.js ───────────────────────────────────────
// F · Mounts the live-detect view onto the shared MediaView shell
// (mountMediaView, mode:'live-detect') instead of the legacy
// _setupVideoChrome + 5-zone skeleton.
//
// Reuse-by-REPARENT (same pattern as the recorded player in E): the 1 Hz
// inference-snapshot <img> + its bbox/trails/zone-mask overlays + the tick
// loop are all bound to #lightboxImg / #lightboxMediaWrap. We reparent the
// media wrap into the shell's stage frame (the overlays fall back to
// #lightboxMediaWrap when no skeleton exists), mount the live 'ld' tab
// system (Detections/Trace/Debug) into the shell's tab + content hosts, and
// move #lightboxSettings (Detections content) + #lightboxBottomStack
// (swimlane) into the shell panel + playbar slots — so every by-id renderer
// in the tick loop keeps working unchanged. The shell owns the title bar,
// the overlay-toggle pills (top-left), the Stream+mode cluster (top-right),
// the status-legend band, and the playbar; this file wires those regions
// back into the live data path.
//
// Q2-4 · snapshot-only: the <img> shows the exact frame inference ran on
// (data.snapshot per tick). DO NOT reintroduce a live stream — a stream
// reintroduces the bbox-ahead-of-picture desync this view exists to remove.
import { byId, esc } from '../core/dom.js';
import { S } from './live-detect-state.js';
import { renderFineAnalysisFold } from './fine-analysis-fold.js';
import { mountMediaView } from './shell.js';
import { _renderBboxOverlay } from './live-detect-bbox.js';
import { mountLdSkeleton } from './live-detect-skeleton.js';
import {
  _installLiveOverlayRefresh,
  _ensureBboxOverlay,
  _ensureTrailsOverlay,
  _ensureZoneMaskOverlay,
  _renderTrailsOverlay,
  _renderZoneMaskOverlay,
} from './live-detect-overlays.js';
import { _renderLiveSwimlane } from './live-detect-panels.js';
import { _tick } from './live-detect-poll.js';

export function _setupLiveChrome(camId, cameraName) {
  if (!S.session) return;
  const item = {
    type: 'live-detect',
    event_id: `live-${camId}`,
    camera_id: camId,
    camera_name: cameraName || camId,
    time: '',
    _tracks: { tracks: [] },
  };
  // Mount the shared shell. live-detect mode → interactive mode-indicator
  // (D4: picking Motion-ROI / 2×2 / 3×3 draws the tiling grid over the LIVE
  // frame, "Aus" clears it) + the live swimlane region. The shell owns the
  // overlay-toggle pills + the status-legend band; onModeChange /
  // onOverlayChange wire them back into the live data path. No shell fafold —
  // _mountPanels owns the live "Trace" fold (inside the Detections tab).
  const shell = mountMediaView({
    mode: 'live-detect',
    item,
    overlays: { bboxes: true, trails: true, zones: true, masks: true },
    panels: {}, // live uses its own persistent 'ld' tabs, not the shell tabs
    showFineFold: false,
    detMode: S.session.detMode || 'off',
    actions: {
      onClose: () => window.closeLightbox?.(),
      onModeChange: (id) => {
        if (!S.session) return;
        S.session.detMode = id;
        _forceImmediateTick();
      },
      onOverlayChange: (id, on) => {
        if (!S.session) return;
        S.overlays[id] = on;
        _renderBboxOverlay();
        _renderTrailsOverlay();
        _renderZoneMaskOverlay();
      },
    },
  });
  const modal = byId('lightboxModal');
  const inner = byId('lightboxInner');
  if (!modal || !inner) return;
  modal.classList.add('lb-live-detect');
  modal.classList.remove('hidden');
  inner.appendChild(shell.root);
  S.session.shell = shell;

  // Reparent the legacy media wrap into the shell frame — the snapshot <img>
  // + the bbox/trails/zonemask overlays live inside it, so the tick loop +
  // painters keep working unchanged (overlays fall back to #lightboxMediaWrap
  // when no 5-zone skeleton is present).
  const frame = shell.root.querySelector('[data-slot="frame"]');
  const wrap = byId('lightboxMediaWrap');
  if (frame && wrap) {
    S.session.wrapHome = { parent: wrap.parentNode, next: wrap.nextSibling };
    frame.appendChild(wrap);
  }

  // Mount the live 'ld' tab system into the shell tab strip + a content host,
  // and move the swimlane stack into the playbar. The shell's placeholder
  // swimlane (D) is cleared first so #lightboxBottomStack is the only stack.
  const tabsHost = shell.root.querySelector('[data-slot="tabs"]');
  const playbar = shell.root.querySelector('[data-slot="playbar"]');
  const panelsArea = shell.root.querySelector('[data-slot="panels"]');
  const fafold = shell.root.querySelector('[data-slot="fafold"]');
  const contentHost = document.createElement('div');
  contentHost.className = 'mv-ld-shell-detail';
  if (fafold) panelsArea.insertBefore(contentHost, fafold);
  else if (panelsArea) panelsArea.appendChild(contentHost);
  if (playbar) playbar.innerHTML = '';
  mountLdSkeleton({
    camId,
    cameraName,
    shellHosts: { tabsHost, contentHost, timelineHost: playbar },
  });

  // Seed the overlay-visibility mirror from the shell toggle bar's state.
  const togState = shell.components?.overlayToggles?.getState?.();
  if (togState) S.overlays = togState;

  // Q2-4 · keep the <video> dark, show the <img>; _renderFrame swaps each
  // tick's inference snapshot into it.
  const videoEl = byId('lightboxVideo');
  if (videoEl) {
    videoEl.pause?.();
    videoEl.removeAttribute('src');
    videoEl.load?.();
    videoEl.style.display = 'none';
  }
  const imgEl = byId('lightboxImg');
  if (imgEl) {
    imgEl.removeAttribute('src');
    imgEl.style.display = 'block';
    imgEl.alt = '';
    _installLiveOverlayRefresh(imgEl);
  }
  _ensureBboxOverlay();
  _ensureTrailsOverlay();
  _ensureZoneMaskOverlay();

  // Stream Sub/Main toggle → the shell's reserved Stream slot (D3).
  _mountStreamToggle(shell);

  // Paint zones/masks + an empty swimlane before the first tick lands.
  _renderZoneMaskOverlay();
  _renderLiveSwimlane();
}

export function _forceImmediateTick() {
  const session = S.session;
  if (!session) return;
  if (session.tickHandle) {
    clearTimeout(session.tickHandle);
    session.tickHandle = null;
  }
  try {
    session.abort?.abort();
  } catch {
    /* ignore */
  }
  _tick();
}

// C2/C3 · the Stream Sub/Main toggle, factored out of the old
// _mountSimControls so there is ONE owner. Mounts into the shell's reserved
// Stream slot (top-right cluster, beside the mode-indicator). Ephemeral
// (session-scoped — no persistence); flips S.session.stream + forces an
// immediate re-tick so the new stream takes visible effect next frame. The
// detection-mode chips are now the shell's interactive mode-indicator (D4),
// wired via the mountMediaView onModeChange above.
function _mountStreamToggle(shell) {
  const slot = shell?.root?.querySelector('[data-slot="stream"]');
  if (!slot || !S.session) return;
  const render = () => {
    const stream = S.session.stream || 'main';
    slot.innerHTML =
      `<button type="button" class="mv-sim-ctl" data-ctl="stream" data-val="${esc(stream)}" ` +
      `title="Welchen Stream der Simulator prüft (Main = Produktions-Pipeline, Sub = 640×360)" ` +
      `aria-label="Stream umschalten, aktuell ${esc(stream)}">` +
      `<span class="mv-sim-ctl-chip"><span class="mv-sim-ctl-k">Stream</span>` +
      `<span class="mv-sim-ctl-v">${stream === 'sub' ? 'Sub' : 'Main'}</span></span></button>`;
    slot.querySelector('button[data-ctl="stream"]')?.addEventListener('click', () => {
      if (!S.session) return;
      S.session.stream = S.session.stream === 'sub' ? 'main' : 'sub';
      render();
      _forceImmediateTick();
    });
  };
  render();
}

export function _pinScrubberRight() {
  // Live has no recorded clip → no seek. The swimlane (renderLiveSwimlane)
  // owns the single LIVE marker; if a recorded-style .lb-time-stack is ever
  // present, pin its playhead to the right edge. Defensive stale-pill drop.
  const stack = document.querySelector('.lb-time-stack');
  if (stack) stack.style.setProperty('--play-pct', '1');
  const stale = byId('mvLiveScrubPill');
  if (stale) stale.remove();
}

export function _mountPanels() {
  const host = byId('lightboxSettings');
  if (!host) return;
  host.hidden = false;
  // D67 · the Detections panel IS the detections — render the rows directly.
  // D78 · the Diagnose <details> + Fein-Analyse fold are merged into one
  // "Trace" fold; the diag pulse becomes that fold's summary suffix.
  host.innerHTML = `
    <div class="mv-recorded-panels">
      <div id="mvLdDetections" class="mv-ld-detections"></div>
      <div class="mv-recorded-fafold"></div>
    </div>`;
  const faHost = host.querySelector('.mv-recorded-fafold');
  // F4 · live:true → empty-state reads "Warte auf ersten Tick …";
  // defaultOpen:true → the Trace fold starts expanded so the decision trace
  // ticks visibly. The tick loop's _appendTrace / _renderDiagPanel feed it
  // via S.session.fold.
  const fold = renderFineAnalysisFold(faHost, null, { defaultOpen: true, live: true });
  if (S.session) S.session.fold = fold;
}
