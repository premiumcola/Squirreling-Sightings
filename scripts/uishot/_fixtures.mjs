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

/** tracks.json sidecar for that clip — two tracks, so lanes have colour. */
export const TRACKS = {
  tracks: [
    {
      id: 1,
      label: 'bird',
      score: 0.71,
      first_ts: 1.2,
      last_ts: 7.8,
      detections: [
        { t: 1.2, score: 0.63, box: [0.31, 0.42, 0.14, 0.19] },
        { t: 3.6, score: 0.71, box: [0.38, 0.4, 0.15, 0.2] },
        { t: 7.8, score: 0.66, box: [0.44, 0.39, 0.13, 0.18] },
      ],
    },
    {
      id: 2,
      label: 'cat',
      score: 0.58,
      first_ts: 5.1,
      last_ts: 11.4,
      detections: [
        { t: 5.1, score: 0.52, box: [0.6, 0.55, 0.22, 0.24] },
        { t: 11.4, score: 0.58, box: [0.66, 0.53, 0.21, 0.23] },
      ],
    },
  ],
  frame_size: [1920, 1080],
};

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
