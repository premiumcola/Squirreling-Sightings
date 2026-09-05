// ─── vplayer/timeline/index.js ─────────────────────────────────────────────
// Mount / update / teardown for the in-stage timeline. Composition
// only: the geometry is _model.js's, the markup is _rail.js's and
// _lanes.js's, the drag is _scrub.js's, and the live variant is
// _rolling.js's.
//
// TWO SHAPES, ONE MOUNT. A recorded clip gets lanes over a scrubbable
// rail; a live surface gets the rolling strip and no rail at all, since
// there is nothing to seek. Which one is decided by the mode's
// `timeline` flag from _config.js — never by sniffing the data.

import { TL_BASIS_LIVE, TL_BASIS_NONE } from './_basis.js';
import { emptyStateFor, emptyStateHtml, wireRescan } from './_empty-states.js';
import { lanesHtml } from './_lanes.js';
import { wireBeads } from './_markers.js';
import { railHtml, setPlayhead } from './_rail.js';
import { renderRolling } from './_rolling.js';
import { mountScrubPreview } from './_preview.js';
import { attachScrub } from './_scrub.js';
import { buildTimelineModel } from './_model.js';

/**
 * Mount the timeline into the stage's timeline slot.
 *
 * @param {HTMLElement} host  the shell's [data-slot="timeline"]
 * @param {object} cfg        normalised config from _config.js
 * @param {object} deps       { getVideo, post, reload }
 * @returns {object|null} handle with update/teardown
 */
/** Above this many lanes the block scrolls; at or below it never does.
 *  Six rows of 14 px plus gaps is ~100 px — comfortably inside the 22dvh
 *  cap, so the cap only ever engages once it is genuinely needed. */
const LANES_BEFORE_SCROLL = 6;

export function mountTimeline(host, cfg, deps = {}) {
  if (!host) return null;

  const rolling = cfg.flags.timeline === 'rolling';
  let model = buildTimelineModel([], rolling ? { windowMs: cfg.windowMs, now: 0 } : {});
  let scrub = null;
  let rescan = null;
  let preview = null;
  let beads = null;
  // Coarse pointers get the bubble lifted clear of the finger. Read once
  // per mount: a device does not change its input class mid-clip, and a
  // matchMedia listener here would outlive the player.
  // globalThis, not window: this module is imported by node tests that
  // stub a document and have no window at all.
  const _touch =
    typeof globalThis.matchMedia === 'function' &&
    globalThis.matchMedia('(pointer: coarse)').matches;

  const rail = () => host.querySelector('.vp-tl-track');
  const head = () => host.querySelector('.vp-tl-head');

  // How tall the lane block is, published to CSS so the playhead's riser
  // can reach exactly to the top of it — „Die Linie geht hoch, dadrüber
  // sind die Timelines in Farbe zu den Objekten eingezeichnet."
  //
  // Observed rather than measured once: the lane count changes when a
  // sidecar lands or a live tick adds a track, and neither of those is a
  // resize of anything else.
  let laneRo = null;
  const watchLanes = () => {
    laneRo?.disconnect();
    const lanes = host.querySelector('.vp-tl-lanes');
    if (!lanes) {
      host.style.removeProperty('--vp-tl-lanes-h');
      return;
    }
    const publish = () => {
      host.style.setProperty('--vp-tl-lanes-h', `${Math.round(lanes.offsetHeight)}px`);
    };
    publish();
    if (typeof ResizeObserver === 'function') {
      laneRo = new ResizeObserver(publish);
      laneRo.observe(lanes);
    }
  };

  /** Repaint everything that only changes when the DATA changes. */
  const render = (tracks, opts = {}) => {
    model = buildTimelineModel(tracks, { ...opts, windowMs: rolling ? cfg.windowMs : 0 });
    // WHICH population these lanes came from, on the element itself. The
    // rail can be drawn from the sidecar or from the clip aggregate and
    // the two are never mixed, so a later reader — a person in devtools,
    // or a test — must be able to tell which one is on screen without
    // guessing from the lane count.
    host.dataset.basis = rolling ? TL_BASIS_LIVE : opts.basis || TL_BASIS_NONE;
    if (rolling) {
      renderRolling(host, model);
      return model;
    }
    scrub?.teardown();
    rescan?.teardown();
    beads?.teardown();
    // `data-many` decides whether the block may scroll at all. Below the
    // threshold it must not: a reserved scrollbar gutter beside two rows
    // is a control for a list that fits. See 36b.
    const body = model.lanes.length
      ? `<div class="vp-tl-lanes" data-many="${model.lanes.length > LANES_BEFORE_SCROLL ? '1' : '0'}">` +
        `${lanesHtml(model)}</div>`
      : emptyStateHtml(emptyStateFor(opts.item, opts.tracks), opts);
    host.innerHTML = body + railHtml(model);
    watchLanes();
    preview?.teardown();
    preview = mountScrubPreview(rail(), {
      getGeometry: () => opts.item?.scrub || null,
      getDuration: () => model.duration,
      isTouch: () => _touch,
    });
    // TWO drag surfaces, one behaviour. The transparent band gives the
    // 6 px rail a 44 px target anywhere along its length; the grip
    // itself has to be draggable too, or the one thing that LOOKS
    // grabbable is the one thing that is not. Only the grip answers a
    // tap, because only the grip is the play button.
    const wire = (el, onTap) =>
      attachScrub(el, {
        getRect: () => rail()?.getBoundingClientRect() || { left: 0, width: 0 },
        getDuration: () => model.duration,
        onSeek: deps.onSeek,
        onTap,
        // Every drag position lands here, and NOTHING here decodes video.
        // The marker moves so the drag tracks the finger, and the
        // filmstrip bubble shows the frame — the picture itself catches up
        // once, on release. See _scrub.js's header for the five-second
        // backlog this replaced.
        onPreview: (t, x, phase) => {
          setPlayhead(host, t, model.duration);
          if (phase === 'end') preview?.hide();
          else if (phase === 'start') preview?.show(x, t);
          else preview?.moveTo(x, t);
        },
        isPlaying: deps.isPlaying,
        onPause: deps.onPause,
      });
    scrub = {
      parts: [wire(host.querySelector('.vp-tl-hit'), null), wire(head(), deps.onToggle)],
      teardown() {
        for (const s of this.parts) s?.teardown();
      },
    };
    rescan = wireRescan(host, deps);
    beads = wireBeads(host, { onSeek: deps.onSeek, onPause: deps.onPause });
    return model;
  };

  return {
    render,
    model: () => model,
    /** Playhead only — called every frame, so it touches one property. */
    tick: (t) => setPlayhead(host, t, model.duration),
    /** Which glyph the grip shows. An attribute, so the swap is CSS and
     *  never a re-render of the element under a dragging finger. */
    setPlaying: (on) => {
      const v = on ? '1' : '0';
      if (host.dataset.playing !== v) host.dataset.playing = v;
    },
    teardown: () => {
      scrub?.teardown();
      preview?.teardown();
      laneRo?.disconnect();
      rescan?.teardown();
      beads?.teardown();
      host.innerHTML = '';
      delete host.dataset.vpFp;
      delete host.dataset.basis;
    },
  };
}
