// ─── storms/_api.js ────────────────────────────────────────────────────────
// The five episode endpoints, as thin wrappers over core/api.js.
//
// Read paths never throw: a missing or unreachable endpoint resolves to
// "the archive is empty" rather than an error page. The archive is a
// passive record — an operator scrolling past it while the weather
// service is down should see the same calm empty state they see on day
// one, not a stack trace. Write paths DO throw, because the caller
// applies its change optimistically and must be able to roll it back.

import { apiGet, apiPatch, apiDelete } from '../core/api.js';

const BASE = '/api/weather/episodes';

/**
 * GET the whole list, newest first, WITHOUT the samples array.
 * Deliberately un-paginated (backend §9.3): the year's Top-3 ranking is
 * computed client-side and a partial page makes correct ranking
 * impossible.
 *
 * @returns {Promise<{items: Array, ok: boolean}>}
 */
export async function fetchEpisodes() {
  try {
    const d = await apiGet(BASE);
    const items = Array.isArray(d) ? d : d?.items || d?.episodes || [];
    return { items, ok: true };
  } catch {
    return { items: [], ok: false };
  }
}

/** GET one episode INCLUDING its samples. null when unavailable. */
export async function fetchEpisode(id) {
  try {
    return await apiGet(`${BASE}/${encodeURIComponent(id)}`);
  } catch {
    return null;
  }
}

/**
 * GET the footage overlapping this episode's window. Always resolves;
 * the endpoint itself never 404s on "no footage" (backend §9.1), and a
 * transport failure degrades to the same shape with a `degraded` marker
 * the renderer already knows how to display.
 */
export async function fetchFootage(id) {
  try {
    const d = await apiGet(`${BASE}/${encodeURIComponent(id)}/footage`);
    return d || { groups: {}, total: 0, degraded: [] };
  } catch {
    return { groups: {}, total: 0, degraded: ['weather_service_unavailable'] };
  }
}

/**
 * PATCH user_class / user_name / user_note. Returns the full updated
 * record (backend §9.5) so the optimistic UI reconciles against the
 * server's own view instead of assuming its write landed verbatim.
 * Throws on failure — the caller reverts and toasts.
 */
export function patchEpisode(id, patch) {
  return apiPatch(`${BASE}/${encodeURIComponent(id)}`, patch);
}

/** DELETE → tombstone. Throws on failure. */
export function deleteEpisode(id) {
  return apiDelete(`${BASE}/${encodeURIComponent(id)}`);
}
