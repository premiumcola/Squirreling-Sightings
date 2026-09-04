// ─── vplayer/panels/_readiness-note.js ─────────────────────────────────────
// The banner that says why the picture shows what it shows — and, when
// the answer is "because a file is missing", the button that makes it.
//
// This is the half of the overlay work that is not painting. A clip with
// no `tracks.json` has no per-frame geometry, so there is no box that
// could follow a subject; the player drew nothing and said nothing, and
// the operator's question was the obvious one: „wo ist die Katze, also
// die bbox??". The honest answer — the aggregate knows WHEN the cat was
// there but never WHERE — is not something anyone should have to infer
// from an empty picture.
//
// THE MARKUP LIVES NEXT DOOR in _readiness-face.js, one builder per
// state, because a state that differs only in its sentence is labelled
// rather than designed. What is left here is behaviour: the rebuild
// request, its three outcomes, and the one clock in this package that
// has to keep moving.
//
// The rebuild route is not new: POST /api/tracking/reindex/<event_id>
// has existed all along, and the LEGACY player auto-kicked it and showed
// a banner while it ran (mediathek/bbox-overlay/reindex.js). The unified
// player inherited neither. This is that affordance, deliberately manual
// rather than automatic: re-walking a clip costs real seconds of TPU on
// a box that has exactly one, and doing it unasked on every open of an
// old archive is not a decision to make on the operator's behalf.
//
// IT IS ALSO GATED ON WHETHER THE ROUTE COULD SUCCEED. The endpoint
// answers 404 for an event with no video, so `readiness.rebuildable`
// decides — a clip whose encode failed gets the reason, not a button
// that cannot work.

import { CLIP_BUILDING } from '../_model/readiness.js';
import { elapsedLabel, readinessFaceHTML } from './_readiness-face.js';

/** How often the seconds-in-stage readout advances. */
const _TICK_MS = 1000;

/** The trailing control: a rebuild, or the outcome of one already sent. */
function _actionHTML(st) {
  if (st.failed) return `<span class="vp-rn-state">Nachbau fehlgeschlagen</span>`;
  if (st.done) return `<span class="vp-rn-state">Wird nachgebaut — gleich neu öffnen</span>`;
  if (st.busy) return `<span class="vp-rn-state">Wird angefordert …</span>`;
  if (st.readiness?.rebuildable) {
    return `<button type="button" class="vp-rn-btn" data-act="reindex">Feinspur nachbauen</button>`;
  }
  return '';
}

/**
 * Seconds this clip has spent in its current stage, right now.
 *
 * Anchored on the SERVER's `stage_age_s` (media_index/_visible.py derives
 * it on every read) plus the wall time since it arrived — never on
 * `stage_since` parsed in the browser, which would silently drift by a
 * whole timezone on any host whose clock is not the server's.
 */
function _liveAge(st) {
  if (st.rawAge == null) return null;
  return st.rawAge + (Date.now() - st.t0) / 1000;
}

/**
 * Mount the readiness note.
 *
 * @param {HTMLElement} host
 * @param {object} cfg   normalised config from _config.js
 * @param {object} deps  { request, onError }
 * @returns {{update: (r: object, item: object) => void, teardown: () => void}|null}
 */
export function renderReadinessNote(host, cfg, deps = {}) {
  if (!host) return null;
  const st = {
    readiness: null,
    item: cfg.item || null,
    busy: false,
    done: false,
    failed: false,
    rawAge: null,
    t0: Date.now(),
    timer: null,
  };

  const paint = () => {
    host.innerHTML = readinessFaceHTML(st.readiness, st.item, _actionHTML(st), _liveAge(st));
  };

  // Only the clock moves, so only the clock is rewritten. Repainting the
  // whole banner every second would rebuild the rebuild button under the
  // user's finger.
  const tick = () => {
    const el = host.querySelector?.('.vp-rn-clock');
    if (el) el.textContent = elapsedLabel(_liveAge(st));
  };

  const retime = () => {
    const running = st.readiness?.state === CLIP_BUILDING && st.rawAge != null;
    if (running && !st.timer) {
      st.timer = setInterval(tick, _TICK_MS);
      // A number in the browser, a Timeout under node — where an
      // un-unref'd interval would hold the test runner open for ever.
      st.timer?.unref?.();
    } else if (!running && st.timer) {
      clearInterval(st.timer);
      st.timer = null;
    }
  };

  const onClick = async (ev) => {
    if (ev.target?.dataset?.act !== 'reindex' || st.busy) return;
    const eventId = st.item?.event_id;
    if (!eventId) return;
    st.busy = true;
    st.failed = false;
    paint();
    try {
      // The camera hint spares the backend a walk over every camera's
      // event tree to find which one owns this id.
      const cam = st.item?.camera_id ? `?camera_id=${encodeURIComponent(st.item.camera_id)}` : '';
      await deps.request?.(`/api/tracking/reindex/${encodeURIComponent(eventId)}${cam}`, {
        method: 'POST',
      });
      st.done = true;
    } catch (err) {
      // The worker can legitimately refuse — not running, video gone.
      // Saying so beats a button that looks like it worked.
      st.failed = true;
      deps.onError?.(err?.message || 'Feinspur konnte nicht angefordert werden.');
    } finally {
      st.busy = false;
      paint();
    }
  };
  host.addEventListener('click', onClick);

  return {
    update: (readiness, item) => {
      // A new clip clears the outcome of the previous one's rebuild.
      if (readiness?.state !== st.readiness?.state) {
        st.done = false;
        st.failed = false;
      }
      if (item) st.item = item;
      const age = typeof st.item?.stage_age_s === 'number' ? st.item.stage_age_s : null;
      // Re-anchor only when the server sent a NEW reading; re-anchoring
      // on every paint would reset the clock to the same number for ever.
      if (age !== st.rawAge) {
        st.rawAge = age;
        st.t0 = Date.now();
      }
      st.readiness = readiness || null;
      retime();
      paint();
    },
    teardown: () => {
      if (st.timer) clearInterval(st.timer);
      st.timer = null;
      host.removeEventListener('click', onClick);
      host.innerHTML = '';
    },
  };
}
