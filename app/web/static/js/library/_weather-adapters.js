// ─── library/_weather-adapters.js ───────────────────────────────────────
// Stage 4 of the Mediathek + Wetter-Ereignisse merge: one small adapter
// per weather-ish `/api/library` kind (sighting, recap, manual, episode),
// mapping each item onto the shape its existing `weather/_feed.js` card
// builder expects. Grouped in one file — each adapter is a handful of
// lines and all four exist only because `weather/_feed.js`'s builders
// were written against `/api/weather/*`'s own list shapes, not
// `/api/library`'s reduced `extra` (see `library._weather_readers`'s
// module docstring: recap/manual candidates carry a deliberately small
// subset of their manifest, not the full thing).
//
// Every adapter here was written by reading the real `extra` shape in
// `library/_weather_readers.py` side by side with the field reads in
// `weather/_feed.js` — not by guessing. Two drift bugs turned up doing
// that (documented inline below): both readers name the record's own id
// differently than the id field their builder reads.

// ── sighting ──────────────────────────────────────────────────────────
// `weather_candidates` (`weather_episodes/_footage_sources.py`, reused
// by `library._weather_readers`) names the record `sighting_id` in
// `extra`; `sightingCardHTML` reads `s.id`. `s.started_at` /
// `s.sun_event_at` aren't in `extra` at all — they're the library item's
// own top-level `start` (already the correct moment: `_manifest_span`
// picks `sun_event_at`-equivalent semantics into `start` upstream), so
// this maps `item.start` onto `started_at` and leaves `sun_event_at`
// unset, which is exactly the "older records without sun_event_at"
// fallback `sightingCardHTML` already has.
//
// NOT available from the library feed at all, so these render as their
// harmless empty state rather than a real value: `score`/`severity`
// (no percentage chip), `duration_s`/`file_size_bytes` (no bottom-right
// stack), `pinned` (pin button always starts unpinned). None of these
// crash `sightingCardHTML` — they're all guarded with `|| 0` / falsy
// checks already — but a later stage that wants them for real will need
// to widen `weather_candidates`'s `extra`, not patch it here.
export function adaptSightingItem(item) {
  const extra = (item && item.extra) || {};
  return {
    id: extra.sighting_id || item.id,
    event_type: extra.event_type,
    api_snapshot: extra.api_snapshot,
    sun_snapshot: extra.sun_snapshot,
    started_at: item.start,
  };
}

// ── recap ─────────────────────────────────────────────────────────────
// `recap_candidates` names the record `recap_id` in `extra`;
// `recapCardHTML` reads `m.id` (used both for `data-id` and as the
// period-label fallback). `period_label` / `n_clips` / `duration_s`
// already match field-for-field.
export function adaptRecapItem(item) {
  const extra = (item && item.extra) || {};
  return {
    id: extra.recap_id || item.id,
    period_label: extra.period_label,
    n_clips: extra.n_clips,
    duration_s: extra.duration_s,
  };
}

// ── manual ────────────────────────────────────────────────────────────
// `manual_event_candidates` names the record `manual_event_id` in
// `extra`; `manualEventCardHTML` (via its own `data-manual-id`) and
// `manualEventCategories` both read `m.id`. `range_start`/`range_end`
// aren't in `extra` either — they're the library item's own top-level
// `start`/`end` (always both set: a manual candidate is only built when
// both parsed, see `_weather_readers.manual_event_candidates`).
//
// `curves` (drives the "N Kurven" meta line) isn't carried by the
// library feed's reduced `extra` at all — the meta line simply omits
// that segment, the same graceful-absence behaviour `duration_s`/
// `size_mb` already have elsewhere in this package.
export function adaptManualItem(item) {
  const extra = (item && item.extra) || {};
  return {
    id: extra.manual_event_id || item.id,
    name: extra.name,
    categories: extra.categories,
    characteristic: extra.characteristic,
    range_start: item.start,
    range_end: item.end,
  };
}

// ── episode ───────────────────────────────────────────────────────────
// `episode_candidates`'s `extra` is `dict(rec)` — the WHOLE stripped-
// samples episode record straight from `weather_episodes.list_episodes`
// (character, curve_preview, footage_count, user_class/auto_class,
// user_name, started_at, duration_min, id — see `_store.py::
// _strip_samples`, which is what `episodeCardHTML` was written against
// in the first place). No renaming needed; this exists only so every
// kind in this package has the same "one function per kind" shape for
// the dispatcher to call uniformly.
export function adaptEpisodeItem(item) {
  return { ...((item && item.extra) || {}) };
}
