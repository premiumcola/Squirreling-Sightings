// ─── vplayer/_chrome.js ────────────────────────────────────────────────────
// Everything the operator presses that is not the picture, the timeline
// or the panel: the top strip, the speed pill, the overflow menu behind
// the ⋮, and the prev/next chevrons at the picture's sides.
//
// WHY ITS OWN FILE. index.js mounts and composes; these four share a
// host, a trigger element and an order that matters, and holding them
// together was the last thing keeping that file growing. The same seam
// _wire-recorded.js was cut along (index.js past CLAUDE.md's 400-line
// ceiling), one concern at a time.
//
// THE ORDER IS THE ARGUMENT. The item set is built FIRST, because
// mountOverflowMenu refuses to mount an empty menu and returns null — so
// a ⋮ rendered before anyone asked whether there were items is a button
// sitting on the picture that answers nothing. That is the exact failure
// removed elsewhere in this pass, and it is cheaper not to reintroduce
// it than to find it again.

import { mountTopbar } from './_topbar.js';
import { mountSpeed } from './_speed.js';
import { mountStageChrome } from './_stage-chrome.js';
import {
  buildOverflowItems,
  mountOverflowMenu,
  VP_MENU_DELETE,
  VP_MENU_NATIVE,
} from './_overflow-menu.js';
import { canNativeFullscreen, handoffToNativePlayer } from '../mediaview/player/_native.js';

/** Route an overflow-menu pick to the action it names. */
function _onMenuPick(id, cfg, stage) {
  if (id === VP_MENU_DELETE) {
    cfg.actions.onDelete?.(cfg.item);
    return;
  }
  if (id === VP_MENU_NATIVE) handoffToNativePlayer(stage.video);
}

/**
 * Mount the player's chrome.
 *
 * `onClose` is passed in rather than imported: the close IS
 * closeVideoPlayer, which lives in index.js and imports this module, so
 * reaching back for it would be a cycle.
 *
 * @param {object} shell     handle from _shell.js
 * @param {object} cfg       normalised config from _config.js
 * @param {object} stage     handle from _stage.js
 * @param {object} handlers  { onClose }
 * @returns {{topbar, menu, stageChrome, speed}}
 */
export function mountChrome(shell, cfg, stage, handlers = {}) {
  const items = buildOverflowItems(cfg, {
    nativeAvailable: !cfg.flags.live && canNativeFullscreen(stage.video),
  });
  const topbar = mountTopbar(shell.slot('topbar'), cfg, {
    onClose: handlers.onClose,
    hasMenu: items.length > 0,
  });
  // prev/next live on the picture's sides, not in the title row.
  const stageChrome = mountStageChrome(shell.slot('stage'), cfg, {
    onPrev: cfg.actions.onPrev,
    onNext: cfg.actions.onNext,
  });
  const speed = mountSpeed(topbar?.speedHost, cfg, stage);
  // On the ROOT, not on the strip: the strip is inside an
  // `overflow: hidden` stage now. See mountOverflowMenu's own note.
  const menu = mountOverflowMenu(shell.root, topbar?.trigger, items, (id) =>
    _onMenuPick(id, cfg, stage),
  );
  return { topbar, menu, stageChrome, speed };
}

/**
 * Release it, in reverse mount order — every listener dropped before the
 * DOM it is bound to goes away. The speed pill comes off before the
 * strip it lives in: it holds two listeners on the <video> and its own
 * node inside the strip's markup.
 */
export function teardownChrome(chrome) {
  if (!chrome) return;
  chrome.menu?.teardown();
  chrome.speed?.teardown();
  chrome.stageChrome?.teardown();
  chrome.topbar?.teardown();
}
