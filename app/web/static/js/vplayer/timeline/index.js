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

  const rail = () => host.querySelector('.vp-tl-track');

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
    scrub = attachScrub(host.querySelector('.vp-tl-hit'), {
      getRect: () => rail()?.getBoundingClientRect() || { left: 0, width: 0 },
      getDuration: () => model.duration,
      onSeek: deps.onSeek,
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
      rescan?.teardown();
      host.innerHTML = '';
      delete host.dataset.vpFp;
      delete host.dataset.basis;
    },
  };
}
