// ─── scripts/uishot/_fixtures.mjs ──────────────────────────────────────────
// The stub data every surface renders against.
//
// Shapes are copied from what the backend actually emits, not invented:
// the camera from routes/cameras.py::api_cameras + camera_runtime/_status.py,
// the media item from library/_motion_reader.py, the netz state from
// routes/_netz_helpers.py::net_state.
//
// Everything is DELIBERATELY fully populated. An empty state hides
// exactly the defects the harness exists to find — a row only overflows
// once it has chips in it, and a button is only dark-on-dark once it is
// rendered.
//
// No real IPs, no real tokens: doc-range values only (RFC 5737).

/** One fully-populated camera, as /api/cameras returns it. */
export const CAMERA = {
  id: 'reolink_rlc810a_garten_51',
  name: 'Garten Nord',
  status: 'active',
  armed: true,
  color: '#4ea3ff',
  rtsp_url: 'rtsp://cam.lan:554/h264Preview_01_main',
  frame_interval_ms: 500,
  preview_fps: 12,
  stream_mode: 'live',
  preview_resolution: '640x360',
  main_resolution: '3840x2160',
  resolution: '3840x2160',
  object_filter: ['person', 'cat', 'bird', 'dog'],
  class_severity: { dog: 'off' },
  telegram_enabled: true,
  mqtt_enabled: true,
  schedule_notify: { enabled: true, from: '21:00', to: '06:00' },
};

/** The ten camera-wide tuning axes the Erkennungsnetz radar draws. */
const TUNING = {
  frame_interval_ms: 500,
  motion_sensitivity: 0.55,
  post_motion_tail_s: 3,
  track_miss_grace_seconds: 2,
  track_iou_match_threshold: 0.35,
  track_spawn_min_score: 0.42,
  track_block_contain: true,
  track_filter_ghosts: true,
  roi_mode: 'soft',
  wildlife_motion_sensitivity: 0.4,
  roi_min_net_disp_frac: 0.12,
};

/** netzState.states[camId] — GET /api/netz/state for one camera. */
export const NETZ_STATE = {
  cam_id: CAMERA.id,
  cam_name: CAMERA.name,
  role: 'garden',
  axes: [
    { label: 'person', E: 62, push: 0.68, push_enabled: true, spawn: 0.42, confirm_n: 2, confirm_s: 1.5, provenance: 'manuell' },
    { label: 'cat', E: 48, push: 0.55, push_enabled: true, spawn: 0.38, confirm_n: 2, confirm_s: 1.2, provenance: 'auto' },
    { label: 'bird', E: 35, push: 0.41, push_enabled: false, spawn: 0.3, confirm_n: 3, confirm_s: 2, provenance: 'auto' },
  ],
  frozen: [{ key: 'confirmation_window', de: 'Bestätigungsfenster' }],
  tuning: TUNING,
};

/** One motion event, as the Mediathek grid receives it. */
function mediaItem(n, over) {
  return {
    event_id: `evt_2026083${n}_1432${n}`,
    camera_id: CAMERA.id,
    labels: ['motion', 'bird'],
    bird_species: 'Grünfink',
    whole_clip: { species: [{ species: 'Grünfink' }, { species: 'Blaumeise' }], truncated: false },
    time: `2026-08-30 1${n}:32:05`,
    snapshot_relpath: `motion_detection/${CAMERA.id}/2026-08-30/e${n}.jpg`,
    video_relpath: `motion_detection/${CAMERA.id}/2026-08-30/e${n}.mp4`,
    duration_s: 12,
    file_size_bytes: 3_100_000,
    confirmed: false,
    ...over,
  };
}

/** A grid's worth of media — mixed labels so the accent colours differ. */
export const MEDIA = [
  mediaItem(1, {}),
  mediaItem(2, { labels: ['motion', 'person'], bird_species: null, whole_clip: null, confirmed: true }),
  mediaItem(3, { labels: ['motion', 'cat'], bird_species: null, whole_clip: null }),
  mediaItem(4, { labels: ['motion'], bird_species: null, whole_clip: null, encode_error: 'ffmpeg exit 1' }),
  mediaItem(5, { labels: ['motion', 'bird'], duration_s: 47, file_size_bytes: 512_000 }),
  mediaItem(6, { labels: ['motion', 'dog'], bird_species: null, whole_clip: null }),
];

/** The recorded clip the operator photographed the player on. */
export const CLIP_ITEM = {
  ...mediaItem(1, {}),
  camera_name: CAMERA.name,
  roi_label: 'Beet Nord',
  recording_settings: { pre_motion_seconds: 3, post_motion_seconds: 5, conf_thresh_general: 0.4 },
  provenance: {
    effective: { spawn_default: 0.42 },
    timing: { pre_roll_s: 3, post_roll_s: 5 },
    model: 'efficientdet_lite0_edgetpu',
    profile: 'garden',
  },
};

/**
 * tracks.json sidecar for that clip — two tracks, so lanes have colour.
 *
 * SHAPE IS tracker_core's, not an approximation of it. Every reader of a
 * sidecar walks `track.samples` (`bbox-overlay/fetcher.js` sorts them by
 * `f`; `vplayer/timeline/_model.js` classifies them by `t` / `source` /
 * `score`), and this fixture used to carry `detections` with `box` and
 * `first_ts` instead — keys nothing in the tree reads. So the sidecar
 * produced tracks with no samples, every lane came back null, and the
 * surface photographed an empty rail no matter what the renderer did.
 * A fixture whose shape the code cannot read tests nothing.
 */
export const TRACKS = {
  schema: 3,
  built_at: '2026-08-30T14:33:10',
  tracks: [
    {
      track_id: 'a1b2c3',
      label: 'bird',
      best_score: 0.71,
      samples: [
        { f: 12, t: 1.2, bbox: { x1: 600, y1: 450, x2: 870, y2: 655 }, score: 0.63, source: 'detect' },
        { f: 36, t: 3.6, bbox: { x1: 730, y1: 430, x2: 1018, y2: 646 }, score: 0.71, source: 'detect' },
        { f: 60, t: 6.0, bbox: { x1: 800, y1: 425, x2: 1070, y2: 640 }, score: 0.31, source: 'detect' },
        { f: 78, t: 7.8, bbox: { x1: 845, y1: 420, x2: 1094, y2: 615 }, score: 0.66, source: 'track' },
      ],
    },
    {
      track_id: 'd4e5f6',
      label: 'cat',
      best_score: 0.58,
      samples: [
        { f: 51, t: 5.1, bbox: { x1: 1150, y1: 594, x2: 1574, y2: 853 }, score: 0.52, source: 'detect' },
        { f: 114, t: 11.4, bbox: { x1: 1267, y1: 572, x2: 1670, y2: 821 }, score: 0.58, source: 'detect' },
      ],
    },
  ],
  frame_size: [1920, 1080],
};

/**
 * The clip the operator photographed: a sidecar that ran and confirmed
 * NOTHING, over an event whose whole-clip aggregate holds two subjects.
 *
 * This is the defect's exact state — the panel lists "Vogel 57 %" and the
 * rail above it was a bare grey line, because the rail was fed the
 * sidecar and only the sidecar. Its own surface rather than a change to
 * CLIP_ITEM, so the sidecar-basis shot above keeps testing the sidecar.
 */
export const CLIP_ONLY_ITEM = {
  ...mediaItem(7, {}),
  camera_name: CAMERA.name,
  roi_label: 'Beet Nord',
  recording_settings: { pre_motion_seconds: 3, post_motion_seconds: 5, conf_thresh_general: 0.4 },
  provenance: {
    effective: { spawn_default: 0.42 },
    timing: { pre_roll_s: 3, post_roll_s: 5 },
    model: 'efficientdet_lite0_edgetpu',
    profile: 'garden',
  },
  // Rows as camera_runtime/_clip_tally.py::ClipTally.rows() writes them:
  // best-scoring first, one row per tracked subject, `track_id` from the
  // LIVE tracker's run (which is why the rail must not number them).
  whole_clip: {
    detections: [
      {
        track_id: 4,
        label: 'squirrel',
        species: null,
        score: 0.61,
        model: 'wildlife_classifier',
        frames: 1,
        first_s: 9.4,
        last_s: 9.4,
      },
      {
        track_id: 2,
        label: 'bird',
        species: 'Grünfink',
        species_latin: 'Chloris chloris',
        score: 0.57,
        model: 'bird_classifier',
        frames: 26,
        first_s: 1.6,
        last_s: 8.2,
      },
      {
        track_id: 9,
        label: 'bird',
        species: 'Blaumeise',
        species_latin: 'Cyanistes caeruleus',
        score: 0.33,
        model: 'bird_classifier',
        frames: 4,
        first_s: 6.1,
        last_s: 7.0,
      },
    ],
    species: [
      { species: 'Grünfink', species_latin: 'Chloris chloris', best_score: 0.57, frames: 26 },
      { species: 'Blaumeise', species_latin: 'Cyanistes caeruleus', best_score: 0.33, frames: 4 },
    ],
    frames: 120,
    truncated: false,
  },
};

/** The indexer ran on that clip and confirmed no track at all. */
export const CLIP_ONLY_TRACKS = { schema: 3, built_at: '2026-08-30T14:35:02', tracks: [] };

/** Weather samples with a real precipitation swing, so a chip pre-lights. */
export const WEATHER_SAMPLES = Array.from({ length: 24 }, (_, i) => ({
  ts: `2026-08-29T${String(i).padStart(2, '0')}:00:00`,
  values: {
    precipitation: i > 13 && i < 19 ? 4 + (i - 13) * 2 : 0,
    snowfall: 0,
    lightning_potential: i > 15 ? 420 : 10,
    visibility: i > 14 ? 2400 : 21000,
    wind_gusts_10m: 12 + i,
    cloud_cover: 40 + i * 2,
    sun_altitude: Math.max(-10, 40 - Math.abs(12 - i) * 5),
  },
}));

export const WEATHER_RANGE = { start: '2026-08-29T14:00:00', end: '2026-08-29T19:00:00' };

/* ── Statistik ────────────────────────────────────────────────────────────
 *
 * A camera the timeline names but /api/cameras does NOT return. That is
 * the precondition for the raw-id leak this surface exists to watch:
 * statistics.js unions the configured cameras with the ids the timeline
 * mentions, and an id with no camera record behind it has no friendly
 * name to print. A fixture with only configured cameras in it would
 * photograph the happy path and see nothing.
 */
const GHOST_CAM = 'reolink_cx810_gartendachterrasse_181';

/** `YYYY-MM-DD HH:MM:SS`, local — the format storage.py writes. */
function stamp(d) {
  const p = (n) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

/**
 * Timeline payloads, as GET /api/timeline returns them.
 *
 * Generated at import time instead of written out as literals, because
 * the panel buckets everything against `Date.now()`: the heatmap draws
 * only for points inside the last 24 h, and the period pills count
 * "Heute" / "Diese Woche" off the wall clock. Frozen timestamps would
 * photograph two empty states instead of the two charts.
 */
function timelinePayloads() {
  const now = Date.now();
  const H = 3600000;
  // 43 events over the month, split 24 / 19 between the two cameras —
  // a two-slice donut and the "43 DIESER MONAT" pill the defect clipped.
  const spread = [0.4, 3, 9, 26, 51, 74, 99, 122, 150, 173, 197, 220, 244, 268];
  const mk = (cam, n, step) =>
    Array.from({ length: n }, (_, i) => ({
      time: stamp(new Date(now - (2 + i * step) * H)),
      camera_id: cam,
    }));
  // `camera_name` is what timeline_stats.py sends. The ghost camera's is
  // its own id, exactly as the route falls back when the settings record
  // carries no name — so this fixture exercises the short-form path, not
  // just the happy one.
  const monthTracks = [
    { camera_id: CAMERA.id, camera_name: CAMERA.name, points: mk(CAMERA.id, 24, 29) },
    { camera_id: GHOST_CAM, camera_name: GHOST_CAM, points: mk(GHOST_CAM, 19, 37) },
  ];
  // Every event carries motion; the classifier labels ride on a subset,
  // so "Top Erkennungen" has three rows with distinct percentages.
  const merged = monthTracks
    .flatMap((t) => t.points)
    .map((p, i) => ({
      ...p,
      labels: ['motion'].concat(i % 3 === 0 ? ['bird'] : [], i % 7 === 0 ? ['person'] : []),
    }));
  const dayTracks = [
    {
      camera_id: CAMERA.id,
      camera_name: CAMERA.name,
      points: spread.map((h) => ({ time: stamp(new Date(now - h * H)), camera_id: CAMERA.id })),
    },
    {
      camera_id: GHOST_CAM,
      camera_name: GHOST_CAM,
      points: spread
        .filter((_, i) => i % 2 === 0)
        .map((h) => ({ time: stamp(new Date(now - (h + 1) * H)), camera_id: GHOST_CAM })),
    },
  ];
  return {
    month: { tracks: monthTracks, merged },
    day: { tracks: dayTracks, merged: dayTracks.flatMap((t) => t.points) },
  };
}

const TIMELINE = timelinePayloads();

/** GET /api/timeline?hours=720 — the month the donut and the pills read. */
export const TIMELINE_MONTH = TIMELINE.month;

/** GET /api/timeline?hours=24 — the rolling window the heatmap reads. */
export const TIMELINE_DAY = TIMELINE.day;

/**
 * GET /api/detection_cloud — one point per confirmed sample.
 * Populated so the Erkennungswolke draws a scatter and its Zeitraum
 * slider sits under a real chart rather than an empty-state line.
 */
export const DETECTION_CLOUD = {
  points: TIMELINE.day.tracks.flatMap((t, ti) =>
    t.points.map((p, i) => ({
      sample_key: `${t.camera_id}:${i}`,
      camera_id: t.camera_id,
      label: ['bird', 'cat', 'person', 'squirrel'][(i + ti) % 4],
      score: 0.35 + ((i * 7) % 60) / 100,
      time: p.time,
      event_id: `evt_dc_${ti}_${i}`,
    })),
  ),
  coverage: { events: 21, sidecars: 19, samples: 21 },
};

/**
 * A full day of history, shaped the way the recorder actually writes it:
 * ONE row per Open-Meteo `minutely_15` slot, so 24 h is 96 samples.
 *
 * It used to be 288 — `_lifecycle.py` polls every `poll_interval`
 * (300 s) and reads the slot covering now, so each measurement was
 * appended three times. That triplication is what drew a ~2.5 px stair
 * tread under every curve on a phone; `_history.py::_record_sample` now
 * skips a slot it has already recorded. Keep this fixture at one row per
 * slot: at three it photographs a staircase the recorder no longer
 * produces.
 *
 * Values come from _consts.py's HISTORY_FIELDS; snowfall stays flat at 0
 * on purpose, because stats.js auto-hides a field that never moved and
 * the real panel is therefore six lines, not seven.
 */
const _WX_SLOTS = 96; // 24 h ÷ 15 min
function _wxSlot(i) {
  const h = (i * 15) / 60; // hour of day, 0…24
  const storm = Math.exp(-((h - 16.5) ** 2) / 2.2); // afternoon cell
  return {
    precipitation: +(storm * 11).toFixed(2),
    snowfall: 0,
    lightning_potential: Math.round(30 + storm * 1900),
    visibility: Math.round(24000 - storm * 21500),
    wind_gusts_10m: +(14 + Math.sin(h / 2.4) * 6 + storm * 34).toFixed(1),
    cloud_cover: Math.min(100, Math.round(28 + Math.sin(h / 3.1) * 22 + storm * 60)),
    sun_altitude: +(Math.sin(((h - 6) / 12) * Math.PI) * 52).toFixed(1),
  };
}
export const WEATHER_HISTORY = {
  hours: 24,
  samples: Array.from({ length: _WX_SLOTS }, (_, n) => {
    const d = new Date(Date.UTC(2026, 7, 29) + n * 15 * 60_000);
    return { ts: d.toISOString().slice(0, 19), values: _wxSlot(n) };
  }),
  bucket_size: 1,
  units: {
    precipitation: 'mm/h',
    snowfall: 'cm/h',
    lightning_potential: 'J/kg',
    visibility: 'm',
    wind_gusts_10m: 'km/h',
    cloud_cover: '%',
    sun_altitude: '°',
  },
  thresholds: { precipitation: 6, lightning_potential: 1000, wind_gusts_10m: 60, visibility: 3000 },
  events_enabled: { precipitation: true, lightning_potential: true, wind_gusts_10m: false },
  labels_de: {
    precipitation: 'Niederschlag',
    snowfall: 'Schneefall',
    lightning_potential: 'Blitzpotenzial',
    visibility: 'Sichtweite',
    wind_gusts_10m: 'Windböen',
    cloud_cover: 'Bewölkung',
    sun_altitude: 'Sonnenstand',
  },
  fields: [
    'precipitation',
    'snowfall',
    'lightning_potential',
    'visibility',
    'wind_gusts_10m',
    'cloud_cover',
    'sun_altitude',
  ],
  poll_interval_s: 300,
  extent: {
    oldest: '2026-08-29T00:00:00',
    newest: '2026-08-29T23:45:00',
    count: _WX_SLOTS,
  },
};

/**
 * A day-old install: three hours in the buffer and nothing before that.
 *
 * The state the range picker was wrong about — it offered 7 d and 30 d
 * regardless, so those windows drew three hours of data stretched across
 * a month-wide axis. Its own surface, because the fully-populated
 * archive above cannot also be a sparse one.
 */
export const WEATHER_HISTORY_SPARSE = {
  ...WEATHER_HISTORY,
  hours: 24,
  samples: WEATHER_HISTORY.samples.slice(56, 69), // 3 h across the storm
  extent: {
    oldest: WEATHER_HISTORY.samples[56].ts,
    newest: WEATHER_HISTORY.samples[68].ts,
    count: 13,
  },
};

// ── /api/timelapse/status ─────────────────────────────────────────────────
// The interesting state for the live tile: one camera recording a
// periodic profile AND two weather captures in flight. Both halves are
// posed at once, because the pill renders a different chip for each and
// the panel stacks the running block above the profile cards.
//
// The `sun` array deliberately also carries a phase that is NOT running,
// with the skip reason the scheduler recorded. Nothing on this surface
// may render it — the tile answers "what is happening now" and the
// skip reasons live with the configuration. That is what the picture
// checks.
export const TL_STATUS = {
  ok: true,
  active_count: 1,
  today: '2026-09-03',
  cameras: [
    {
      camera_id: 'reolink_rlc810a_garten_42',
      name: 'Garten',
      any_active: true,
      profiles: {
        daily: {
          enabled: true,
          interval_s: 8,
          interval_clamped: false,
          fps: 15,
          expected_frames: 10800,
          frame_count: 4120,
          bytes_on_disk: 1236000000,
          projected_bytes: 3240000000,
          rejected: 17,
          next_build_at: '2026-09-04T00:05:00',
        },
        weekly: { enabled: false },
        monthly: { enabled: false },
        quarterly: { enabled: false },
        yearly: { enabled: false },
        custom: { enabled: false },
      },
    },
  ],
  weather: {
    available: true,
    running_count: 2,
    sun: [
      {
        camera_id: 'reolink_rlc810a_garten_42',
        camera_name: 'Garten',
        phase: 'sunset',
        phase_text: 'Sonnenuntergang',
        state: 'running',
        state_text: 'läuft',
        skip_reason: null,
        skip_text: null,
        remaining_s: 1980,
        window_end: '2026-09-03T20:20:00',
      },
      {
        camera_id: 'reolink_rlc810a_garten_42',
        camera_name: 'Garten',
        phase: 'sunrise',
        phase_text: 'Sonnenaufgang',
        state: 'skipped',
        state_text: 'übersprungen',
        skip_reason: 'window_passed',
        skip_text: 'Fenster war schon vorbei',
        remaining_s: null,
      },
    ],
    event: [
      {
        camera_id: 'reolink_rlc810a_hof_43',
        camera_name: 'Hof',
        trigger: 'storm_front',
        trigger_text: 'Sturmfront',
        state: 'running',
        state_text: 'läuft',
        remaining_s: 2640,
        window_end: '2026-09-03T21:04:00',
      },
    ],
  },
};
