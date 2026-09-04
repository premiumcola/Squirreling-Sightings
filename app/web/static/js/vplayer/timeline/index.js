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
export function mountTimeline(host, cfg, deps = {}) {
  if (!host) return null;

  const rolling = cfg.flags.timeline === 'rolling';
  let model = buildTimelineModel([], rolling ? { windowMs: cfg.windowMs, now: 0 } : {});
  let scrub = null;
  let rescan = null;
  let preview = null;
  // Coarse pointers get the bubble lifted clear of the finger. Read once
  // per mount: a device does not change its input class mid-clip, and a
  // matchMedia listener here would outlive the player.
  // globalThis, not window: this module is imported by node tests that
  // stub a document and have no window at all.
  const _touch =
    typeof globalThis.matchMedia === 'function' &&
    globalThis.matchMedia('(pointer: coarse)').matches;

  const rail = () => host.querySelector('.vp-tl-track');

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
    const body = model.lanes.length
      ? `<div class="vp-tl-lanes">${lanesHtml(model)}</div>`
      : emptyStateHtml(emptyStateFor(opts.item, opts.tracks), opts);
    host.innerHTML = body + railHtml(model);
    watchLanes();
    preview?.teardown();
    preview = mountScrubPreview(rail(), {
      getGeometry: () => opts.item?.scrub || null,
      getDuration: () => model.duration,
      isTouch: () => _touch,
    });
    scrub = attachScrub(host.querySelector('.vp-tl-hit'), {
      getRect: () => rail()?.getBoundingClientRect() || { left: 0, width: 0 },
      getDuration: () => model.duration,
      onSeek: deps.onSeek,
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
      onResume: deps.onResume,
    });
    rescan = wireRescan(host, deps);
    return model;
  };

  return {
    render,
    model: () => model,
    /** Playhead only — called every frame, so it touches one property. */
    tick: (t) => setPlayhead(host, t, model.duration),
    teardown: () => {
      scrub?.teardown();
      preview?.teardown();
      laneRo?.disconnect();
      rescan?.teardown();
      host.innerHTML = '';
      delete host.dataset.vpFp;
      delete host.dataset.basis;
    },
  };
}
