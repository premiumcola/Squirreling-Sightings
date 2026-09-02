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
// Rollout state: the shell, the timeline, the overlays and the panels
// land here first with no call site able to reach them. Each surface is
// switched over separately behind vplayer/_flag.js.

import { buildPlayerConfig } from './_config.js';

/**
 * Thrown while a mode's controller is still landing. Named so a call
 * site added ahead of its controller fails as an obvious, greppable
 * error rather than as an empty modal.
 */
export class VPlayerNotImplementedError extends Error {
  constructor(mode) {
    super(`vplayer: the '${mode}' player is not mounted yet`);
    this.name = 'VPlayerNotImplementedError';
    this.mode = mode;
  }
}

/**
 * Open the player.
 *
 * @param {object} config  { mode: 'recorded'|'live'|'sim', source?,
 *   item?, camId?, cameraName?, overlays?, actions? }
 * @returns {object} the mounted player handle
 */
export function openVideoPlayer(config) {
  const cfg = buildPlayerConfig(config);
  throw new VPlayerNotImplementedError(cfg.mode);
}

/** Close whatever the player currently has open. Safe to call twice. */
export function closeVideoPlayer() {
  // No-op until a controller exists to tear down. Exported from the
  // first commit so the public surface is fixed before any call site
  // depends on it.
}
