// ─── library/_motion-adapter.js ─────────────────────────────────────────
// Stage 4 of the Mediathek + Wetter-Ereignisse merge: maps one `/api/
// library` item of kind "motion" onto the shape `mediathek/_cards.js
// ::mediaCardHTML` expects.
//
// No renaming needed. `library._motion_reader.motion_candidate`'s own
// docstring says it plainly: "the whole event payload rides along in
// extra... clients hand motion tiles to the existing lightbox, which
// speaks exactly the shape /api/camera/<id>/media returns" — and that
// route's items ARE the raw event JSON (`media_index._visible.
// visible_media_events` returns `store.list_events(...)` untouched).
// mediaCardHTML was built against exactly that shape, so `item.extra`
// already carries every field it reads (`event_id`, `camera_id`,
// `labels`, `bird_species`, `time`, `snapshot_relpath`, `video_relpath`,
// `duration_s`, `file_size_bytes`, `encode_error`, `confirmed`). It also
// never carries a `type` key, so mediaCardHTML's own
// `item.type === 'timelapse'` dispatch correctly falls through to its
// motion branch — nothing here has to force that.
//
// The two-field fallback below only guards a hypothetically thin
// `extra` (e.g. a future reader that trims the payload) — real motion
// items today never need it.
export function adaptMotionItem(item) {
  const extra = (item && item.extra) || {};
  return {
    ...extra,
    event_id: extra.event_id || item.id,
    camera_id: extra.camera_id || item.cam_id,
  };
}
