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
import { mountTopbar } from './_topbar.js';
import { mountTransport } from './_transport.js';
import { mountOverlayRow } from './_overlay-row.js';
import { mountStageChrome } from './_stage-chrome.js';
import {
  buildOverflowItems,
  mountOverflowMenu,
  VP_MENU_DELETE,
  VP_MENU_NATIVE,
} from './_overflow-menu.js';
import { canNativeFullscreen, handoffToNativePlayer } from '../mediaview/player/_native.js';
import { timelineBasis } from './timeline/_basis.js';
import { mountTimeline } from './timeline/index.js';
import { renderContextPanel } from './panels/index.js';
import { mountOverlayPainter } from './_overlay-paint.js';
import { subscribeLive } from './_data/live.js';
import { liveStatus, resetLiveStatus } from './_data/status.js';
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
  return subscribeLive((frame) => {
    // The picture. The backend hands back the exact frame inference ran
    // on, as a base64 JPEG in the SAME coordinate space as the boxes —
    // which is why the boxes are painted against it rather than against
    // a live stream that has moved on since.
    if (frame.snapshot && stage.img.getAttribute('src') !== frame.snapshot) {
      stage.img.src = frame.snapshot;
    }
    // Through the painter, not straight at the layer: it is what holds
    // the operator's toggle state, and a direct paint here is how the
    // simulation's own bbox switch ended up with nothing to switch.
    overlays?.paintLive(frame);
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
    timeline?.render(frame.tracks || [], { now: Date.now() / 1000, item: cfg.item });
  }, source);
}

/**
 * Load a recorded clip's data and paint the panel and the timeline
 * with it. Fire-and-forget: the shell is already up, so the picture
 * plays while the sidecar is still in flight.
 */
function _wireRecorded(cfg, stage, panel, timeline, overlays) {
  if (cfg.flags.live) return;
  loadRecorded(cfg.item)
    .then((data) => {
      panel?.update(data);
      const p = data.provenance || {};
      const rs = cfg.item.recording_settings || {};
      const timing = p.timing || {};
      // The boxes come from the same sidecar the lanes do, so a lane and
      // the box it explains are one subject in one colour. The sidecar's
      // own gate wins over the caller's threshold inside setTracks.
      overlays?.setTracks(data.tracks, {
        threshold: p.effective?.spawn_default,
        item: data.item || cfg.item,
      });
      // The WIDENED item, not cfg.item: loadRecorded folds a `whole_clip`
      // recovered from /api/event/<id> into its copy, and a clip opened
      // from a narrow route would otherwise be told it has no aggregate
      // by the very object that just fetched one.
      const item = data.item || cfg.item;
      // ONE basis per render, chosen once — the sidecar's tracks when it
      // has any, else lanes synthesised from the clip aggregate. Never
      // both: see timeline/_basis.js for why merging them would lie.
      // THE MEASUREMENT WINS OVER THE INTENTION, and the order used to be
      // the other way round — which is the whole of „wieso kein Vor- und
      // Nachlauf!???".
      //
      // `provenance.timing.pre_roll_s` is what the pre-roll was CONFIGURED
      // as (3 s on every camera here). `recording_settings.pre_motion_seconds`
      // is what the splice actually ACHIEVED — _finalize.py writes
      // `round(achieved_pre_s, 2)` into it after the ring has been spliced
      // onto the clip. Reading the configured number first meant the rail
      // drew a 3 s band onto clips that contain no pre-roll at all: every
      // clip in this archive reports an achieved pre-roll of 0.0.
      //
      // The details fold keeps showing the configured value, correctly —
      // there it is labelled as the setting. Here the rail is a picture of
      // the clip, so it may only draw what the clip has.
      const preRoll = rs.pre_motion_seconds ?? timing.pre_roll_s;
      // The trigger frame sits at the END of the pre-roll — that is what
      // a pre-roll IS. Only the third basis uses it, and only when the
      // sidecar and the aggregate are both empty.
      const { basis, tracks } = timelineBasis(item, data.tracks, { triggerT: preRoll });
      const render = () =>
        timeline?.render(tracks, {
          duration: stage.video.duration,
          preRoll,
          // Same rule, same reason: the clip's own number first.
          postRoll: rs.post_motion_seconds ?? timing.post_roll_s,
          threshold: p.effective?.spawn_default ?? rs.conf_thresh_general,
          basis,
          item,
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
 * The top bar and the overflow menu it triggers. One helper because they
 * share a slot and a trigger element, and because splitting them off is
 * what keeps _mountAll under the 60-line ceiling.
 */
function _mountChrome(shell, cfg, stage) {
  const topbar = mountTopbar(shell.slot('topbar'), cfg, {
    onClose: () => closeVideoPlayer(),
  });
  // prev/next live on the picture now, not in the title row.
  const stageChrome = mountStageChrome(shell.slot('stage'), cfg, {
    onPrev: cfg.actions.onPrev,
    onNext: cfg.actions.onNext,
  });
  const items = buildOverflowItems(cfg, {
    nativeAvailable: !cfg.flags.live && canNativeFullscreen(stage.video),
  });
  const menu = mountOverflowMenu(shell.slot('topbar'), topbar?.trigger, items, (id) =>
    _onMenuPick(id, cfg, stage),
  );
  return { topbar, menu, stageChrome };
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
  const { topbar, menu, stageChrome } = _mountChrome(shell, cfg, stage);
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
        roi: cfg.item.roi_label,
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

  // A live surface with a stream URL points its <img> straight at it,
  // so the picture is continuous rather than a 1 Hz snapshot loop.
  if (cfg.flags.live && cfg.source?.url) stage.img.src = cfg.source.url;

  const panel = renderContextPanel(shell.slot('panel'), cfg, null, cfg.deps || {});
  const live = _wireLive(cfg, stage, panel, timeline, overlays);
  if (!cfg.flags.live && cfg.source?.url) {
    stage.video.src = cfg.source.url;
    _autoplay(stage.video);
  }
  _wireRecorded(cfg, stage, panel, timeline, overlays);

  return {
    cfg,
    shell,
    stage,
    topbar,
    menu,
    stageChrome,
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
  p.menu?.teardown();
  p.stageChrome?.teardown();
  p.topbar?.teardown();
  p.stage?.teardown();
  p.shell?.teardown();
  p.cfg.actions.onClose?.();
}
