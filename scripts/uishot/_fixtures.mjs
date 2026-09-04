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
  // Inclusion zone + exclusion mask, stamped in the stand-in clip's own
  // 640x360 space (see TRACKS). Without these the player's Zonen and
  // Masken switches sit over an empty layer and the shot cannot show
  // whether they do anything — which is exactly the defect the harness
  // failed to catch the first time.
  zones: [
    {
      name: 'Beet Nord',
      source_w: 640,
      source_h: 360,
      points: [
        { x: 190, y: 175 },
        { x: 470, y: 165 },
        { x: 500, y: 320 },
        { x: 170, y: 315 },
      ],
    },
  ],
  masks: [
    {
      name: 'Gehweg',
      source_w: 640,
      source_h: 360,
      points: [
        { x: 20, y: 250 },
        { x: 170, y: 250 },
        { x: 170, y: 345 },
        { x: 20, y: 345 },
      ],
    },
  ],
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
  // SIX class axes, not three. A real garden camera runs person, cat,
  // dog, bird, squirrel and car, and the axis count is what decides how
  // tall the radar has to be and how many rows the legend below it
  // wraps to. With three axes the card fit its height-locked box in the
  // harness while the operator's own screenshot showed a scrollbar down
  // the side of every one of them — a fixture thinner than the real
  // data cannot photograph a layout that only breaks when it is full.
  axes: [
    {
      label: 'person',
      E: 62,
      push: 0.68,
      push_enabled: true,
      spawn: 0.42,
      confirm_n: 2,
      confirm_s: 1.5,
      provenance: 'manuell',
    },
    {
      label: 'cat',
      E: 48,
      push: 0.55,
      push_enabled: true,
      spawn: 0.38,
      confirm_n: 2,
      confirm_s: 1.2,
      provenance: 'auto',
    },
    {
      label: 'bird',
      E: 35,
      push: 0.41,
      push_enabled: false,
      spawn: 0.3,
      confirm_n: 3,
      confirm_s: 2,
      provenance: 'auto',
    },
    {
      label: 'dog',
      E: 44,
      push: 0.5,
      push_enabled: true,
      spawn: 0.36,
      confirm_n: 2,
      confirm_s: 1.4,
      provenance: 'auto',
    },
    {
      label: 'squirrel',
      E: 71,
      push: 0.62,
      push_enabled: true,
      spawn: 0.34,
      confirm_n: 2,
      confirm_s: 1.1,
      provenance: 'manuell',
    },
    {
      label: 'car',
      E: 28,
      push: 0.33,
      push_enabled: false,
      spawn: 0.45,
      confirm_n: 3,
      confirm_s: 2.2,
      provenance: 'auto',
    },
  ],
  frozen: [{ key: 'confirmation_window', de: 'Bestätigungsfenster' }],
  tuning: TUNING,
};

/**
 * One tick of POST /api/cameras/<id>/test-detection — the simulation's
 * whole world.
 *
 * Shaped from routes/coral_test_detection.py's own response body, not
 * invented: `modes` is _sim_debug.modes_block (the ROI and device chips
 * read `roi_mode_active` and `inference.device` off it), `detections`
 * are the pre-gate rows with their verdicts, `decision_trace` feeds the
 * track-events list and `debug.tracks` the track rows.
 *
 * It exists because the harness could not exercise the simulation at
 * all: with no answer for this endpoint the poll loop only ever saw a
 * network error, so no shot and no probe could tell a loop that was
 * running from one that had never been started — which is exactly the
 * defect that shipped.
 */
export const SIM_TICK = {
  ok: true,
  snapshot: null,
  frame_size: { w: 640, h: 360 },
  frame_age_ms: 120,
  frame_interval_avg_ms: 350,
  decoder_backlog_suspected: false,
  revision: null,
  detections: [
    {
      label: 'person',
      score: 0.81,
      bbox: [210, 90, 120, 210],
      verdict: 'pass',
      track_num: 1,
      model: 'coco',
    },
    {
      label: 'cat',
      score: 0.34,
      bbox: [420, 200, 90, 70],
      verdict: 'tentative',
      track_num: 2,
      model: 'coco',
    },
    {
      label: 'bird',
      score: 0.29,
      bbox: [60, 250, 40, 35],
      verdict: 'masked',
      track_num: null,
      model: 'coco',
    },
  ],
  decision_trace: [
    { t: 'SPAWN', track: 1, label: 'person', score: 0.81 },
    { t: 'HOLD', track: 2, label: 'cat', score: 0.34 },
  ],
  diag: { motion_px: 4210, gate: 'motion', roi_tiles: 4 },
  cluster_evidence: null,
  modes: {
    inference: { device: 'tpu', model: 'efficientdet_lite0_edgetpu' },
    role: 'garden',
    alarm_profile: 'standard',
    detection_trigger: 'motion',
    roi_mode: '2x2',
    roi_mode_active: '2x2',
  },
  models: {
    coco: { file: 'coco_ssd_mobilenet_v2_edgetpu.tflite', sha256: 'ab12cd34' },
  },
  debug: {
    tracks: [
      { num: 1, label: 'person', score: 0.81, state: 'active', age_s: 4.2, misses: 0 },
      { num: 2, label: 'cat', score: 0.34, state: 'coasting', age_s: 1.1, misses: 2 },
    ],
  },
};

/**
 * The `tpu` block of GET /api/status, as detectors/_utilisation.py's
 * fleet_tpu_utilisation writes it. The simulation panel's TPU chip
 * reads it through tpuFor(status, camId) — from the STATUS payload, not
 * from the frame, which is why a panel handed a null status can never
 * fill that chip however well the poll loop is running.
 */
// Field names are detectors/_utilisation.py::_readouts's own — `busy`
// is the 0..1 fraction the chip prints, and it is NOT called
// `busy_ratio`, which is what this fixture said on the first pass. A
// stub that invents a field name renders a placeholder and proves the
// chip broken when it is fine.
export const TPU_STATUS = {
  window_s: 60,
  total: { count: 118, busy_s: 1.74, span_s: 4.1, mean_ms: 14.7, per_s: 28.8, busy: 0.424 },
  cameras: {
    [CAMERA.id]: { count: 118, busy_s: 1.74, span_s: 4.1, mean_ms: 14.7, per_s: 28.8, busy: 0.424 },
  },
};

/** A landscape and a PORTRAIT reference photo.
 *
 * Different shapes on purpose: the defect being photographed is two
 * reference photos standing at different widths beside each other, and
 * two landscape sources cannot show it. Solid blocks with a marked
 * "head" third, so a crop that eats the head is visible in the shot.
 *
 * Served over http by _server.mjs rather than inlined as a data: URI.
 * Real photo URLs are `https://upload.wikimedia.org/…`, and the code
 * treats the two differently: the blurred hero ground runs its URL
 * through core/dom.js's `cssUrl` allowlist, which admits http(s) and
 * root-relative paths only. With data: fixtures that ground silently
 * did not paint, so the harness photographed a state production never
 * reaches — the fourth time this session that a fixture was thinner
 * than reality and hid the thing it was pointed at.
 */
export const REF_PHOTOS = new Map();

function _refPhoto(w, h, body, head) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">` +
    `<rect width="${w}" height="${h}" fill="#20303c"/>` +
    `<rect x="0" y="0" width="${w}" height="${Math.round(h * 0.34)}" fill="${head}"/>` +
    `<ellipse cx="${w / 2}" cy="${h * 0.46}" rx="${w * 0.26}" ry="${h * 0.2}" fill="${body}"/>` +
    `<text x="${w / 2}" y="${Math.round(h * 0.2)}" text-anchor="middle" font-family="sans-serif" ` +
    `font-size="${Math.round(Math.min(w, h) * 0.11)}" fill="#0d1116">KOPF</text></svg>`;
  const name = `/__fixture__/ref-${w}x${h}-${body.replace('#', '')}.svg`;
  REF_PHOTOS.set(name, svg);
  return name;
}

/** /api/library?kinds=motion rows — the shape _motion-adapter.js reads:
 *  everything real lives under `extra`. Two clips so the gallery's paging
 *  arrows render too. */
export const DOSSIER_CLIPS = {
  items: [
    {
      kind: 'motion',
      id: 'evt_hrs_1',
      cam_id: CAMERA.id,
      extra: {
        ...mediaItem(1, {}),
        event_id: 'evt_hrs_1',
        labels: ['motion', 'bird'],
        bird_species: 'Hausrotschwanz',
        duration_s: 11,
      },
    },
    {
      kind: 'motion',
      id: 'evt_hrs_2',
      cam_id: CAMERA.id,
      extra: {
        ...mediaItem(2, {}),
        event_id: 'evt_hrs_2',
        labels: ['motion', 'bird'],
        bird_species: 'Hausrotschwanz',
        duration_s: 6,
      },
    },
  ],
  total: 2,
};

export const DOSSIERS = [
  {
    latin: 'Phoenicurus ochruros',
    common_name_de: 'Hausrotschwanz',
    tier: 'Regelmäßig',
    seen_count: 1,
    wikipedia_summary:
      'Der Hausrotschwanz ist ein Singvogel aus der Familie der Fliegenschnäpper (Muscicapidae). ' +
      'Er ist etwas kleiner als der Haussperling und vor allem an seinem rostorangen Schwanz zu erkennen.',
    wikipedia_url: 'https://de.wikipedia.org/wiki/Hausrotschwanz',
    photo_urls: [
      _refPhoto(640, 420, '#c2703a', '#3d5568'),
      _refPhoto(360, 620, '#a8603a', '#41607a'),
    ],
    recordings: [],
    audio_url: null,
  },
];

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
  mediaItem(2, {
    labels: ['motion', 'person'],
    bird_species: null,
    whole_clip: null,
    confirmed: true,
  }),
  mediaItem(3, { labels: ['motion', 'cat'], bird_species: null, whole_clip: null }),
  mediaItem(4, {
    labels: ['motion'],
    bird_species: null,
    whole_clip: null,
    encode_error: 'ffmpeg exit 1',
  }),
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
 *
 * COORDINATES ARE THE STAND-IN CLIP'S OWN. A sidecar's bbox space is by
 * contract the pixel space of the mp4 it sits next to, and every painter
 * reads the source size off the media element. These used to be authored
 * against 1920x1080 while _clip.mjs renders 640x360, so a box drawn from
 * them landed three times too far right and low — outside the picture
 * entirely for the cat. The same failure the shape note above describes,
 * one level down: a fixture whose COORDINATES the clip cannot hold
 * photographs nothing. The cat is left straddling the exclusion mask on
 * purpose, so the shot shows a masked box as well as a plain one.
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
        {
          f: 12,
          t: 1.2,
          bbox: { x1: 200, y1: 150, x2: 290, y2: 218 },
          score: 0.63,
          source: 'detect',
        },
        {
          f: 36,
          t: 3.6,
          bbox: { x1: 243, y1: 143, x2: 339, y2: 215 },
          score: 0.71,
          source: 'detect',
        },
        {
          f: 60,
          t: 6.0,
          bbox: { x1: 267, y1: 142, x2: 357, y2: 213 },
          score: 0.31,
          source: 'detect',
        },
        {
          f: 78,
          t: 7.8,
          bbox: { x1: 282, y1: 140, x2: 365, y2: 205 },
          score: 0.66,
          source: 'track',
        },
      ],
    },
    {
      track_id: 'd4e5f6',
      label: 'cat',
      best_score: 0.58,
      samples: [
        {
          f: 51,
          t: 5.1,
          bbox: { x1: 60, y1: 198, x2: 165, y2: 284 },
          score: 0.52,
          source: 'detect',
        },
        {
          f: 114,
          t: 11.4,
          bbox: { x1: 48, y1: 191, x2: 158, y2: 274 },
          score: 0.58,
          source: 'detect',
        },
      ],
    },
  ],
  frame_size: [640, 360],
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
