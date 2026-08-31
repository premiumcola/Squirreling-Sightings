// ─── mediaview/player/index.js ─────────────────────────────────────────────
// Public face of the recorded-clip player chrome — the piece that makes
// our in-page player feel like the one iOS ships, so the operator has a
// reason to stay in it and keep the detection overlay.
//
// Composition (all three ride the shell's existing stage; nothing new is
// added to modals.html):
//
//   _transport.js  centre −10 / play-pause / +10 discs + the elapsed /
//                  −remaining strip + the system-player switch.
//   _autohide.js   chrome fades during playback, returns on tap or mouse
//                  move, never hides while paused.
//   _native.js     the handoff itself and — the part that actually needs
//                  care — the trip back: overlay layers and the RAF loop
//                  restored, whichever way the operator left fullscreen.
//
// The overlay-toggle pills and the mode badge the shell already pins to
// the stage corners join the auto-hide group via CSS (30h), so the whole
// set reads as one player's chrome rather than a control strip that
// happens to sit near a video.

import { byId } from '../../core/dom.js';
import { installChromeAutoHide } from './_autohide.js';
import { renderTransport } from './_transport.js';
import { renderTransportControls } from './_transport-controls.js';
import {
  canNativeFullscreen,
  handoffToNativePlayer,
  resumeOverlayAfterNative,
  suspendOverlayForNative,
  watchNativeFullscreen,
} from './_native.js';

/**
 * Mount the player chrome onto a MediaView stage.
 *
 * The media element is #lightboxVideo, not a parameter: recorded-mode.js
 * REPARENTS the legacy #lightboxMediaWrap into the stage rather than
 * building a fresh player (its header comment says why — the painter,
 * the zone overlay and the scrubber are all bound to those ids at module
 * load). Resolved per call so the lookup survives the reparenting.
 *
 * @param {HTMLElement} stage         the shell's [data-slot="stage"] node
 * @param {HTMLElement} [controlsHost]  the shell's [data-slot="controls"]
 *   node — hosts Transport v2's below-stage row (speed / frame-step /
 *   loop / detection-nav / snapshot). Optional so a caller with no such
 *   slot still gets the core transport; renderTransportControls itself
 *   no-ops on a missing host.
 * @returns {{ sync(): void, teardown(): void }|null}
 */
export function mountPlayerChrome(stage, controlsHost) {
  if (!stage) return null;
  const getVideo = () => byId('lightboxVideo');
  const video = getVideo();

  const host = document.createElement('div');
  host.className = 'mv-player';
  stage.appendChild(host);

  const autoHide = installChromeAutoHide(stage, getVideo);
  const transport = renderTransport(host, {
    getVideo,
    nativeAvailable: canNativeFullscreen(video),
    onInteract: () => autoHide?.reveal(),
    onNative: () => handoffToNativePlayer(getVideo()),
  });
  const transportControls = renderTransportControls(controlsHost, { getVideo });

  // Fullscreen can also be entered/left without our button — the native
  // controls' own affordance, Esc, the iOS swipe-down. One watcher covers
  // every route so the overlay state can never disagree with what the
  // operator is looking at.
  const unwatch = watchNativeFullscreen(video, {
    onEnter: (v) => suspendOverlayForNative(v),
    onExit: (v) => {
      resumeOverlayAfterNative(v);
      transport?.sync();
      transportControls?.sync();
      autoHide?.reveal();
    },
  });

  return {
    sync: () => {
      transport?.sync();
      transportControls?.sync();
    },
    teardown: () => {
      try {
        unwatch();
      } catch {
        /* ignore */
      }
      // Leaving the modal while the wrap still carries the native-fs flag
      // would hide the overlay layers for the NEXT clip too — the flag
      // lives on the reused #lightboxMediaWrap, which outlives this shell.
      try {
        resumeOverlayAfterNative(getVideo());
      } catch {
        /* ignore */
      }
      transportControls?.teardown();
      transport?.teardown();
      autoHide?.teardown();
      host.remove();
    },
  };
}
