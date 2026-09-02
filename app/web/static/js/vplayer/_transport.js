// ─── vplayer/_transport.js ─────────────────────────────────────────────────
// Thin composition over mediaview/player/*. It owns nothing.
//
// That toolkit is a large, tested body of behaviour: the −10 / play /
// +10 discs, the elapsed and −remaining pair, the 2600 ms idle
// auto-hide that never fires while paused, frame-step, speed, loop,
// snapshot, the system-player handoff with its overlay suspend/restore
// both ways, and Picture-in-Picture with its pressed-state watcher. A
// second copy of any of it would be the parallel implementation
// CLAUDE.md forbids, and the handoff paths in particular encode fixes
// for reproduced regressions.
//
// The one thing that had to change to reach it from here is the video
// element: mountPlayerChrome resolved #lightboxVideo internally,
// because the old architecture reparented one shared wrap between
// surfaces. It now takes an optional getVideo, so this package hands it
// the <video> the stage owns.

import { mountPlayerChrome } from '../mediaview/player/index.js';

/**
 * Mount the transport onto the stage.
 *
 * Live and simulation get nothing: their picture is a snapshot <img>
 * with no timeline to seek, no duration to count down and nothing to
 * hand to a system player. Returning null rather than mounting a
 * disabled row keeps a dead control off a 375 px screen.
 *
 * @param {HTMLElement} stageEl      the shell's [data-slot="stage"]
 * @param {HTMLElement} controlsHost the shell's [data-slot="controls"]
 * @param {object} cfg               normalised config from _config.js
 * @param {object} stage             handle from _stage.js
 * @returns {{sync: () => void, teardown: () => void}|null}
 */
export function mountTransport(stageEl, controlsHost, cfg, stage) {
  if (!stageEl || !stage || cfg.flags.live) return null;
  return mountPlayerChrome(stageEl, controlsHost, { getVideo: () => stage.video });
}
