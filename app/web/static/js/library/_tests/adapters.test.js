// ─── library/_tests/adapters.test.js ────────────────────────────────────
// Field-adapter correctness: each adapter fed a REALISTIC `/api/library`
// item (matching what `library/_motion_reader.py` /
// `library/_weather_readers.py` actually emit — read directly from
// source, not guessed) must produce the exact field names/shapes the
// underlying `weather/_feed.js` builder reads. This is the test that
// would have caught the two real drift bugs found while building this
// package: `recap_candidates`/`manual_event_candidates` name the record
// `recap_id`/`manual_event_id` in `extra`, but `recapCardHTML`/
// `manualEventCardHTML` read `m.id`.
import './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { adaptMotionItem } from '../_motion-adapter.js';
import {
  adaptSightingItem,
  adaptRecapItem,
  adaptManualItem,
  adaptEpisodeItem,
} from '../_weather-adapters.js';

test('adaptMotionItem passes the raw event JSON through unrenamed', () => {
  const item = {
    kind: 'motion',
    id: 'motion:e1',
    cam_id: 'cam1',
    extra: {
      event_id: 'e1',
      camera_id: 'cam1',
      time: '2026-08-30T12:00:00',
      labels: ['fox'],
      bird_species: null,
      snapshot_relpath: 'motion_detection/cam1/2026-08-30/e1.jpg',
      video_relpath: 'motion_detection/cam1/2026-08-30/e1.mp4',
      duration_s: 12,
      file_size_bytes: 555,
      confirmed: true,
    },
  };
  const out = adaptMotionItem(item);
  assert.equal(out.event_id, 'e1');
  assert.equal(out.camera_id, 'cam1');
  assert.equal(out.labels[0], 'fox');
  assert.equal(out.video_relpath, 'motion_detection/cam1/2026-08-30/e1.mp4');
  assert.equal(out.confirmed, true);
  // Never a `type` key, so mediaCardHTML's own `type === 'timelapse'`
  // dispatch falls through to its motion branch.
  assert.equal(out.type, undefined);
});

test('adaptMotionItem falls back to the top-level id/cam_id when extra is thin', () => {
  const out = adaptMotionItem({ id: 'motion:e2', cam_id: 'cam2', extra: {} });
  assert.equal(out.event_id, 'motion:e2');
  assert.equal(out.camera_id, 'cam2');
});

test('adaptSightingItem renames sighting_id to id and sources started_at from the top-level start', () => {
  const item = {
    id: 'sighting:sight_1',
    start: '2026-08-30T12:00:00',
    extra: {
      sighting_id: 'sight_1',
      event_type: 'thunder',
      api_snapshot: { precipitation: 0.4 },
      sun_snapshot: null,
    },
  };
  const out = adaptSightingItem(item);
  assert.equal(out.id, 'sight_1', 'must read extra.sighting_id, not the library item id');
  assert.equal(out.event_type, 'thunder');
  assert.equal(out.started_at, '2026-08-30T12:00:00');
  assert.deepEqual(out.api_snapshot, { precipitation: 0.4 });
});

test('adaptRecapItem renames recap_id to id', () => {
  const item = {
    id: 'recap:recap_1',
    extra: { recap_id: 'recap_1', period_label: 'Q2 2026', n_clips: 5, duration_s: 90 },
  };
  const out = adaptRecapItem(item);
  assert.equal(out.id, 'recap_1', 'recapCardHTML reads m.id, not m.recap_id');
  assert.equal(out.period_label, 'Q2 2026');
  assert.equal(out.n_clips, 5);
  assert.equal(out.duration_s, 90);
});

test('adaptManualItem renames manual_event_id to id and sources range_start/end from top-level start/end', () => {
  const item = {
    id: 'manual:m1',
    start: '2026-08-30T12:00:00',
    end: '2026-08-30T12:30:00',
    extra: {
      manual_event_id: 'm1',
      name: 'Regenguss',
      categories: ['heavy_rain'],
      characteristic: null,
    },
  };
  const out = adaptManualItem(item);
  assert.equal(out.id, 'm1', 'manualEventCardHTML reads m.id, not m.manual_event_id');
  assert.equal(out.name, 'Regenguss');
  assert.deepEqual(out.categories, ['heavy_rain']);
  assert.equal(out.range_start, '2026-08-30T12:00:00');
  assert.equal(out.range_end, '2026-08-30T12:30:00');
});

test('adaptEpisodeItem is an identity pass-through of the full stripped-samples record', () => {
  const rec = {
    id: 'ep_1',
    started_at: '2026-08-30T12:00:00',
    duration_min: 30,
    user_class: 'thunder',
    character: 'single_spike',
    curve_preview: { field: 'cape', values: [1, 2] },
    footage_count: 4,
  };
  const out = adaptEpisodeItem({ id: 'episode:ep_1', extra: rec });
  assert.deepEqual(out, rec);
});
