// ─── library/_tests/dispatch.test.js ────────────────────────────────────
// Dispatch correctness: one fixture per `/api/library` kind, shaped like
// the REAL item + `extra` each reader in `library/_motion_reader.py` /
// `library/_weather_readers.py` actually produces (not an invented
// shape) — asserts `libraryCardHTML` calls through to the right existing
// builder by checking for markup only THAT builder emits, and that an
// unrecognised kind renders a safe fallback instead of throwing.
import './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { libraryCardHTML } from '../index.js';

const MOTION_ITEM = {
  kind: 'motion',
  id: 'motion:e1',
  cam_id: 'cam1',
  cam_name: 'Cam 1',
  start: '2026-08-30T12:00:00',
  end: '2026-08-30T12:01:00',
  video_url: '/media/motion_detection/cam1/2026-08-30/e1.mp4',
  thumb_url: '/media/motion_detection/cam1/2026-08-30/e1.jpg',
  missing_media: false,
  // The whole raw event JSON — see motion_reader.py::motion_candidate.
  extra: {
    event_id: 'e1',
    camera_id: 'cam1',
    time: '2026-08-30T12:00:00',
    labels: ['fox'],
    snapshot_relpath: 'motion_detection/cam1/2026-08-30/e1.jpg',
    video_relpath: 'motion_detection/cam1/2026-08-30/e1.mp4',
    duration_s: 12,
  },
};

const SIGHTING_ITEM = {
  kind: 'sighting',
  id: 'sighting:sight_1',
  cam_id: 'cam1',
  cam_name: 'Cam 1',
  start: '2026-08-30T12:00:00',
  end: '2026-08-30T12:00:30',
  video_url: '/api/weather/sightings/sight_1/clip',
  thumb_url: '/api/weather/sightings/sight_1/thumb',
  missing_media: false,
  // Real weather_candidates() shape (weather_episodes/_footage_sources.py).
  extra: { sighting_id: 'sight_1', event_type: 'thunder', api_snapshot: null, sun_snapshot: null },
};

const RECAP_ITEM = {
  kind: 'recap',
  id: 'recap:recap_1',
  cam_id: '',
  cam_name: '',
  start: '2026-06-01T00:00:00',
  end: '2026-06-30T23:59:59',
  video_url: '/api/weather/recaps/recap_1/clip',
  thumb_url: '',
  missing_media: false,
  extra: { recap_id: 'recap_1', period_label: 'Q2 2026', n_clips: 5, duration_s: 90 },
};

const MANUAL_ITEM = {
  kind: 'manual',
  id: 'manual:m1',
  cam_id: '',
  cam_name: '',
  start: '2026-08-30T12:00:00',
  end: '2026-08-30T12:30:00',
  video_url: '',
  thumb_url: '',
  missing_media: true,
  extra: {
    manual_event_id: 'm1',
    name: 'Regenguss',
    categories: ['heavy_rain'],
    characteristic: null,
  },
};

const EPISODE_ITEM = {
  kind: 'episode',
  id: 'episode:ep_1',
  cam_id: '',
  cam_name: '',
  start: '2026-08-30T12:00:00',
  end: '2026-08-30T12:30:00',
  video_url: '',
  thumb_url: '',
  missing_media: true,
  // The whole stripped-samples episode record (_store.py::_strip_samples).
  extra: {
    id: 'ep_1',
    started_at: '2026-08-30T12:00:00',
    ended_at: '2026-08-30T12:30:00',
    duration_min: 30,
    user_class: 'thunder',
    character: 'single_spike',
    curve_preview: { field: 'cape', values: [1, 2, 3, 4] },
  },
};

const TIMELAPSE_ITEM = {
  kind: 'timelapse',
  id: 'timelapse:cam1:2026-08-30',
  cam_id: 'cam1',
  cam_name: 'Cam 1',
  start: '2026-08-29T00:00:00',
  end: '2026-08-30T00:00:00',
  video_url: '/media/timelapse/cam1/2026-08-30.mp4',
  thumb_url: '/media/timelapse/cam1/2026-08-30.jpg',
  missing_media: false,
  extra: { profile: 'daily' },
};

test('motion kind dispatches to mediaCardHTML', () => {
  const html = libraryCardHTML(MOTION_ITEM, {});
  assert.match(html, /class="media-card /);
  assert.match(html, /data-event-id="e1"/);
});

test('sighting kind dispatches to sightingCardHTML', () => {
  const html = libraryCardHTML(SIGHTING_ITEM, {});
  assert.match(html, /class="ws-card/);
  assert.match(html, /data-id="sight_1"/);
});

test('recap kind dispatches to recapCardHTML', () => {
  const html = libraryCardHTML(RECAP_ITEM, {});
  assert.match(html, /data-recap-idx="0"/);
  assert.match(html, /data-id="recap_1"/);
});

test('manual kind dispatches to manualEventCardHTML', () => {
  const html = libraryCardHTML(MANUAL_ITEM, {});
  assert.match(html, /class="ws-recap-card ws-manual-card"/);
  assert.match(html, /data-manual-id="m1"/);
});

test('episode kind dispatches to episodeCardHTML', () => {
  const html = libraryCardHTML(EPISODE_ITEM, {});
  assert.match(html, /data-ep-id="ep_1"/);
  // The character badge is episodeCardHTML's own distinguishing feature
  // (Stage 5) — proves the full extra record, not a trimmed copy, made
  // it through the adapter.
  assert.match(html, /ws-ep-character/);
});

test('timelapse kind dispatches to the new timelapseCardHTML', () => {
  const html = libraryCardHTML(TIMELAPSE_ITEM, {});
  assert.match(html, /class="media-card mmc-tl"/);
  assert.match(html, /data-lib-id="timelapse:cam1:2026-08-30"/);
});

test('an unrecognised kind renders a safe fallback instead of throwing', () => {
  const html = libraryCardHTML({ kind: 'weird_future_kind', id: 'x:1', cam_name: 'Whatever' }, {});
  assert.match(html, /lib-card--unknown/);
  assert.match(html, /data-lib-kind="weird_future_kind"/);
});

test('a malformed item (no kind at all) does not throw', () => {
  assert.doesNotThrow(() => libraryCardHTML({}, {}));
  assert.doesNotThrow(() => libraryCardHTML(null, {}));
  assert.match(libraryCardHTML(null, {}), /lib-card--unknown/);
});
