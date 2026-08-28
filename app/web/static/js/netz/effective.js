// ─── netz/effective.js ─────────────────────────────────────────────────────
// Read-only, cached access to the EFFECTIVE thresholds, for panels
// outside the Netz page that need to show the line the pipeline applies.
//
// This is the public half of the package — hence no underscore. It
// exists because the live-detect panel used to print
// `cam.detection_min_score || 0.55` as the "Settings-Limit": the global
// processing default, five points above the real spawn
// (TRACK_SPAWN_SCORE 0.50), on the one panel whose job is to explain
// whether a detection cleared the bar.
//
// The lookup is SYNCHRONOUS because its callers render inside an
// animation frame. It answers from cache and kicks off a background
// refresh on a miss; until the first answer arrives it returns the
// shipped factory value for that class — which is the honest fallback,
// since E = 50 IS the factory behaviour. Never 0.55, which was nobody's
// value.

import { fetchState } from './_api.js';
import { pushFor, spawnFor, E_FACTORY } from './_mapping.js';

const _cache = new Map(); // camId -> {axes: Map(label -> axis), ts}
const _inflight = new Set();
// A camera's thresholds change on a drag or once a night, so a long TTL
// is right; the panel is not a live gauge of the config.
const TTL_MS = 60_000;

function _refresh(camId) {
  if (!camId || _inflight.has(camId)) return;
  _inflight.add(camId);
  fetchState(camId)
    .then((res) => {
      if (res?.ok) {
        const axes = new Map((res.axes || []).map((a) => [a.label, a]));
        _cache.set(camId, { axes, ts: Date.now() });
      }
    })
    .finally(() => _inflight.delete(camId));
}

function _axis(camId, label) {
  const hit = _cache.get(camId);
  if (!hit || Date.now() - hit.ts > TTL_MS) _refresh(camId);
  return hit?.axes.get(label) || null;
}

/** Effective spawn for (camera, class) — the score a track must clear. */
export function netzSpawnFor(camId, label) {
  const axis = _axis(camId, label);
  return axis ? Number(axis.spawn) : spawnFor(label, E_FACTORY);
}

/** Effective push for (camera, class) — the score that earns a Meldung. */
export function netzPushFor(camId, label) {
  const axis = _axis(camId, label);
  return axis ? Number(axis.push) : pushFor(label, E_FACTORY);
}

/** Drop the cache after a commit so the next paint shows the new line. */
export function invalidateNetzCache(camId) {
  if (camId) _cache.delete(camId);
  else _cache.clear();
}
