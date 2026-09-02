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
  // Two deliberate omissions, both straight from the approved design.
  //
  // No below-stage row. `controlsHost` is passed as null, so the toolkit's
  // speed / frame-step / loop / detection-nav / snapshot bar never mounts.
  // Every one of those was struck from the design — "Geschwindigkeit
  // brauch ich nicht … Screenshot brauche ich auch nicht" — and shipping
  // it anyway put a second control row under a 375 px screen that already
  // had one, pushing the objects list below the fold.
  //
  // No handoff pills. "Im Systemplayer öffnen" lives in the ⋯ menu
  // (_overflow-menu.js), which is where the design put it; rendering it a
  // second time inside the time strip showed the same action twice and,
  // on a phone, overlapped the elapsed / remaining readouts it shares
  // that row with. Picture-in-Picture goes with it for the same reason.
  return mountPlayerChrome(stageEl, null, {
    getVideo: () => stage.video,
    handoffPills: false,
  });
}
