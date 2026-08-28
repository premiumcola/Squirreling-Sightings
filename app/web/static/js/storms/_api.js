// ─── storms/_api.js ────────────────────────────────────────────────────────
// The episode endpoints, as thin wrappers over core/api.js.
//
// Read paths never throw: a missing or unreachable endpoint resolves to
// "the archive is empty" rather than an error page. The archive is a
// passive record — an operator scrolling past it while the weather
// service is down should see the same calm empty state they see on day
// one, not a stack trace. Write paths DO throw, because the caller
// applies its change optimistically and must be able to roll it back.

import { apiGet, apiPatch } from '../core/api.js';

const BASE = '/api/weather/episodes';

const EMPTY_FOOTAGE = { groups: {}, total: 0, degraded: [] };

/**
 * GET the whole list, newest first, WITHOUT the samples array.
 * Deliberately un-paginated: the year's Top-3 ranking is computed
 * client-side and a partial page makes correct ranking impossible.
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
 * GET the footage overlapping this episode's window. Always resolves,
 * and the two failure modes are NOT the same thing:
 *
 *   404 — the endpoint or the episode does not exist. Nothing is
 *         wrong with the weather service; there is simply nothing to
 *         show, so this resolves to the empty payload and the column
 *         renders "Keine Aufnahmen in diesem Zeitraum."
 *   anything else — the request never landed. That gets the
 *         `weather_service_unavailable` marker, which the renderer
 *         turns into an explicit "konnten nicht geladen werden" hint.
 *
 * Collapsing the two used to claim the Wetterdienst was unreachable on
 * every detail page while the service was perfectly healthy.
 */
export async function fetchFootage(id) {
  try {
    const d = await apiGet(`${BASE}/${encodeURIComponent(id)}/footage`);
    return d || { ...EMPTY_FOOTAGE };
  } catch (err) {
    if (err?.status === 404) return { ...EMPTY_FOOTAGE };
    return { groups: {}, total: 0, degraded: ['weather_service_unavailable'] };
  }
}

/**
 * PATCH user_class / user_name / user_note. Resolves to the route's
 * `{ok, episode}` envelope; the caller reconciles against
 * `episode` so server-side normalisation (trimming, length limits,
 * rejected class values) is not silently discarded.
 * Throws on failure — the caller reverts and toasts.
 */
export function patchEpisode(id, patch) {
  return apiPatch(`${BASE}/${encodeURIComponent(id)}`, patch);
}
