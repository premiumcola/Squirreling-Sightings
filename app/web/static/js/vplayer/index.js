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
// Rollout state: the shell, the stage, the top bar, the overlay row and
// the transport mount. The timeline, the context panels and the data
// adapters land in the following commits, into the slots that are
// already here. NO CALL SITE CAN REACH ANY OF IT YET — each surface is
// switched over separately behind vplayer/_flag.js, and until then this
// module has no importer at all.

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

  return { cfg, shell, stage, topbar, menu, overlayRow, transport, timeline };
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

/** Close whatever the player currently has open. Safe to call twice. */
export function closeVideoPlayer() {
  if (!_open) return;
  const p = _open;
  _open = null;
  // Reverse mount order — every listener released before the DOM it is
  // bound to goes away.
  p.timeline?.teardown();
  p.transport?.teardown();
  p.overlayRow?.teardown();
  p.menu?.teardown();
  p.topbar?.teardown();
  p.stage?.teardown();
  p.shell?.teardown();
  p.cfg.actions.onClose?.();
}
