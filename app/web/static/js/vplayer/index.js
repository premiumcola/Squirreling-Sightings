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
// Rollout state: ALL THREE surfaces — recorded clips, the live view and
// the simulation — run on this player by default. Every old
// implementation is still on disk and still one URL parameter away:
// ?vplayer=off forces all three back. The flag and the old code go in a
// later sweep, once this has soaked.

import { buildPlayerConfig } from './_config.js';
import { keyAction, seekTarget } from './_keys.js';
import { mountShell } from './_shell.js';
import { mountStage } from './_stage.js';
import { mountChrome, teardownChrome } from './_chrome.js';
import { mountTransport } from './_transport.js';
import { mountOverlayRow } from './_overlay-row.js';
import { makeLiveTrackBuffer } from './timeline/_live-buffer.js';
import { mountTimeline } from './timeline/index.js';
import { renderContextPanel } from './panels/index.js';
import { wireRecorded } from './_wire-recorded.js';
import { mountOverlayPainter } from './_overlay-paint.js';
import { subscribeLive } from './_data/live.js';
import { liveStatus, resetLiveStatus } from './_data/status.js';
import { installBackGesture } from './_back-gesture.js';

/** The single open player, or null. One at a time, by construction. */
let _open = null;

/**
 * Feed a live surface. The frames come from the EXISTING poll loop —
 * this only maps and paints. See _data/live.js for why owning any of
 * that loop's logic here would be the migration's worst regression.
 */
function _wireLive(cfg, stage, panel, timeline, overlays) {
  if (!cfg.flags.live) return null;
  // Only the surfaces that SHOW something from the detection loop
  // subscribe to it. The plain live view wants the continuous stream
  // its <img> is already pointed at; letting the 1 Hz snapshot poll
  // overwrite it would turn a live picture into a slideshow, which is
  // worse than the tile the operator expanded from.
  if (!cfg.flags.showPanel && !cfg.flags.showOverlays) return null;
  // The camera is what makes this a PRODUCER and not just a listener:
  // subscribeLive starts the poll loop for it and stops it on teardown.
  // Passing it is what fixes "TPU zeigt nix, ROI zeigt nix, Debug-Log
  // leer, wartet auf einen Tick, der nie kommt".
  const source = { camId: cfg.item.camera_id, cameraName: cfg.item.camera_name };
  // THE HISTORY THE BACKEND DOES NOT KEEP. A tick answers "what is in
  // this frame"; the rolling strip draws the last sixty seconds, and
  // nothing was assembling one — see timeline/_live-buffer.js.
  const history = makeLiveTrackBuffer({ windowS: (cfg.windowMs || 60000) / 1000 });
  return subscribeLive((frame) => {
    // The picture. The backend hands back the exact frame inference ran
    // on, as a base64 JPEG in the SAME coordinate space as the boxes —
    // which is why the boxes are painted against it rather than against
    // a live stream that has moved on since.
    //
    // PAINTED AFTER THE DECODE, not with the assignment. `img.src = …`
    // starts a decode; until it finishes the element still shows the
    // PREVIOUS frame. Painting synchronously here put frame N's boxes
    // over frame N−1's pixels for the whole decode, and on a moving
    // subject that is exactly „personen sind zu bboxes extrem versetzt".
    // `decode()` resolves when the new pixels are ready to present, so
    // the frame drawn on and the frame measured are the same one by
    // construction rather than by luck.
    //
    // The fallback matters as much as the happy path: no snapshot means
    // the picture is NOT the analysed frame, and boxes over it would be
    // a claim about pixels nobody has seen. Then nothing is repainted
    // and the previous, honest overlay stands.
    const paint = () => overlays?.paintLive(frame);
    if (frame.snapshot && stage.img.getAttribute('src') !== frame.snapshot) {
      stage.img.src = frame.snapshot;
      if (typeof stage.img.decode === 'function') {
        stage.img.decode().then(paint, paint);
      } else {
        stage.img.addEventListener('load', paint, { once: true });
      }
    } else if (frame.snapshot) {
      // Byte-identical snapshot: already on screen, nothing to wait for.
      paint();
    }
    // The second argument is the SYSTEM status, not part of the frame:
    // the tick says which device ran it, /api/status says how loaded that
    // device is, and the panel's TPU chip reads the latter. It was hard
    // wired to `null` here, so that chip could only ever print a
    // placeholder — a defect quite separate from the loop not running,
    // and one that would have outlived the fix for it. liveStatus()
    // returns synchronously off a cache and refreshes itself at most
    // every 8 s, so this adds no second poller and never delays a paint.
    panel?.update(frame, liveStatus());
    // The rolling window is right-anchored on now, so every tick moves
    // it whether or not a detection landed.
    //
    // `frame.tracks` used to be the argument here, and `mapFrame` has
    // never produced such a key — so this was `[]` on every tick since
    // the strip existed, on the live view and in the simulation alike.
    // The history is folded in first, then drawn.
    const nowS = Date.now() / 1000;
    history.push(frame, nowS);
    timeline?.render(history.tracks(), { now: nowS, item: cfg.item });
  }, source);
}

/**
 * Drive everything that follows the playhead from the <video>.
 *
 * The timeline exposed `tick` from its first commit and NOTHING ever
 * called it, so the head sat at zero and the clock read "0:00 / −0:00"
 * for the whole clip however long it played — „Laufzeit-Knopf bewegt
 * sich nicht, es steht auch keine Abspielzeit an". The overlay painter
 * has the same dependency: a box interpolated at t only moves if
 * something tells it t changed.
 *
 * `timeupdate` fires ~4×/s while playing; `seeked` and `loadedmetadata`
 * cover the two moments it does not — a scrub while paused, and the
 * duration arriving after the first paint.
 */
function _wirePlayhead(cfg, stage, timeline, overlays) {
  if (cfg.flags.live) return null;
  const video = stage.video;
  const sync = () => {
    const t = video.currentTime || 0;
    timeline?.tick(t);
    overlays?.repaintAt(t);
  };

  // WHILE PLAYING, THE FRAME LOOP DRIVES IT. `timeupdate` fires about
  // four times a second, so a head driven by it advances in visible
  // jumps — „der Sekundenzeiger springt pro Sekunde komplett schnell
  // weiter. Der soll flüssig fließen." requestAnimationFrame ticks with
  // the display instead, and costs nothing when the clip is paused
  // because the loop is not running then.
  let raf = 0;
  const frame = () => {
    sync();
    raf = requestAnimationFrame(frame);
  };
  const start = () => {
    timeline?.setPlaying(true);
    if (!raf) raf = requestAnimationFrame(frame);
  };
  const stop = () => {
    timeline?.setPlaying(false);
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    // One last sync so the head lands exactly on the paused position
    // rather than wherever the cancelled frame left it.
    sync();
  };

  video.addEventListener('play', start);
  video.addEventListener('playing', start);
  video.addEventListener('pause', stop);
  video.addEventListener('ended', stop);
  // The moments no frame loop covers: a scrub while paused, and the
  // duration arriving after the first paint.
  video.addEventListener('seeked', sync);
  video.addEventListener('loadedmetadata', sync);
  if (!video.paused) start();
  else timeline?.setPlaying(false);
  sync();

  return {
    teardown: () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      video.removeEventListener('play', start);
      video.removeEventListener('playing', start);
      video.removeEventListener('pause', stop);
      video.removeEventListener('ended', stop);
      video.removeEventListener('seeked', sync);
      video.removeEventListener('loadedmetadata', sync);
    },
  };
}

/**
 * Start the clip the moment it is opened.
 *
 * Opening a clip IS the request to watch it — „logisch, wenn ich
 * draufklicke, will ich's anschauen" — so there is no first tap on a
 * play button any more. The open runs inside the click that asked for
 * it, which is the gesture browsers require, so an unmuted start is
 * normally permitted.
 *
 * A refusal gets ONE muted retry and then silence, deliberately: a
 * picture playing without sound is much closer to what was asked for
 * than an error toast about audio nobody asked to hear, and if both
 * attempts fail the transport's own play button is sitting on the
 * picture. This is the one play() in the package allowed to swallow its
 * rejection — the button's own handler still reports failures, because
 * there a dead press has nothing else to explain it.
 */
function _autoplay(video) {
  if (!video) return;
  video.play().catch(() => {
    video.muted = true;
    video.play().catch(() => {});
  });
}

/**
 * Turn a swallowed key into something happening to the video.
 *
 * The mapping itself is in _keys.js and is pure; this is the half that
 * touches the element. A LIVE surface gets Escape and nothing else —
 * there is no position to seek in a stream, and Space toggling a
 * <video> that is not the live <img> would look like a broken key.
 */
function _keyHandler(cfg, stage) {
  return (key, ev) => {
    const action = keyAction(key, { shift: ev?.shiftKey === true });
    if (!action) return;
    if (action.type === 'close') {
      closeVideoPlayer();
      return;
    }
    const v = stage?.video;
    if (!v || cfg.flags.live) return;
    if (action.type === 'toggle') {
      if (v.paused || v.ended) v.play().catch(() => {});
      else v.pause();
      return;
    }
    const t = seekTarget(action, v.currentTime, v.duration);
    if (t != null) v.currentTime = t;
  };
}

/** Compose the shell's parts. Kept apart so openVideoPlayer stays thin. */
function _mountAll(cfg) {
  // The shell installs the key trap at mount, before the stage it needs
  // to act on exists. So it calls through this holder, which is filled in
  // once there IS a video — a press that lands in the gap does nothing,
  // which is what it did before anyway.
  let onKey = (key) => key === 'Escape' && closeVideoPlayer();
  const shell = mountShell(cfg, { onKey: (key, ev) => onKey(key, ev) });
  const stage = mountStage(shell.slot('frame'), cfg);
  const chrome = mountChrome(shell, cfg, stage, { onClose: () => closeVideoPlayer() });
  // The painter first, so the row can push the operator's choice into
  // it; then the row's own resolved state back into the painter, because
  // a persisted "trails off" wins over the mode's default and the
  // picture must start out matching the buttons.
  const overlays = mountOverlayPainter(stage, cfg);
  // THE SHELL'S OWN ROW, below the picture — `data-slot="toggles"` is a
  // sibling AFTER `.vp-stage` and 36a already styles it as a row.
  //
  // It used to be a node created here, absolutely positioned onto the
  // stage with `vp-toggles--onstage`, so four pills sat permanently over
  // the footage on every surface: „In der SIMU ist es schlecht, dass die
  // Buttons dauerhaft über dem Video liegen." The timeline learned this
  // exact lesson already — 36b's header explains at length why it stopped
  // being a scrim over the picture — and these cameras burn their own
  // clock into the frame, so anything floating over it is competing with
  // the footage for the same pixels.
  //
  // Handing over the shell's empty slot is safe in the way the stage slot
  // never was: mountOverlayRow assigns `host.innerHTML`, which on the
  // stage would have wiped the <video>, the overlay layers and the
  // timeline in one statement. This slot owns nothing.
  const togglesHost = cfg.flags.showOverlays ? shell.slot('toggles') : null;
  const overlayRow = cfg.flags.showOverlays
    ? mountOverlayRow(togglesHost, cfg, {
        onChange: (next) => overlays?.setLayers(next),
      })
    : null;
  if (overlayRow) {
    overlays?.setLayers(overlayRow.state());
    // The painter is the only thing that knows a repaint HAD boxes and
    // withheld them; the row is the only thing that can offer them back.
    overlays?.onBoxesHidden((n) => overlayRow.setHiddenBoxes(n));
  }
  const transport = mountTransport(shell.slot('stage'), shell.slot('controls'), cfg, stage);
  const timeline = mountTimeline(shell.slot('timeline'), cfg, {
    onSeek: (t) => {
      stage.video.currentTime = t;
    },
    isPlaying: () => !stage.video.paused && !stage.video.ended,
    onPause: () => stage.video.pause(),
    // The playhead IS the play button, so a press on it that never moved
    // toggles playback instead of seeking to where it already sits.
    //
    // `wasPlaying` is the state BEFORE the press paused it. Reading
    // `stage.video.paused` here instead would always see "paused" — the
    // pointerdown just did that — and start the clip again, so pressing
    // pause on a running clip did nothing at all.
    onToggle: (wasPlaying) => {
      // It was running and the press already stopped it. Leave it
      // stopped; that IS the pause.
      if (wasPlaying) return;
      stage.video.play().catch(() => {});
    },
  });

  onKey = _keyHandler(cfg, stage);

  const playhead = _wirePlayhead(cfg, stage, timeline, overlays);

  // A live surface with a stream URL points its <img> straight at it, so
  // the picture is continuous rather than a 1 Hz snapshot loop.
  //
  // NOT ON A SURFACE THAT DRAWS BOXES. The stream is the camera's HD
  // feed, decoded by a different pipeline and always AHEAD of the frame
  // inference ran on; the simulation would then paint measured boxes
  // over pixels nobody measured. That is a picture claiming a
  // correspondence it does not have — and the simulation exists to show
  // the correspondence. It waits for its first snapshot instead; on this
  // box that is one tick.
  if (cfg.flags.live && cfg.source?.url && !cfg.flags.showOverlays) {
    stage.img.src = cfg.source.url;
  }

  // A mutable slot rather than a callback chain: the panel is built now,
  // the timeline's repainter only exists once loadRecorded has answered
  // (async), and the panel looks the slot up at save time — by then it is
  // filled. Empty stays harmless: a live/sim player never fills it.
  const relanes = { run: () => {} };
  const panelDeps = {
    ...(cfg.deps || {}),
    onSaved: (res, labels) => {
      // The rail is drawn from the same detection rows the correction
      // just rewrote — repaint it BEFORE handing the reply outward, so
      // the player the operator is looking at is never the last surface
      // to catch up.
      relanes.run();
      cfg.deps?.onSaved?.(res, labels);
    },
  };
  const panel = renderContextPanel(shell.slot('panel'), cfg, null, panelDeps);
  const live = _wireLive(cfg, stage, panel, timeline, overlays);
  if (!cfg.flags.live && cfg.source?.url) {
    stage.video.src = cfg.source.url;
    _autoplay(stage.video);
  }
  wireRecorded(cfg, stage, panel, timeline, overlays, relanes);

  return {
    cfg,
    shell,
    stage,
    chrome,
    overlays,
    overlayRow,
    playhead,
    transport,
    timeline,
    panel,
    live,
  };
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
  // The open player is a history entry, so the phone's own back gesture
  // closes it instead of leaving the app — see _back-gesture.js.
  _open.backGesture = installBackGesture(_open.shell?.root, () => closeVideoPlayer());
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
  resetLiveStatus();
  p.panel?.teardown();
  p.timeline?.teardown();
  p.transport?.teardown();
  p.overlayRow?.teardown();
  // NOT `togglesHost.remove()`. That line was written for a node this
  // file created and appended to the stage itself; the row now lives in
  // the shell's own `data-slot="toggles"`, and removing it would tear a
  // slot out of the skeleton — the next open would find no host for the
  // switches. `overlayRow.teardown()` already empties it, and the shell
  // is discarded whole a few lines below.
  p.playhead?.teardown();
  p.overlays?.teardown();
  teardownChrome(p.chrome);
  p.stage?.teardown();
  // Before the shell goes: the gesture is bound to its root, and the
  // teardown also pops the history entry this open pushed.
  p.backGesture?.();
  p.shell?.teardown();
  p.cfg.actions.onClose?.();
}
