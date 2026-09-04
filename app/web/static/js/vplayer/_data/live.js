// ─── vplayer/_data/live.js ─────────────────────────────────────────────────
// A THIN ADAPTER over mediaview/live-detect-poll.js. It owns NO polling
// logic whatsoever, and that is the single most important property of
// this file. It subscribes, maps through _map.js, and stops.
//
// What the existing loop encodes — all of it fixes for reproduced
// regressions, none of it re-derivable by reading the happy path:
//
//   · the in-flight / no-abort contract: a request younger than 30 s is
//     never aborted, because Flask cannot cancel its own handler, so
//     aborting the client side only abandons a worker that is still
//     holding the TPU;
//   · the adaptive cadence and the cycle EMA that paces it;
//   · the CONTACT-vs-PACE watchdog split, which tells "the backend
//     stopped answering" apart from "the backend is answering slowly";
//   · three DIFFERENT 429/503 branches — busy, mode_too_expensive and
//     frame failure — needing three messages and three recoveries,
//     including the "auf Aus zurückschalten" escape from a mode the
//     hardware cannot sustain;
//   · the hold-time bbox fade.
//
// Re-implementing any of it here would be the parallel implementation
// CLAUDE.md forbids and the highest-probability silent regression in
// this migration.

import { onLiveFrame } from '../../mediaview/live-detect-poll.js';
import {
  startHeadlessLiveSession,
  stopHeadlessLiveSession,
} from '../../mediaview/live-detect-session.js';
import { mapFrame } from './_map.js';

/**
 * Subscribe to the live loop — AND start it.
 *
 * Starting it is the half that was missing, and it is why the whole
 * simulation surface was dead. This adapter used to only register an
 * observer, on the reasonable assumption that something else ran the
 * loop: in the legacy world `openLiveDetect()` did, as a side effect of
 * mounting its chrome. `dashboard.js::_cvOpenSim` stopped calling that
 * the moment it began routing to the new player, and nothing took the
 * job over. Nobody noticed because the picture is a separate MJPEG
 * stream that keeps playing regardless — so the surface looked alive
 * while its panel read "Warte auf ersten Tick …" indefinitely.
 *
 * A subscriber that starts its own producer cannot regress that way: if
 * the loop is not running, this function is not running either.
 *
 * @param {(frame: object) => void} onFrame  receives a mapped frame
 * @param {{camId?: string, cameraName?: string}} [opts]  which camera to
 *   poll. Omitted for a surface that only wants to watch a loop someone
 *   else owns — then this behaves exactly as it did before.
 * @returns {{teardown: () => void}}
 */
export function subscribeLive(onFrame, opts = {}) {
  const off = onLiveFrame((data) => onFrame(mapFrame(data)));
  const owned = opts.camId ? startHeadlessLiveSession(opts) : false;
  return {
    teardown: () => {
      // Unsubscribe BEFORE stopping, so a frame that lands mid-teardown
      // cannot reach a panel that is already gone.
      off();
      if (owned) stopHeadlessLiveSession();
    },
  };
}
