// ─── vplayer/index.js ──────────────────────────────────────────────────────
// The one video player: recorded clips, the live view and the detection
// simulation, in one shell with one timeline and one overlay stack.
//
// THIS IS THE ONLY FILE ANYTHING OUTSIDE THE PACKAGE IMPORTS. Everything
// else here is prefixed `_` or lives in a sub-package, and the shell
// builds its OWN DOM — its own root, its own <video>, its own overlay
// hosts, all under the `.vp-` class prefix. It never reaches for
// #lightboxModal or #lightboxMediaWrap. That independence is deliberate:
// the reason the previous architecture had to REPARENT one shared media
// wrap between four surfaces is that its listeners were bound to those
// fixed ids at module load and never unbound. Owning its DOM is what
// makes this package mountable with zero consumers, unit-testable
// without a browser, and removable in a single revert.
//
// Rollout state: SIMULATION runs on this player by default. Live and
// recorded are still behind vplayer/_flag.js and still open their old
// implementations, which remain on disk for the whole soak — one URL
// parameter (?vplayer=off) is the operator's way back.

import { buildPlayerConfig } from './_config.js';
import { mountShell } from './_shell.js';
import { mountStage } from './_stage.js';
import { mountTopbar } from './_topbar.js';
import { mountTransport } from './_transport.js';
import { mountOverlayRow } from './_overlay-row.js';
import {
  buildOverflowItems,
  mountOverflowMenu,
  VP_MENU_DELETE,
  VP_MENU_NATIVE,
} from './_overflow-menu.js';
import { canNativeFullscreen, handoffToNativePlayer } from '../mediaview/player/_native.js';
import { mountTimeline } from './timeline/index.js';
import { renderContextPanel } from './panels/index.js';
import { renderBoxLayer } from './_overlay-svg.js';
import { subscribeLive } from './_data/live.js';
import { loadRecorded } from './_data/recorded.js';

/** The single open player, or null. One at a time, by construction. */
let _open = null;

/** Route an overflow-menu pick to the action it names. */
function _onMenuPick(id, cfg, stage) {
  if (id === VP_MENU_DELETE) {
    cfg.actions.onDelete?.(cfg.item);
    return;
  }
  if (id === VP_MENU_NATIVE) handoffToNativePlayer(stage.video);
}

/**
 * Feed a live surface. The frames come from the EXISTING poll loop —
 * this only maps and paints. See _data/live.js for why owning any of
 * that loop's logic here would be the migration's worst regression.
 */
function _wireLive(cfg, stage, panel, timeline) {
  if (!cfg.flags.live) return null;
  // Only the surfaces that SHOW something from the detection loop
  // subscribe to it. The plain live view wants the continuous stream
  // its <img> is already pointed at; letting the 1 Hz snapshot poll
  // overwrite it would turn a live picture into a slideshow, which is
  // worse than the tile the operator expanded from.
  if (!cfg.flags.showPanel && !cfg.flags.showOverlays) return null;
  return subscribeLive((frame) => {
    // The picture. The backend hands back the exact frame inference ran
    // on, as a base64 JPEG in the SAME coordinate space as the boxes —
    // which is why the boxes are painted against it rather than against
    // a live stream that has moved on since.
    if (frame.snapshot && stage.img.getAttribute('src') !== frame.snapshot) {
      stage.img.src = frame.snapshot;
    }
    if (cfg.flags.showOverlays) {
      renderBoxLayer(stage.layers.boxes, frame.detections, {
        frameSize: frame.frameSize,
        screenW: stage.rect().w,
      });
    }
    panel?.update(frame, null);
    // The rolling window is right-anchored on now, so every tick moves
    // it whether or not a detection landed.
    timeline?.render(frame.tracks || [], { now: Date.now() / 1000, item: cfg.item });
  });
}

/**
 * Load a recorded clip's data and paint the panel and the timeline
 * with it. Fire-and-forget: the shell is already up, so the picture
 * plays while the sidecar is still in flight.
 */
function _wireRecorded(cfg, stage, panel, timeline) {
  if (cfg.flags.live) return;
  loadRecorded(cfg.item)
    .then((data) => {
      panel?.update(data);
      const p = data.provenance || {};
      const rs = cfg.item.recording_settings || {};
      const timing = p.timing || {};
      const render = () =>
        timeline?.render(data.tracks?.tracks || [], {
          duration: stage.video.duration,
          preRoll: timing.pre_roll_s ?? rs.pre_motion_seconds,
          postRoll: timing.post_roll_s ?? rs.post_motion_seconds,
          threshold: p.effective?.spawn_default ?? rs.conf_thresh_general,
          item: cfg.item,
          tracks: data.tracks,
        });
      render();
      // Duration arrives with the metadata, which on first open lands
      // after this render — without the second pass every lane would be
      // laid out against a duration of 0.
      stage.video.addEventListener('loadedmetadata', render);
    })
    .catch(() => {
      /* the clip still plays; the panel simply stays empty */
    });
}

/** Compose the shell's parts. Kept apart so openVideoPlayer stays thin. */
function _mountAll(cfg) {
  const shell = mountShell(cfg, { onKey: (key) => key === 'Escape' && closeVideoPlayer() });
  const stage = mountStage(shell.slot('frame'), cfg);
  const topbar = mountTopbar(shell.slot('topbar'), cfg, {
    onClose: () => closeVideoPlayer(),
    onPrev: cfg.actions.onPrev,
    onNext: cfg.actions.onNext,
  });
  const items = buildOverflowItems(cfg, {
    nativeAvailable: !cfg.flags.live && canNativeFullscreen(stage.video),
  });
  const menu = mountOverflowMenu(shell.slot('topbar'), topbar?.trigger, items, (id) =>
    _onMenuPick(id, cfg, stage),
  );
  const overlayRow = cfg.flags.showOverlays
    ? mountOverlayRow(shell.slot('toggles'), cfg, { roi: cfg.item.roi_label })
    : null;
  const transport = mountTransport(shell.slot('stage'), shell.slot('controls'), cfg, stage);
  const timeline = mountTimeline(shell.slot('timeline'), cfg, {
    onSeek: (t) => {
      stage.video.currentTime = t;
    },
    isPlaying: () => !stage.video.paused && !stage.video.ended,
    onPause: () => stage.video.pause(),
    onResume: () => stage.video.play().catch(() => {}),
  });

  // A live surface with a stream URL points its <img> straight at it,
  // so the picture is continuous rather than a 1 Hz snapshot loop.
  if (cfg.flags.live && cfg.source?.url) stage.img.src = cfg.source.url;

  const panel = renderContextPanel(shell.slot('panel'), cfg, null, cfg.deps || {});
  const live = _wireLive(cfg, stage, panel, timeline);
  if (!cfg.flags.live && cfg.source?.url) stage.video.src = cfg.source.url;
  _wireRecorded(cfg, stage, panel, timeline);

  return { cfg, shell, stage, topbar, menu, overlayRow, transport, timeline, panel, live };
}

/**
 * Open the player.
 *
 * Opening while one is already open closes that one first: two shells
 * on document.body at once would each hold a scroll lock and a
 * capture-phase key trap, and the second teardown would restore the
 * first one's saved body style.
 *
 * @param {object} config  { mode: 'recorded'|'live'|'sim', source?,
 *   item?, camId?, cameraName?, overlays?, actions? }
 * @returns {object} the mounted player handle
 */
export function openVideoPlayer(config) {
  const cfg = buildPlayerConfig(config);
  closeVideoPlayer();
  _open = _mountAll(cfg);
  return _open;
}

/** Is a player currently mounted? Lets a toggle call site ask. */
export function isVideoPlayerOpen() {
  return _open !== null;
}

/** Close whatever the player currently has open. Safe to call twice. */
export function closeVideoPlayer() {
  if (!_open) return;
  const p = _open;
  _open = null;
  // Reverse mount order — every listener released before the DOM it is
  // bound to goes away.
  // The live subscription goes first: a frame arriving mid-teardown
  // would paint into a panel that is already gone.
  p.live?.teardown();
  p.panel?.teardown();
  p.timeline?.teardown();
  p.transport?.teardown();
  p.overlayRow?.teardown();
  p.menu?.teardown();
  p.topbar?.teardown();
  p.stage?.teardown();
  p.shell?.teardown();
  p.cfg.actions.onClose?.();
}
