// ─── vplayer/panels/_readiness-note.js ─────────────────────────────────────
// One line that says why the picture shows what it shows — and, when the
// answer is "because a file is missing", the button that makes it.
//
// This is the half of the overlay work that is not painting. A clip with
// no `tracks.json` has no per-frame geometry, so there is no box that
// could follow a subject; the player drew nothing and said nothing, and
// the operator's question was the obvious one: „wo ist die Katze, also
// die bbox??". The honest answer — the aggregate knows WHEN the cat was
// there but never WHERE — is not something anyone should have to infer
// from an empty picture.
//
// The rebuild route is not new: POST /api/tracking/reindex/<event_id>
// has existed all along, and the LEGACY player auto-kicked it and showed
// a banner while it ran (mediathek/bbox-overlay/reindex.js). The unified
// player inherited neither. This is that affordance, deliberately manual
// rather than automatic: re-walking a clip costs real seconds of TPU on
// a box that has exactly one, and doing it unasked on every open of an
// old archive is not a decision to make on the operator's behalf.

import { esc } from '../../core/dom.js';
import { CLIP_COARSE, CLIP_EMPTY, CLIP_MISSING, CLIP_PENDING } from '../_model/readiness.js';

/** Which states offer a rebuild — the two where a sidecar is absent. */
const _REBUILDABLE = new Set([CLIP_COARSE, CLIP_MISSING]);

/** Severity class per state, so an answer and a gap do not look alike. */
const _TONE = {
  [CLIP_COARSE]: 'is-partial',
  [CLIP_MISSING]: 'is-partial',
  [CLIP_EMPTY]: 'is-quiet',
  [CLIP_PENDING]: 'is-quiet',
};

function _markup(readiness, busy, done, failed) {
  if (!readiness || !readiness.note) return '';
  const tone = _TONE[readiness.state] || 'is-quiet';
  let action = '';
  if (failed) {
    action = `<span class="vp-rn-state">Nachbau fehlgeschlagen</span>`;
  } else if (done) {
    action = `<span class="vp-rn-state">Wird nachgebaut — gleich neu öffnen</span>`;
  } else if (busy) {
    action = `<span class="vp-rn-state">Wird angefordert …</span>`;
  } else if (_REBUILDABLE.has(readiness.state)) {
    action = `<button type="button" class="vp-rn-btn" data-act="reindex">Feinspur nachbauen</button>`;
  }
  return (
    `<div class="vp-rn ${tone}">` +
    `<span class="vp-rn-text">${esc(readiness.note)}</span>${action}` +
    `</div>`
  );
}

/**
 * Mount the readiness note.
 *
 * @param {HTMLElement} host
 * @param {object} cfg   normalised config from _config.js
 * @param {object} deps  { request, onError }
 * @returns {{update: (r: object) => void, teardown: () => void}|null}
 */
export function renderReadinessNote(host, cfg, deps = {}) {
  if (!host) return null;
  const st = { readiness: null, busy: false, done: false, failed: false };

  const paint = () => {
    host.innerHTML = _markup(st.readiness, st.busy, st.done, st.failed);
  };

  const onClick = async (ev) => {
    if (ev.target?.dataset?.act !== 'reindex' || st.busy) return;
    const eventId = cfg.item.event_id;
    if (!eventId) return;
    st.busy = true;
    st.failed = false;
    paint();
    try {
      // The camera hint spares the backend a walk over every camera's
      // event tree to find which one owns this id.
      const cam = cfg.item.camera_id ? `?camera_id=${encodeURIComponent(cfg.item.camera_id)}` : '';
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
    update: (readiness) => {
      // A new clip clears the outcome of the previous one's rebuild.
      if (readiness?.state !== st.readiness?.state) {
        st.done = false;
        st.failed = false;
      }
      st.readiness = readiness || null;
      paint();
    },
    teardown: () => {
      host.removeEventListener('click', onClick);
      host.innerHTML = '';
    },
  };
}
