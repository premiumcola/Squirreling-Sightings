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
import { mapFrame } from './_map.js';

/**
 * Subscribe to the live loop.
 *
 * @param {(frame: object) => void} onFrame  receives a mapped frame
 * @returns {{teardown: () => void}}
 */
export function subscribeLive(onFrame) {
  const off = onLiveFrame((data) => onFrame(mapFrame(data)));
  return { teardown: off };
}
