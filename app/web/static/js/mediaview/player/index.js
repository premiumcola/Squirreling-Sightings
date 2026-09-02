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
import { canPictureInPicture, togglePictureInPicture, watchPictureInPicture } from './_pip.js';

/**
 * Watch both hand-off surfaces (native fullscreen + Picture-in-Picture)
 * at once and return one combined teardown. Extracted out of
 * mountPlayerChrome so that function stays under the file's own 60-line
 * ceiling. Both surfaces share the same overlay problem (a promoted
 * <video> can't be followed by its SVG/canvas siblings) and so share
 * the exact same onEnter/onExit reaction — suspend or restore the
 * overlay, re-sync the two control rows, and (on the way back only, so
 * the operator sees the chrome again where they left off) reveal the
 * auto-hidden chrome. PiP's onEnter additionally re-syncs the transport
 * immediately, because unlike fullscreen — where the outgoing surface
 * disappears entirely — the transport (with its own PiP toggle) stays
 * visible and interactive while the video floats, so its pressed state
 * has to flip right away, not just on the way out.
 */
function _watchHandoffSurfaces(video, { transport, transportControls, autoHide }) {
  const onExit = (v) => {
    resumeOverlayAfterNative(v);
    transport?.sync();
    transportControls?.sync();
    autoHide?.reveal();
  };
  const unwatchFs = watchNativeFullscreen(video, {
    onEnter: (v) => suspendOverlayForNative(v),
    onExit,
  });
  const unwatchPip = watchPictureInPicture(video, {
    onEnter: (v) => {
      suspendOverlayForNative(v);
      transport?.sync();
    },
    onExit,
  });
  return () => {
    try {
      unwatchFs();
    } catch {
      /* ignore */
    }
    try {
      unwatchPip();
    } catch {
      /* ignore */
    }
  };
}

/**
 * Mount the player chrome onto a MediaView stage.
 *
 * The media element DEFAULTS to #lightboxVideo because recorded-mode.js
 * REPARENTS the legacy #lightboxMediaWrap into the stage rather than
 * building a fresh player (its header comment says why — the painter,
 * the zone overlay and the scrubber are all bound to those ids at module
 * load). Resolved per call so the lookup survives the reparenting.
 *
 * A caller that owns its own <video> passes `getVideo` instead, which is
 * the whole point of the parameter: the transport discs, idle auto-hide,
 * frame-step, speed, loop, snapshot, native handoff and PiP are a large
 * and well-tested body of behaviour, and a second player that could not
 * reach them would have to reimplement all of it.
 *
 * NOTE for such a caller: _native.js still resolves the overlay host it
 * flags during a native handoff by #lightboxMediaWrap, so a video
 * mounted outside that wrap gets the legacy element. A caller with its
 * own overlay layers therefore has to suspend them itself.
 *
 * @param {HTMLElement} stage         the shell's [data-slot="stage"] node
 * @param {HTMLElement} [controlsHost]  the shell's [data-slot="controls"]
 *   node — hosts Transport v2's below-stage row (speed / frame-step /
 *   loop / detection-nav / snapshot). Optional so a caller with no such
 *   slot still gets the core transport; renderTransportControls itself
 *   no-ops on a missing host.
 * @param {object} [opts]
 * @param {() => (HTMLVideoElement|null)} [opts.getVideo]  resolver for the
 *   media element, called per use. Defaults to the #lightboxVideo lookup.
 * @returns {{ sync(): void, teardown(): void }|null}
 */
export function mountPlayerChrome(stage, controlsHost, opts = {}) {
  if (!stage) return null;
  const getVideo = opts.getVideo || (() => byId('lightboxVideo'));
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
    pipAvailable: canPictureInPicture(video),
    onPip: () => togglePictureInPicture(getVideo()),
  });
  const transportControls = renderTransportControls(controlsHost, { getVideo });

  // Both hand-off surfaces (system player, Picture-in-Picture) can also
  // be entered/left without our own buttons — native controls' own
  // affordances, Esc, the iOS swipe-down, a right-click "Picture in
  // Picture". One combined watcher covers every route for both so the
  // overlay state can never disagree with what the operator is looking
  // at, regardless of how they got there.
  const unwatch = _watchHandoffSurfaces(video, { transport, transportControls, autoHide });

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
